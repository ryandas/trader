"""NSE-style normalized momentum: mean cross-sectional z-score of vol-adjusted 6-1 and 12-1 month returns."""
META = {
    "slug": "nse_norm_mom",
    "kind": "rotation",
    "hypothesis": "Volatility-adjusted momentum over two horizons ranks smooth winners above jumpy ones, which should "
                  "lower momentum-crash risk versus raw 6-1 return ranking.",
    "source": "NSE Indices Nifty500 Momentum 50 methodology (normalized momentum score from 6- and 12-month "
              "volatility-adjusted returns, semi-annual rebalance; snippets seen 2026-11-19, not opened in full). "
              "Index provider document, not a performance claim.",
    # fixed before any result: windows 126 and 252, skip 21; top 10, buffer 5; semi-annual vs quarterly cadence
    # (INR 15.34 flat DP charge per sale; ~INR 500 per name at INR 5,000).
    "grid": [
        {"w1": 126, "w2": 252, "skip": 21, "top_n": 10, "buffer": 5, "rebalance": "S"},
        {"w1": 126, "w2": 252, "skip": 21, "top_n": 10, "buffer": 5, "rebalance": "Q"},
    ],
}


def _z(a):
    """Row-wise cross-sectional z-score (NaN-aware)."""
    import numpy as np
    m = np.nanmean(a, axis=1, keepdims=True)
    s = np.nanstd(a, axis=1, keepdims=True)
    s = np.where(s == 0, np.nan, s)
    return (a - m) / s


def score(prep, w1: int = 126, w2: int = 252, skip: int = 21):
    """mean of z(ret/vol) over windows w1 and w2, each ending `skip` bars ago. Uses bars <= t only."""
    import numpy as np
    c = prep.close_df
    r = c.pct_change(fill_method=None)
    parts = []
    for w in (w1, w2):
        ret = c.shift(skip) / c.shift(w) - 1
        vol = r.shift(skip).rolling(w - skip, min_periods=w - skip).std()
        vol = vol.where(vol > 0)
        parts.append(_z((ret / vol).to_numpy(dtype=float)))
    with np.errstate(all="ignore"):
        return np.where(np.isnan(parts[0]) | np.isnan(parts[1]), np.nan, (parts[0] + parts[1]) / 2)
