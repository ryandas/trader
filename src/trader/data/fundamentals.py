"""Dated fundamentals snapshots (point-in-time by construction).

yfinance only serves TODAY's figures, with later revisions folded in and no publication dates, so
backtesting on them would leak the future. Instead we save a copy per run, named by the day it was
taken (`data/fundamentals/<YYYY-MM-DD>.parquet`). A strategy may only read the newest snapshot dated
on or before the day it is deciding (`asof` / `panel`). Until several years of snapshots exist there
is no fair backtest history, so fundamentals-based candidates are forward-paper-only.
"""
from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

# column name -> yfinance Ticker.info key
FIELDS = {
    "market_cap": "marketCap",
    "pe": "trailingPE",
    "pb": "priceToBook",
    "roe": "returnOnEquity",
    "debt_to_equity": "debtToEquity",
    "op_margin": "operatingMargins",
    "earnings_growth": "earningsGrowth",
    "revenue_growth": "revenueGrowth",
    "fcf": "freeCashflow",
}


def snapshot_dates(fund_dir: Path | None) -> list[pd.Timestamp]:
    if fund_dir is None or not Path(fund_dir).exists():
        return []
    return sorted(pd.Timestamp(p.stem) for p in Path(fund_dir).glob("*.parquet"))


def latest_snapshot_date(fund_dir: Path | None) -> pd.Timestamp | None:
    d = snapshot_dates(fund_dir)
    return d[-1] if d else None


def asof(fund_dir: Path | None, day) -> pd.DataFrame:
    """Snapshot (index = symbol) of the newest copy dated on or before `day`; empty if none exists."""
    day = pd.Timestamp(day)
    ok = [d for d in snapshot_dates(fund_dir) if d <= day]
    if not ok:
        return pd.DataFrame(columns=list(FIELDS))
    return pd.read_parquet(Path(fund_dir) / f"{ok[-1].date()}.parquet")


def panel(fund_dir: Path | None, dates: pd.DatetimeIndex, syms: list[str], field: str) -> np.ndarray:
    """(len(dates) x len(syms)) values of `field` as known on each date (NaN before the first snapshot)."""
    out = np.full((len(dates), len(syms)), np.nan)
    snaps = snapshot_dates(fund_dir)
    if not snaps:
        return out
    pos = {s: i for i, s in enumerate(syms)}
    # snapshot k covers dates in [snaps[k], snaps[k+1]); a date before snaps[0] stays NaN
    bounds = [int(dates.searchsorted(d, side="left")) for d in snaps] + [len(dates)]
    for k, d in enumerate(snaps):
        lo, hi = bounds[k], bounds[k + 1]
        if lo >= hi:
            continue
        df = pd.read_parquet(Path(fund_dir) / f"{d.date()}.parquet")
        if field not in df:
            continue
        row = np.full(len(syms), np.nan)
        for sym, v in df[field].items():
            if sym in pos:
                row[pos[sym]] = v
        out[lo:hi] = row
    return out


def snapshot(fund_dir: Path, symbols: list[str], day: date | None = None, pause: float = 0.3, retries: int = 2):
    """Fetch today's fundamentals for `symbols` and save them as `<day>.parquet`.
    Returns (path, rows_saved, failed_symbols). Missing fields stay NaN."""
    import yfinance as yf

    day = day or date.today()
    fund_dir = Path(fund_dir)
    fund_dir.mkdir(parents=True, exist_ok=True)
    rows, failed = {}, []
    for sym in symbols:
        info = None
        for attempt in range(retries + 1):
            try:
                info = yf.Ticker(f"{sym}.NS").info
                break
            except Exception:  # network / rate limit: back off and retry
                time.sleep(1.5 * (attempt + 1))
        if not info or not any(info.get(v) is not None for v in FIELDS.values()):
            failed.append(sym)
            continue
        rows[sym] = {k: _num(info.get(v)) for k, v in FIELDS.items()}
        time.sleep(pause)
    df = pd.DataFrame.from_dict(rows, orient="index", columns=list(FIELDS))
    df.index.name = "symbol"
    path = fund_dir / f"{day}.parquet"
    if len(df):
        df.to_parquet(path)
    return path, len(df), failed


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")
