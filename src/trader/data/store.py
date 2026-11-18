from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from .dhan import IST
from .sources import CandleSource

MARKET_CLOSE_HOUR = 16  # IST; before this, today's bar may be partial


def _path(candles_dir: Path, symbol: str) -> Path:
    return candles_dir / f"{symbol}.parquet"


def load(candles_dir: Path, symbol: str) -> pd.DataFrame | None:
    p = _path(candles_dir, symbol)
    return pd.read_parquet(p) if p.exists() else None


def last_complete_day(now: datetime | None = None) -> date:
    now = now or datetime.now(IST)
    d = now.date()
    return d if now.hour >= MARKET_CLOSE_HOUR else d - timedelta(days=1)


def _fetch(source: CandleSource, symbol, security_id, start: date, end: date) -> pd.DataFrame:
    """Fetch in chunks of the source's max span (Dhan: 1y per call; Yahoo: unlimited)."""
    span = getattr(source, "max_span_days", 365)
    frames, cur = [], start
    while cur <= end:
        stop = min(cur + timedelta(days=span - 1), end)
        f = source.daily_candles(symbol, security_id, cur, stop)
        if len(f):
            frames.append(f)
        cur = stop + timedelta(days=1)
    return pd.concat(frames) if frames else pd.DataFrame()


def _differs(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    """True if the frames differ in index, columns or values (dtype-insensitive, NaN == NaN)."""
    if not a.index.equals(b.index) or list(a.columns) != list(b.columns):
        return True
    try:
        return not a.astype("float64").equals(b.astype("float64"))
    except (TypeError, ValueError):
        return not a.equals(b)


def update_symbol(
    source: CandleSource,
    candles_dir: Path,
    symbol: str,
    security_id: str | int,
    years: int = 5,
    now: datetime | None = None,
) -> int:
    """Backfill, extend or incrementally update one symbol. Returns net rows added."""
    candles_dir.mkdir(parents=True, exist_ok=True)
    end = last_complete_day(now)
    want_start = end - timedelta(days=int(365.25 * years))
    old = load(candles_dir, symbol)
    old = old if old is not None and len(old) else None
    parts: list[pd.DataFrame] = []

    if old is not None:
        # Re-fetch a short overlap. If it disagrees with stored data (split/bonus
        # adjustment), discard history and backfill from scratch.
        recent = _fetch(source, symbol, security_id, old.index.max().date() - timedelta(days=5), end)
        common = recent.index.intersection(old.index)
        if len(common) and (
            (recent.loc[common, "close"] / old.loc[common, "close"] - 1).abs().max() > 0.01
        ):
            old = None
        else:
            parts.append(recent)
            first = old.index.min().date()
            if first > want_start + timedelta(days=30):  # extend history backwards
                parts.append(_fetch(source, symbol, security_id, want_start, first - timedelta(days=1)))
    if old is None:
        parts = [_fetch(source, symbol, security_id, want_start, end)]

    new = pd.concat([p for p in parts if len(p)]) if any(len(p) for p in parts) else None
    if new is None:
        return 0
    new = new[new.index <= pd.Timestamp(end)]
    merged = new if old is None else pd.concat([old, new])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    before = 0 if old is None else len(old)
    if old is None or len(merged) != before or _differs(merged, old):
        merged.to_parquet(_path(candles_dir, symbol))
    return len(merged) - before
