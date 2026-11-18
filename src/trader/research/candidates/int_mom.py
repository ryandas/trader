"""Intermediate momentum: rank by the return from 12 months ago to 6 months ago, ignoring the most recent 6 months."""
META = {
    "slug": "int_mom",
    "kind": "rotation",
    "hypothesis": "Momentum is driven mainly by performance 7-12 months back; the most recent months add noise (and some "
                  "reversal), so ranking on the intermediate window alone should select more persistent winners.",
    "source": "Novy-Marx (2012), 'Is momentum really momentum?', Journal of Financial Economics 103(3), 429-453 "
              "(citation confirmed by search 2026-11-18; contested by Goyal & Wahal 2015).",
    # fixed before any result: window 12m->6m back; monthly vs quarterly cadence (INR 15.34 per sale)
    "grid": [
        {"far": 252, "near": 126, "top_n": 10, "buffer": 5, "rebalance": "M"},
        {"far": 252, "near": 126, "top_n": 10, "buffer": 5, "rebalance": "Q"},
    ],
}


def score(prep, far: int = 252, near: int = 126):
    """close[t-near] / close[t-far] - 1. Uses bars <= t only."""
    c = prep.close_df
    return (c.shift(near) / c.shift(far) - 1).to_numpy()
