from __future__ import annotations

import math

from .config import RiskCfg


def position_size(
    equity: float,
    risk_pct: float,
    entry: float,
    stop: float,
    max_position_pct: float,
    cash: float,
) -> int:
    """Shares such that a stop-out loses ~risk_pct of equity, capped by position size and cash."""
    rps = entry - stop
    if rps <= 0 or entry <= 0:
        return 0
    qty = math.floor(equity * risk_pct / rps)
    qty = min(qty, math.floor(equity * max_position_pct / entry))
    if math.isfinite(cash):
        qty = min(qty, math.floor(cash / entry))
    return max(qty, 0)


def can_open(
    n_positions: int,
    n_in_sector: int,
    open_heat: float,
    new_risk: float,
    equity: float,
    r: RiskCfg,
) -> bool:
    """Portfolio constraints. `n_positions` counts open positions plus pending orders."""
    return (
        n_positions < r.max_positions
        and n_in_sector < r.max_per_sector
        and (open_heat + new_risk) <= r.max_heat * equity
    )
