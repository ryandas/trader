from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as ind

BEAR, NEUTRAL, BULL = 0, 1, 2
NAMES = {BEAR: "bear", NEUTRAL: "neutral", BULL: "bull"}


def market_regime(close: pd.Series) -> pd.Series:
    """Per-day regime of the benchmark index from data up to that day's close.

    bull: close > 200 SMA and the 50 SMA is rising; bear: close < 200 SMA; else neutral.
    """
    s200, s50 = ind.sma(close, 200), ind.sma(close, 50)
    bull = (close > s200) & (s50 > s50.shift(10))
    bear = close < s200
    code = np.where(bull, BULL, np.where(bear, BEAR, NEUTRAL))
    return pd.Series(code, index=close.index).where(s200.notna(), NEUTRAL).astype(int)


def stock_trending(f: pd.DataFrame, adx_min: float = 25) -> pd.Series:
    return ((f["adx"] > adx_min) & (f["ema50"] > f["ema200"])).fillna(False)
