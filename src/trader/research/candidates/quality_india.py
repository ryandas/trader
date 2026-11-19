"""Quality: high profitability (ROE, operating margin) and low leverage (debt/equity), forward-paper only."""
import numpy as np
import pandas as pd

META = {
    "slug": "quality_india",
    "kind": "rotation",
    "uses_fundamentals": True,
    "hypothesis": "Profitable, low-leverage firms are mispriced relative to their quality; a long-only top-10 quality "
                  "book rebalanced quarterly has low churn. Fundamentals come from dated snapshots (from 2026-11-18), "
                  "so there is no backtest: forward paper only.",
    "source": "SSRN 4284686, quality factor in India (abstract only seen via search 2026-11-19: QMJ four-factor alpha "
              "0.92%/month, long-only 0.69%/month; full text not opened). Working paper; effects often weaken after "
              "publication.",
    # single point (fundamentals candidate): quarterly cadence to limit INR 15.34 per-sale charges, 10 names
    "grid": [{"top_n": 10, "buffer": 5, "rebalance": "Q"}],
}


def _rank(a: np.ndarray) -> np.ndarray:
    """Cross-sectional percentile rank per row (NaN stays NaN)."""
    return pd.DataFrame(a).rank(axis=1, pct=True).to_numpy()


def score(prep):
    """Mean percentile rank of ROE, operating margin and (inverted) debt/equity as known on each date.
    Needs all three fields; otherwise NaN (not eligible). Uses only snapshots dated <= the row's date."""
    roe = prep.fund_panel("roe")
    opm = prep.fund_panel("op_margin")
    de = prep.fund_panel("debt_to_equity")
    ok = ~(np.isnan(roe) | np.isnan(opm) | np.isnan(de))
    s = (_rank(roe) + _rank(opm) + (1 - _rank(de))) / 3.0
    return np.where(ok, s, np.nan)
