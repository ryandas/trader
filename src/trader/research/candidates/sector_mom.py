"""Sector momentum: hold stocks from the sectors that have been rising the most."""
import pandas as pd

META = {
    "slug": "sector_mom",
    "kind": "rotation",
    "hypothesis": "Industry momentum drives much of stock momentum: stocks in sectors that have recently outperformed keep "
                  "outperforming, because information diffuses slowly across an industry.",
    "source": "Moskowitz & Grinblatt (1999), 'Do Industries Explain Momentum?', Journal of Finance 54(4), 1249-1290 "
              "(citation checked by search 2026-11-18). Later work (Grundy & Martin 2001; Lewellen 2002) disputes how much "
              "industries explain.",
    "grid": [{"lookback": 126, "skip": 21}, {"lookback": 252, "skip": 21}],  # fixed before any result
}
TIE_BREAK = 1e-3  # weight of the stock's own return, only to order stocks inside the same sector


def score(prep, lookback: int = 126, skip: int = 21):
    """Equal-weight mean trailing return of the stock's sector (+ a tiny own-return tie-break). Uses bars <= each row only."""
    own = prep.close_df.shift(skip) / prep.close_df.shift(lookback) - 1
    sec = pd.Series(prep.sectors, index=own.columns)
    sector_ret = own.T.groupby(sec).transform("mean").T  # mean across the sector's stocks that have a value that day
    return (sector_ret + TIE_BREAK * own).to_numpy()
