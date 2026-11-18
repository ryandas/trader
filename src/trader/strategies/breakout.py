from __future__ import annotations

import pandas as pd

from .base import SignalSet, Strategy


class Breakout(Strategy):
    """Close above the prior 55-day high on heavy volume; buy next open (capped)."""

    name = "breakout"
    entry_type = "open"
    max_hold = None

    def __init__(self, vol_mult=1.5, atr_stop=2.0, cap_atr=1.0):
        self.vol_mult, self.atr_stop, self.cap_atr = vol_mult, atr_stop, cap_atr

    def signals(self, f: pd.DataFrame) -> SignalSet:
        sig = ((f["close"] > f["dh55"]) & (f["vol_ratio"] >= self.vol_mult)).fillna(False)
        return SignalSet(
            signal=sig,
            trigger=self._nan(f),
            max_entry=f["dh55"] + self.cap_atr * f["atr"],
            stop=f["close"] - self.atr_stop * f["atr"],
            target=self._nan(f),
            score=f["rs"],
            trail=f["dl20_incl"],
            exit_now=pd.Series(False, index=f.index),
        )
