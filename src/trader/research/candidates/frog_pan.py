"""Frog in the pan: momentum that arrived through many small moves ranks above momentum that arrived in a few jumps."""
import numpy as np

META = {
    "slug": "frog_pan",
    "kind": "rotation",
    "hypothesis": "Investors under-react to information that arrives continuously in small pieces, so winners whose past return "
                  "came from many small up-days (low information discreteness) keep drifting longer than winners whose return "
                  "came from a few jumps.",
    "source": "Da, Gurun & Warachka (2014), 'Frog in the Pan: Continuous Information and Momentum', Review of Financial Studies "
              "27(7), 2171-2218 (citation confirmed by search 2026-11-18; abstract read, full text not).",
    # fixed before any result: 12-1 month formation, monthly vs quarterly cadence (quarterly to cut INR 15.34 sell charges)
    "grid": [
        {"lookback": 252, "skip": 21, "top_n": 10, "buffer": 5, "rebalance": "M"},
        {"lookback": 252, "skip": 21, "top_n": 10, "buffer": 5, "rebalance": "Q"},
    ],
}


def score(prep, lookback: int = 252, skip: int = 21):
    """0.5*pct-rank(PRET) + 0.5*pct-rank(-ID), PRET = close[t-skip]/close[t-lookback]-1,
    ID = sign(PRET) * (share of negative days - share of positive days) over the same window. Bars <= t only."""
    close = prep.close_df
    n = lookback - skip
    ret = close.pct_change()
    ok = ret.notna().astype(float)
    pos = ((ret > 0).astype(float) * ok).rolling(n, min_periods=n).sum().shift(skip)
    neg = ((ret < 0).astype(float) * ok).rolling(n, min_periods=n).sum().shift(skip)
    cnt = ok.rolling(n, min_periods=n).sum().shift(skip)
    pret = close.shift(skip) / close.shift(lookback) - 1
    idisc = np.sign(pret) * (neg - pos) / cnt
    r1 = pret.rank(axis=1, pct=True)
    r2 = (-idisc).rank(axis=1, pct=True)
    return (0.5 * r1 + 0.5 * r2).to_numpy()
