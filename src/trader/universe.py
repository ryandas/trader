"""Step 1: which symbols are tradable on a given day."""
from __future__ import annotations

import numpy as np
import pandas as pd


def rank_matrix(rs: np.ndarray, liquid: np.ndarray) -> np.ndarray:
    """Per-day relative-strength rank (1 = strongest) among liquid symbols; NaN if illiquid.

    Inputs are (days x symbols). Hard liquidity/price/history filters are in `liquid`
    (see strategies.base.features); ranking only ever uses information up to each day.
    """
    return (
        pd.DataFrame(np.where(liquid, rs, np.nan))
        .rank(axis=1, ascending=False, method="first")
        .to_numpy()
    )


def membership(rank: np.ndarray, top_n: int) -> np.ndarray:
    return rank <= top_n  # NaN compares False
