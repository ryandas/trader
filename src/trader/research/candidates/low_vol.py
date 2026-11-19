"""Low volatility: rank by the lowest trailing realised daily volatility."""
META = {
    "slug": "low_vol",
    "kind": "rotation",
    "hypothesis": "Investors overpay for volatile/lottery-like stocks and leverage-constrained investors tilt to high "
                  "beta, so low-risk names earn higher risk-adjusted returns.",
    "source": "NSE low-risk anomaly study Jan 2001-Jun 2016 (abstract seen via search 2026-11-19); Agarwalla et al. "
              "2014 BAB India (seen cited). Journal articles; effect size sample-dependent.",
    # fixed before any result: vol window 126 or 252; quarterly cadence (INR 15.34 per sale), ~10 names
    "grid": [
        {"window": 126, "top_n": 10, "buffer": 5, "rebalance": "Q"},
        {"window": 252, "top_n": 10, "buffer": 5, "rebalance": "Q"},
    ],
}


def score(prep, window: int = 126):
    """Negative rolling std of daily returns (higher = lower vol = buy). Uses bars <= t only."""
    r = prep.close_df.pct_change(fill_method=None)
    return (-r.rolling(window, min_periods=window).std()).to_numpy()
