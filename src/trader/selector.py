"""Step 2: which strategy may trade a symbol, and which gets priority."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .regime import BEAR, NAMES

PRIORITY = ["breakout", "trend_pullback", "mean_reversion"]  # tie-break when no stats exist


def eligible(
    name: str, mkt: np.ndarray, trending: np.ndarray, above200: np.ndarray, bear_policy: str
) -> np.ndarray:
    """Rule-based eligibility from market regime and the stock's own regime (arrays over days)."""
    not_bear = mkt != BEAR
    if name in ("breakout", "trend_pullback"):
        return trending & not_bear
    if name == "mean_reversion":
        ok = ~trending & above200
        return ok if bear_policy == "mean_reversion_only" else ok & not_bear
    return np.ones_like(trending, dtype=bool)


class Selector:
    """Ranks and gates strategies using in-sample expectancy per (strategy, market regime)."""

    def __init__(self, stats: dict[tuple[str, int], float] | None = None):
        self.stats = stats or {}

    @classmethod
    def from_trades(cls, trades: pd.DataFrame, min_trades: int = 20) -> "Selector":
        stats: dict[tuple[str, int], float] = {}
        if len(trades):
            for (name, reg), g in trades.groupby(["strategy", "mkt"]):
                if len(g) >= min_trades and g["risk"].sum() > 0:
                    stats[(name, int(reg))] = float(g["net_pnl"].sum() / g["risk"].sum())
        return cls(stats)

    def allowed(self, name: str, regime: int) -> bool:
        """A strategy that lost money in a regime in-sample is switched off there."""
        v = self.stats.get((name, regime))
        return v is None or v > 0

    def weight(self, name: str, regime: int) -> float:
        v = self.stats.get((name, regime))
        if v is not None:
            return v
        return -1e-3 * (PRIORITY.index(name) if name in PRIORITY else 99)

    def to_dict(self) -> dict[str, float]:
        return {f"{n}|{NAMES[r]}": round(v, 4) for (n, r), v in sorted(self.stats.items())}

    @classmethod
    def from_dict(cls, raw: dict[str, float]) -> "Selector":
        inv = {v: k for k, v in NAMES.items()}
        return cls({(k.split("|")[0], inv[k.split("|")[1]]): v for k, v in raw.items()})

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: Path) -> "Selector":
        return cls.from_dict(json.loads(path.read_text()) if path.exists() else {})
