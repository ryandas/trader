"""Short-term reversal: rank by the trailing return over the last `lookback` sessions, buy the worst performers."""
META = {
    "slug": "str_rev",
    "kind": "rotation",
    "hypothesis": "Short-horizon overreaction: stocks that fell most over the last month tend to bounce over the "
                  "following weeks, so buying the recent losers should beat the index at small size.",
    "source": "Quantpedia, 'Short Term Reversal Effect in Stocks' (page opened 2026-11-18, summary only); "
              "Terblanche (2015), Johannesburg SE large caps (abstract seen). No Indian test found.",
    # fixed before any result: 1-4 positions (INR 5,000 account, >= ~INR 2,500 per position so the INR 15.34 sale
    # charge stays near 0.6%); weekly vs monthly cadence; buffer 1 for top 2, 2 for top 5.
    "grid": [
        {"lookback": 21, "top_n": 2, "buffer": 1, "rebalance": "W", "bear_exit": True},
        {"lookback": 21, "top_n": 2, "buffer": 1, "rebalance": "M", "bear_exit": True},
        {"lookback": 21, "top_n": 5, "buffer": 2, "rebalance": "W", "bear_exit": True},
        {"lookback": 21, "top_n": 5, "buffer": 2, "rebalance": "M", "bear_exit": True},
    ],
}


def score(prep, lookback: int = 21):
    """-(close[t] / close[t - lookback] - 1): higher = bigger recent loser. Uses bars <= t only."""
    c = prep.close_df
    return (-(c / c.shift(lookback) - 1)).to_numpy()
