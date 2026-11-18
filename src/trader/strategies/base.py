from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import indicators as ind


def features(df: pd.DataFrame, min_price: float = 50, min_value_cr: float = 10) -> pd.DataFrame:
    """Per-symbol indicator frame. Every column at row t uses only bars <= t."""
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
