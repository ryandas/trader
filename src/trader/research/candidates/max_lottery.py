"""MAX / lottery avoidance: hold stocks whose largest recent daily returns are smallest."""
import numpy as np

META = {
    "slug": "max_lottery",
    "kind": "rotation",
    "hypothesis": "Investors overpay for lottery-like stocks (those with extreme recent daily gains), so stocks with the lowest "
                  "recent maximum daily returns earn higher subsequent returns than high-MAX stocks.",
    "source": "Bali, Cakici & Whitelaw (2011), 'Maxing out: Stocks as lotteries and the cross-section of expected returns', "
              "Journal of Financial Economics 99(2), 427-446 (NBER w14804; seen via search 2026-11-18, abstract only). "
              "India evidence indirect and mixed.",
    # fixed before any result: mean of the 5 largest daily returns over 1-month and 3-month windows, monthly cadence
    "grid": [
        {"window": 21, "k": 5, "top_n": 10, "buffer": 5, "rebalance": "M"},
        {"window": 63, "k": 5, "top_n": 10, "buffer": 5, "rebalance": "M"},
    ],
}


def score(prep, window: int = 21, k: int = 5):
    """-(mean of the k largest daily returns in the last `window` sessions); needs a full window. Bars <= t only."""
    r = prep.close_df.pct_change().to_numpy()
    out = np.full(r.shape, np.nan)
    for t in range(window, r.shape[0]):  # r[0] is NaN, so the first full window ends at row `window`
        w = r[t - window + 1: t + 1]
        full = ~np.isnan(w).any(axis=0)
        if not full.any():
            continue
        top = np.partition(w[:, full], window - k, axis=0)[window - k:]
        out[t, full] = -top.mean(axis=0)
    return out
