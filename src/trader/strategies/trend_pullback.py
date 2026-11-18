from __future__ import annotations

import numpy as np
import pandas as pd

from .base import SignalSet, Strategy


class TrendPullback(Strategy):
    """Buy a dip in an established uptrend with a buy-stop above the signal bar's high."""

    name = "trend_pullback"
    entry_type = "stop"
    max_hold = 40

    def __init__(self, rsi_lo=40, rsi_hi=50, atr_stop=2.0, rr=2.0, trail_atr=3.0):
        self.rsi_lo, self.rsi_hi = rsi_lo, rsi_hi
        self.atr_stop, self.rr, self.trail_atr = atr_stop, rr, trail_atr

    def signals(self, f: pd.DataFrame) -> SignalSet:
        trend = (f["ema20"] > f["ema50"]) & (f["ema50"] > f["ema200"])
        dip = f["rsi14"].between(self.rsi_lo, self.rsi_hi)
        trigger = f["high"]
        # tighter of swing low / ATR stop, but never closer than 0.75 ATR
        stop = np.minimum(
            np.maximum(f["swing_low10"], trigger - self.atr_stop * f["atr"]),
            trigger - 0.75 * f["atr"],
        )
        sig = (trend & dip & stop.notna() & (stop < trigger)).fillna(False)
        return SignalSet(
            signal=sig,
            trigger=trigger,
            max_entry=self._nan(f),
            stop=stop,
            target=trigger + self.rr * (trigger - stop),
            score=f["rs"],
            trail=f["close"] - self.trail_atr * f["atr"],
            exit_now=pd.Series(False, index=f.index),
        )
