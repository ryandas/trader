"""Industry momentum: rank stocks by the trailing 6-1 month return of their sector (median of members)."""
import numpy as np
import pandas as pd

META = {
    "slug": "sector_mom",
    "kind": "rotation",
    "hypothesis": "Industry momentum explains much of stock momentum and persists at the 6-12 month horizon, so stocks "
                  "in recently strong sectors keep outperforming; ties inside a sector are broken by own 12-1 return.",
    "source": "Moskowitz and Grinblatt (1999), Journal of Finance 54(4) (US; seen cited, not opened); India: Garg and "
              "Varshney (2015), Global Business Review 16(3) (abstract seen via search). Journal articles; published "
              "effect may have weakened.",
    # fixed before any result: slow cadence (INR 15.34 per sale), 10 names, buffer 5; Q or S rebalance
    "grid": [
        {"top_n": 10, "buffer": 5, "rebalance": "Q"},
        {"top_n": 10, "buffer": 5, "rebalance": "S"},
    ],
}

MIN_MEMBERS = 3  # a sector median needs at least this many stocks with a return on that day


def score(prep, lookback: int = 126, skip: int = 21, own_lookback: int = 252):
    """Sector median of the (skip, lookback) return + 1e-6 * own (skip, own_lookback) return as tie-break.
    Uses bars <= t only. Unknown-sector stocks are NaN (never bought)."""
    if prep.sectors is None:
        raise ValueError("sector_mom needs prep.sectors (instruments.sector)")
    close = prep.close_df
    sec_ret = close.shift(skip) / close.shift(lookback) - 1
    own = (close.shift(skip) / close.shift(own_lookback) - 1).clip(-1, 5)
    labels = pd.Series(prep.sectors, index=close.columns)
    labels = labels.where(~labels.isin(["Unknown", "", None]))
    out = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
    for sec in labels.dropna().unique():
        cols = labels.index[labels == sec]
        block = sec_ret[cols]
        med = block.median(axis=1).where(block.notna().sum(axis=1) >= MIN_MEMBERS)
        out[cols] = np.repeat(med.to_numpy()[:, None], len(cols), axis=1)
    return (out + 1e-6 * own).to_numpy()
