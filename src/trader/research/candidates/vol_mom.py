"""Volatility-adjusted momentum ranking: 12-1 month return divided by trailing realised daily volatility."""
import numpy as np

META = {
    "slug": "vol_mom",
    "kind": "rotation",
    "hypothesis": "Momentum crashes concentrate in high-volatility names/periods; dividing the 12-1 month return by "
                  "trailing realised volatility should favour smoother winners and cut crash losses while keeping "
                  "most of the average return. (Ranking version: the rotation contract cannot scale exposure.)",
    "source": "Barroso & Santa-Clara (2015), 'Momentum has its moments', Journal of Financial Economics 116(1) "
              "(abstract seen via search 2026-11-18; full text not opened). Their paper scales the momentum portfolio, "
              "not the ranking: this is a deviation.",
    # fixed before any result: backlog grid; monthly rebalance, 5 or 10 names, vol window 63 or 126
    "grid": [
        {"window": 63, "top_n": 5, "buffer": 2, "rebalance": "M"},
        {"window": 126, "top_n": 5, "buffer": 2, "rebalance": "M"},
        {"window": 63, "top_n": 10, "buffer": 5, "rebalance": "M"},
        {"window": 126, "top_n": 10, "buffer": 5, "rebalance": "M"},
    ],
}


def score(prep, window: int = 126, lookback: int = 252, skip: int = 21):
    """(close[t-skip] / close[t-lookback] - 1) / std(daily returns over `window` bars ending at t). Bars <= t only."""
    c = prep.close_df
    mom = c.shift(skip) / c.shift(lookback) - 1
    vol = c.pct_change(fill_method=None).rolling(window, min_periods=window).std()
    vol = vol.where(vol > 0)
    return (mom / vol).replace([np.inf, -np.inf], np.nan).to_numpy()
