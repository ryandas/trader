"""Trend factor (price-only): average over several moving-average lengths of close / MA_L - 1."""
import numpy as np

META = {
    "slug": "trend_ma",
    "kind": "rotation",
    "hypothesis": "Information diffuses slowly, so price relative to multi-horizon moving averages predicts returns "
                  "(trend factor, price-only; the original has high turnover, so it is run at quarterly cadence).",
    "source": "Han, Zhou & Zhu (2016), 'A trend factor: Any economic gains from using information over investment "
              "horizons?', Journal of Financial Economics (seen via CXO Advisory).",
    # fixed before any result: quarterly vs monthly cadence (INR 15.34 per sale)
    "grid": [
        {"top_n": 10, "buffer": 5, "rebalance": "Q", "ma_lengths": (20, 50, 100, 200)},
        {"top_n": 10, "buffer": 5, "rebalance": "M", "ma_lengths": (20, 50, 100, 200)},
    ],
}


def score(prep, ma_lengths=(20, 50, 100, 200)):
    """Mean over L of close / rolling_mean(close, L) - 1. Trailing windows only (bars <= t).
    NaN until max(L) bars are available."""
    c = prep.close_df
    lengths = tuple(int(x) for x in ma_lengths)
    ratios = [c / c.rolling(L, min_periods=L).mean() - 1 for L in lengths]
    s = sum(ratios) / len(ratios)
    out = s.to_numpy(dtype=float).copy()
    out[: max(lengths) - 1] = np.nan
    return out
