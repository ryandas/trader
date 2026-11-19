"""Equal-weight long-only winners: 12-1 month momentum, 20-30 names, monthly (Raju and Teli, SSRN 4000418)."""
META = {
    "slug": "ew_winners_top20",
    "kind": "rotation",
    "hypothesis": "Equal-weighted, monthly-rebalanced long-only winner portfolios of 20+ names avoid the large-cap tilt of "
                  "cap weighting and keep factor alpha after costs in the Indian top-200 universe.",
    "source": "Raju and Teli, 'Long Factors, not Short Change: Long Only Factor Portfolios in India', SSRN 4000418 "
              "(Jan 2022; abstract and intro opened 2026-11-19); Plyakha et al. 2014 (seen cited). Working paper, "
              "practitioner-authored; full text not read.",
    # fixed before any result: 12-1 score, monthly, buffer 10; 20 or 30 names. At INR 5,000 a 20-name book is
    # ~INR 250 per name, so the flat INR 15.34 DP charge per sale (~6%) is expected to hurt: a cost effect is plausible.
    "grid": [
        {"lookback": 252, "skip": 21, "top_n": 20, "buffer": 10, "rebalance": "M"},
        {"lookback": 252, "skip": 21, "top_n": 30, "buffer": 10, "rebalance": "M"},
    ],
}


def score(prep, lookback: int = 252, skip: int = 21):
    """Trailing (skip, lookback) return, higher = buy. Uses bars <= t only."""
    c = prep.close_df
    return (c.shift(skip) / c.shift(lookback) - 1).to_numpy()
