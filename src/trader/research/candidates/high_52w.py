"""52-week-high nearness: rank by close / trailing 252-bar maximum close (George and Hwang 2004)."""
META = {
    "slug": "high_52w",
    "kind": "rotation",
    "hypothesis": "Anchoring: investors under-react to good news when a stock is near its 52-week high, so stocks "
                  "closest to their high keep outperforming.",
    "source": "George and Hwang (2004), Journal of Finance 59(4) (US; abstract seen via search 2026-11-19); "
              "Gupta, Locke, Scrimgeour (2010) 51-country test seen cited. Journal articles; effect may have weakened.",
    # fixed before any result: ~10 names, buffer 5; monthly or quarterly cadence (INR 15.34 per sale)
    "grid": [
        {"window": 252, "top_n": 10, "buffer": 5, "rebalance": "M"},
        {"window": 252, "top_n": 10, "buffer": 5, "rebalance": "Q"},
    ],
}


def score(prep, window: int = 252):
    """close / rolling max of closes over `window` bars (<= 1; higher = nearer the high = buy). Uses bars <= t only."""
    c = prep.close_df
    return (c / c.rolling(window, min_periods=window).max()).to_numpy()
