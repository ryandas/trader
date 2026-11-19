"""Regime-switched momentum / reversal: 12-1 momentum when the index is calm, 1-month reversal when index volatility is extreme."""
import numpy as np
import pandas as pd

META = {
    "slug": "regime_switch",
    "kind": "rotation",
    "hypothesis": "Momentum and short-term reversal are regime-dependent complements: momentum's information "
                  "coefficient falls in high-volatility (crash) states while reversal's rises. Rank by 12-1 momentum "
                  "in calm states and by minus the 1-month return in crash states. Proxy for the paper's Hidden "
                  "Markov Model: crash = NIFTY 500 20-day volatility above its trailing 1-year percentile.",
    "source": "Regime-Dependent Price Formation in Indian Equities (SSRN abstract 7044244, posted 2 Jul 2026, working "
              "paper; abstract opened 2026-11-18, full text not read). Deviation: volatility-percentile proxy instead of an HMM.",
    # fixed before any result (backlog row): percentile 0.8 or 0.9; 10 names, buffer 5, monthly (INR 15.34 per sale)
    "grid": [
        {"pct": 0.8, "top_n": 10, "buffer": 5, "rebalance": "M", "bear_exit": True},
        {"pct": 0.9, "top_n": 10, "buffer": 5, "rebalance": "M", "bear_exit": True},
    ],
}


def crash_state(bench: pd.Series, pct: float, vol_window: int = 20, rank_window: int = 252) -> pd.Series:
    """True where the index's 20d volatility exceeds its trailing 1y `pct` quantile. Bars <= t only."""
    vol = bench.pct_change(fill_method=None).rolling(vol_window, min_periods=vol_window).std()
    thr = vol.rolling(rank_window, min_periods=rank_window).quantile(pct)
    return (vol > thr).fillna(False)


def blend(mom12: np.ndarray, rev1: np.ndarray, crash: np.ndarray) -> np.ndarray:
    """Row-wise: reversal score on crash dates, momentum score otherwise."""
    return np.where(np.asarray(crash, dtype=bool)[:, None], rev1, mom12)


def score(prep, pct: float = 0.8, lookback: int = 252, skip: int = 21):
    c = prep.close_df
    mom12 = (c.shift(skip) / c.shift(lookback) - 1).to_numpy()
    rev1 = (-(c / c.shift(skip) - 1)).to_numpy()
    bench = pd.Series(prep.bench_close, index=prep.dates)
    return blend(mom12, rev1, crash_state(bench, pct).to_numpy())
