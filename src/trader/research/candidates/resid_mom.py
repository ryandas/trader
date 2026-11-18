"""Residual momentum: rank by the market-neutral part of past returns, scaled by its volatility."""
import numpy as np
import pandas as pd

META = {
    "slug": "resid_mom",
    "kind": "rotation",
    "hypothesis": "Momentum measured on returns left after removing each stock's market (NIFTY 500) exposure is steadier and "
                  "less hostage to market swings than total-return momentum, so ranking on it should hold up better.",
    "source": "Blitz, Huij & Martens (2011), 'Residual Momentum', Journal of Empirical Finance 18(3), 506-521 "
              "(citation checked by search 2026-11-18). Simplified here to a one-factor (market) residual.",
    "grid": [{"lookback": 252, "skip": 21}, {"lookback": 126, "skip": 21}],  # fixed before any result
}
BETA_WINDOW = 252


def score(prep, lookback: int = 252, skip: int = 21):
    """Sum of daily residual returns over `lookback` sessions ending `skip` sessions ago, divided by their std.
    Beta is the trailing 252-day regression slope on the index, lagged one day so it only uses bars < the day it is applied."""
    r = prep.close_df.pct_change()
    rm = pd.Series(prep.bench_close, index=prep.close_df.index).pct_change()
    beta = r.rolling(BETA_WINDOW, min_periods=BETA_WINDOW).cov(rm).div(rm.rolling(BETA_WINDOW, min_periods=BETA_WINDOW).var(), axis=0)
    resid = r.sub(beta.shift(1).mul(rm, axis=0))
    past = resid.shift(skip)
    num = past.rolling(lookback, min_periods=lookback).sum()
    den = past.rolling(lookback, min_periods=lookback).std()
    return (num / den.replace(0, np.nan)).to_numpy()
