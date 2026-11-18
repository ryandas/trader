from __future__ import annotations

import pandas as pd

from .base import SignalSet, Strategy


class MeanReversion(Strategy):
    """Buy a short-term oversold dip (RSI2) above the 200 SMA; exit on a close above the 5 SMA."""

    name = "mean_reversion"
    entry_type = "open"
    max_hold = 7
    loose_universe = True  # not limited to the top relative-strength names

    def __init__(self, rsi2_max=10, atr_stop=2.5):
        self.rsi2_max, self.atr_stop = rsi2_max, atr_stop

    def signals(self, f: pd.DataFrame) -> SignalSet:
        sig = ((f["close"] > f["sma200"]) & (f["rsi2"] < self.rsi2_max)).fillna(False)
        return SignalSet(
            signal=sig,
            trigger=self._nan(f),
            max_entry=self._nan(f),
            stop=f["close"] - self.atr_stop * f["atr"],
            target=self._nan(f),
            score=-f["rsi2"],  # most oversold first
            trail=self._nan(f),
            exit_now=(f["close"] > f["sma5"]).fillna(False),
        )
