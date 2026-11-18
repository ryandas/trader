"""Market-context snapshot for research journals. INFORMATIONAL ONLY: it never feeds the gates, the choice of
parameters, or which idea is tested; it just records the conditions under which an idea was looked at."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .. import indicators as ind
from ..regime import NAMES, market_regime


def market_context(bench: pd.Series, prep=None) -> dict:
    """Facts about the benchmark (and, if a MomPrep is given, breadth among liquid stocks) as of the last bar."""
    c = bench.dropna()
    last = c.iloc[-1]
    s200, s50 = ind.sma(c, 200), ind.sma(c, 50)
    ret = lambda n: round(float(100 * (last / c.iloc[-1 - n] - 1)), 2) if len(c) > n else None  # noqa: E731
    daily = c.pct_change()
    out = {
        "as_of": str(c.index[-1].date()),
        "regime": NAMES[int(market_regime(c).iloc[-1])],
        "close": round(float(last), 1),
        "vs_200sma_pct": round(float(100 * (last / s200.iloc[-1] - 1)), 2) if np.isfinite(s200.iloc[-1]) else None,
        "sma50_rising_10d": bool(s50.iloc[-1] > s50.iloc[-11]) if len(s50.dropna()) > 11 else None,
        "return_1m_pct": ret(21), "return_3m_pct": ret(63), "return_6m_pct": ret(126), "return_12m_pct": ret(252),
        "drawdown_from_52w_high_pct": round(float(100 * (last / c.iloc[-252:].max() - 1)), 2),
        "volatility_20d_ann_pct": round(float(100 * daily.iloc[-20:].std() * np.sqrt(252)), 1),
        "volatility_1y_ann_pct": round(float(100 * daily.iloc[-252:].std() * np.sqrt(252)), 1),
    }
    if prep is not None:
        li = len(prep.dates) - 1
        liq = prep.liquid[li]
        n = int(liq.sum())
        if n:
            high = prep.close_df.rolling(252, min_periods=200).max().to_numpy()[li]
            near = (prep.c[li] >= 0.95 * high) & liq
            out |= {
                "liquid_stocks": n,
                "pct_above_200sma": round(float(100 * (prep.above200[li] & liq).sum() / n), 1),
                "pct_within_5pct_of_52w_high": round(float(100 * near.sum() / n), 1),
            }
    return out


def render(ctx: dict) -> str:
    return "\n".join(f"- {k}: {v}" for k, v in ctx.items())
