from __future__ import annotations

from .config import CostCfg


def apply_slippage(price: float, side: str, bps: float) -> float:
    """Adverse slippage: buys fill higher, sells lower."""
    k = bps / 10_000
    return price * (1 + k) if side == "buy" else price * (1 - k)


def trade_costs(side: str, value: float, c: CostCfg) -> float:
    """Total INR charges for one delivery-equity order of the given traded value."""
    exch = value * c.exch_pct
    sebi = value * c.sebi_pct
    gst = c.gst * (c.brokerage_per_order + exch + sebi)
    total = c.brokerage_per_order + exch + sebi + gst + value * c.stt_pct
    if side == "buy":
        total += value * c.stamp_pct
    else:
        total += c.dp_charge
    return total
