"""52-week-high proximity: hold the stocks trading closest to their own trailing high."""
META = {
    "slug": "high_52w",
    "kind": "rotation",
    "hypothesis": "Stocks priced near their 52-week high keep outperforming: investors anchor on the high and under-react to "
                  "good news, so nearness to the high predicts returns better than past return itself.",
    "source": "George & Hwang (2004), 'The 52-Week High and Momentum Investing', Journal of Finance 59(5), 2145-2176 "
              "(citation checked by search 2026-11-18).",
    "grid": [{"window": 252}, {"window": 126}],  # fixed before any result: the paper's 12 months, and a 6-month variant
}


def score(prep, window: int = 252):
    """close / highest close of the last `window` sessions (1.0 = at the high). Uses bars <= each row only."""
    high = prep.close_df.rolling(window, min_periods=window).max()
    return (prep.close_df / high).to_numpy()
