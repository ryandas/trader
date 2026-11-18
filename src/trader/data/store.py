from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import text

from .. import db
from .dhan import IST
from .sources import CandleSource

MARKET_CLOSE_HOUR = 16  # IST; before this, today's bar may be partial


COLS = ["open", "high", "low", "close", "volume"]


def _frame(df: pd.DataFrame) -> pd.DataFrame:
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")  # same resolution the parquet store had
    df = df.set_index("date")[COLS]
    return df.astype({"open": "float64", "high": "float64", "low": "float64", "close": "float64", "volume": "int64"})


def load(symbol: str) -> pd.DataFrame | None:
    """Daily candles of one symbol (DatetimeIndex 'date'; open/high/low/close/volume), or None."""
    df = db.qdf("SELECT date, open, high, low, close, volume FROM candles WHERE symbol = :s ORDER BY date", s=symbol)
    return _frame(df) if len(df) else None


def load_many(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Candles for many symbols in one round trip (COPY). Keeps the order of `symbols`; absent ones are left out."""
    if not symbols:
        return {}
    lit = ",".join("'" + s.replace("'", "''") + "'" for s in symbols)
    df = db.copy_df(f"SELECT symbol, date, open, high, low, close, volume FROM candles "
                    f"WHERE symbol = ANY(ARRAY[{lit}]) ORDER BY symbol, date")
    groups = {s: g.drop(columns="symbol") for s, g in df.groupby("symbol", sort=False)}
    return {s: _frame(groups[s].copy()) for s in symbols if s in groups}


def _write(symbol: str, df: pd.DataFrame, replace: bool) -> None:
    """Upsert candle rows (or, with replace, delete the symbol's history first) in one transaction."""
    rows = [{"s": symbol, "d": d.date(), "o": float(r.open), "h": float(r.high), "l": float(r.low),
             "c": float(r.close), "v": int(r.volume)} for d, r in df.iterrows()]
    with db.engine().begin() as c:
        if replace:
            c.execute(text("DELETE FROM candles WHERE symbol = :s"), {"s": symbol})
        if rows:
            c.execute(text(
                "INSERT INTO candles (symbol, date, open, high, low, close, volume) VALUES (:s, :d, :o, :h, :l, :c, :v) "
                "ON CONFLICT (symbol, date) DO UPDATE SET open = EXCLUDED.open, high = EXCLUDED.high, "
                "low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume"), rows)


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
    symbol: str,
    security_id: str | int,
    years: int = 5,
    now: datetime | None = None,
) -> int:
    """Backfill, extend or incrementally update one symbol. Returns net rows added."""
    end = last_complete_day(now)
    want_start = end - timedelta(days=int(365.25 * years))
    old = load(symbol)
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
    if old is None:
        _write(symbol, merged, replace=True)  # first load, or a split/bonus re-adjustment discarded the history
    elif len(merged) != before or _differs(merged, old):
        common = merged.index.intersection(old.index)
        diff = merged.loc[common].astype("float64").ne(old.loc[common].astype("float64")).any(axis=1)
        changed = pd.concat([merged[~merged.index.isin(old.index)], merged.loc[common][diff]])
        _write(symbol, changed, replace=False)
    return len(merged) - before
