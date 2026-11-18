"""Dated fundamentals snapshots (point-in-time by construction).

yfinance only serves TODAY's figures, with later revisions folded in and no publication dates, so
backtesting on them would leak the future. Instead we save a copy per run, named by the day it was
taken (rows of the `fundamentals` table keyed by `snap_date`). A strategy may only read the newest snapshot dated
on or before the day it is deciding (`asof` / `panel`). Until several years of snapshots exist there
is no fair backtest history, so fundamentals-based candidates are forward-paper-only.
"""
from __future__ import annotations

import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy import text

from .. import db

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


def snapshot_dates() -> list[pd.Timestamp]:
    df = db.qdf("SELECT DISTINCT snap_date FROM fundamentals ORDER BY snap_date")
    return [pd.Timestamp(d) for d in df["snap_date"]]


def latest_snapshot_date() -> pd.Timestamp | None:
    d = snapshot_dates()
    return d[-1] if d else None


def asof(day) -> pd.DataFrame:
    """Snapshot (index = symbol) of the newest copy dated on or before `day`; empty if none exists."""
    day = pd.Timestamp(day)
    ok = [d for d in snapshot_dates() if d <= day]
    if not ok:
        return pd.DataFrame(columns=list(FIELDS))
    df = db.qdf(f"SELECT symbol, {', '.join(FIELDS)} FROM fundamentals WHERE snap_date = :d ORDER BY symbol", d=ok[-1].date())
    return df.set_index("symbol")


def panel(dates: pd.DatetimeIndex, syms: list[str], field: str) -> np.ndarray:
    """(len(dates) x len(syms)) values of `field` as known on each date (NaN before the first snapshot)."""
    if field not in FIELDS:
        raise KeyError(field)
    out = np.full((len(dates), len(syms)), np.nan)
    allrows = db.qdf(f"SELECT snap_date, symbol, {field} FROM fundamentals ORDER BY snap_date")
    if allrows.empty:
        return out
    allrows["snap_date"] = pd.to_datetime(allrows["snap_date"])
    snaps = sorted(allrows["snap_date"].unique())
    pos = {s: i for i, s in enumerate(syms)}
    # snapshot k covers dates in [snaps[k], snaps[k+1]); a date before snaps[0] stays NaN
    bounds = [int(dates.searchsorted(d, side="left")) for d in snaps] + [len(dates)]
    by_day = {d: g for d, g in allrows.groupby("snap_date")}
    for k, d in enumerate(snaps):
        lo, hi = bounds[k], bounds[k + 1]
        if lo >= hi:
            continue
        row = np.full(len(syms), np.nan)
        for sym, v in zip(by_day[d]["symbol"], by_day[d][field]):
            if sym in pos and v is not None:
                row[pos[sym]] = v
        out[lo:hi] = row
    return out


def ist_today() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def snapshot(symbols: list[str], day: date | None = None, pause: float = 0.3, retries: int = 2):
    """Fetch today's fundamentals for `symbols` and save them under `snap_date = day`.
    Returns (day, rows_saved, failed_symbols). Missing fields stay NaN (NULL)."""
    import yfinance as yf

    day = day or ist_today()
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
    if len(df):
        save_snapshot(day, df)
    return day, len(df), failed


def save_snapshot(day, df: pd.DataFrame) -> None:
    """Store one dated snapshot (index = symbol, FIELDS columns), replacing any earlier copy of the same day."""
    recs = [{"d": pd.Timestamp(day).date(), "s": sym, **{k: (None if k not in df.columns or pd.isna(r[k]) else float(r[k])) for k in FIELDS}}
            for sym, r in df.iterrows()]
    cols = ", ".join(FIELDS)
    with db.engine().begin() as c:
        c.execute(text("DELETE FROM fundamentals WHERE snap_date = :d"), {"d": pd.Timestamp(day).date()})
        c.execute(text(f"INSERT INTO fundamentals (snap_date, symbol, {cols}) VALUES (:d, :s, "
                       + ", ".join(f":{k}" for k in FIELDS) + ")"), recs)


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")
