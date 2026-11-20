from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import indicators as ind


def features(df: pd.DataFrame, min_price: float = 50, min_value_cr: float = 10,
             shares_outstanding: float | pd.Series | None = None) -> pd.DataFrame:
    """Per-symbol indicator frame. Every column at row t uses only bars <= t.

    Liquidity columns: `amihud_20` (20-bar mean of |return| / (volume x close); zero-volume bars are skipped as NaN),
    `vol_trend_20` (volume / 20-bar mean volume, today's bar included) and `turnover_20` (20-bar mean of volume / shares).
    Shares are not stored in the database, so `turnover_20` is NaN unless the caller passes `shares_outstanding`
    (a scalar, or a series indexed like `df` that is itself known as of each bar)."""
    f = df[["open", "high", "low", "close", "volume"]].copy()
    c = f["close"]
    f["sma5"] = ind.sma(c, 5)
    f["sma200"] = ind.sma(c, 200)
    f["ema20"], f["ema50"], f["ema200"] = ind.ema(c, 20), ind.ema(c, 50), ind.ema(c, 200)
    f["rsi14"], f["rsi2"] = ind.rsi(c, 14), ind.rsi(c, 2)
    f["atr"] = ind.atr(f, 14)
    f["adx"] = ind.adx(f, 14)
    f["dh55"] = ind.donchian_high(f, 55)
    f["dl20_incl"] = f["low"].rolling(20, min_periods=20).min()  # known at today's close
    f["swing_low10"] = f["low"].rolling(10, min_periods=10).min()
    f["vol_ratio"] = ind.volume_ratio(f, 20)
    # Cross-sectionally comparable strength score (ranking is identical vs. any common benchmark)
    f["rs"] = 0.5 * ind.roc(c, 63) + 0.5 * ind.roc(c, 126)
    value_cr = (c * f["volume"]).rolling(20, min_periods=20).median() / 1e7
    traded = (c * f["volume"]).where(f["volume"] > 0)
    f["amihud_20"] = (c.pct_change(fill_method=None).abs() / traded).rolling(20, min_periods=20).mean()
    f["vol_trend_20"] = f["volume"] / f["volume"].rolling(20, min_periods=20).mean()
    shares = np.nan if shares_outstanding is None else shares_outstanding
    f["turnover_20"] = (f["volume"] / shares).rolling(20, min_periods=20).mean()
    f["liquid"] = (value_cr >= min_value_cr) & (c >= min_price)
    return f


@dataclass(frozen=True)
class SignalSet:
    """Vectorised output of a strategy for one symbol (indexed like the feature frame).

    A row with `signal` True is evaluated at that day's CLOSE; the order works the next session.
    `trail` is a stop level known at each day's close (NaN = no trailing stop) and
    `exit_now` a discretionary exit condition at the close (filled at the next open).
    """

    signal: pd.Series
    trigger: pd.Series  # buy-stop price for entry_type 'stop', else NaN
    max_entry: pd.Series  # reject fills above this (NaN = no cap)
    stop: pd.Series
    target: pd.Series  # NaN = no target
    score: pd.Series
    trail: pd.Series
    exit_now: pd.Series


class Strategy:
    name: str = ""
    entry_type: str = "open"  # 'open' or 'stop'
    max_hold: int | None = None
    loose_universe: bool = False
    params: dict = {}

    def signals(self, f: pd.DataFrame) -> SignalSet:
        raise NotImplementedError

    @staticmethod
    def _nan(f: pd.DataFrame) -> pd.Series:
        return pd.Series(np.nan, index=f.index)
