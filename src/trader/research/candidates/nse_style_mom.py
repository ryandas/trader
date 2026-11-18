"""NSE-style momentum: volatility-adjusted 6- and 12-month returns, rebalanced slowly."""
import numpy as np
import pandas as pd

META = {
    "slug": "nse_style_mom",
    "kind": "rotation",
    "hypothesis": "Volatility-adjusted momentum (return per unit of risk over 6 and 12 months), held for months rather than "
                  "weeks, keeps the momentum edge while a slow cadence cuts the flat per-sale charge that hurts a small account.",
    "source": "Modelled on NSE's Nifty200 Momentum 30 index (6- and 12-month volatility-adjusted score, semi-annual rebalance; "
              "see research/india_evidence.md; details from secondary sources are unconfirmed) with Barroso & Santa-Clara (2015) "
              "and Jegadeesh & Titman (1993) as the general references.",
    "grid": [  # fixed before any result: the only difference is how often the book is rebalanced
        {"top_n": 10, "buffer": 10, "rebalance": "S"},
        {"top_n": 10, "buffer": 10, "rebalance": "Q"},
    ],
}


def _z(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional z-score on each date (uses only that date's values)."""
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1).replace(0, np.nan), axis=0)


def score(prep):
    """Mean of the z-scored (return / annualised volatility) over 126 and 252 sessions. No skip of recent days (as NSE describes)."""
    c = prep.close_df
    ret = c.pct_change()
    parts = []
    for n in (126, 252):
        r_n = c / c.shift(n) - 1
        vol_n = ret.rolling(n, min_periods=n).std() * np.sqrt(252)
        parts.append(_z(r_n / vol_n.replace(0, np.nan)))
    return ((parts[0] + parts[1]) / 2).to_numpy()
