from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]


class UniverseCfg(BaseModel):
    min_bars: int = 250
    min_price: float = 50
    min_median_value_cr: float = 10
    top_n: int = 50
    loose_top_n: int = 150  # mean reversion trades a wider set


class RegimeCfg(BaseModel):
    bear_policy: str = "mean_reversion_only"  # or "none": no new entries in a bear market
    bear_size_mult: float = 0.5  # risk-per-trade multiplier while the market is bearish
    min_stat_trades: int = 20  # in-sample trades needed before a strategy/regime stat is trusted


class RiskCfg(BaseModel):
    max_position_pct: float = 0.20
    max_positions: int = 10
    max_per_sector: int = 3
    max_heat: float = 0.06


class CostCfg(BaseModel):
    """Delivery (CNC) equity costs. Verify brokerage against your Dhan plan."""

    brokerage_per_order: float = 0
    slippage_bps: float = 5
    stt_pct: float = 0.001  # both sides
    exch_pct: float = 0.000030699  # NSE transaction charge (Dhan 0.0030699%)
    sebi_pct: float = 0.000001
    stamp_pct: float = 0.00015  # buy side only
    gst: float = 0.18  # on brokerage + exchange + sebi
    dp_charge: float = 14.75  # per scrip, sell side: Dhan Rs 12.50 + 18% GST


class ResearchCfg(BaseModel):
    """Fixed gates for the research harness (v4). Review if capital/contribution changes."""
    dsr_min: float = 0.95
    max_annual_charges_pct: float = 3.0
    max_correlation: float = 0.9
    min_fold_win_share: float = 2.0 / 3.0  # fraction of OOS years that must beat the index


class MomentumCfg(BaseModel):
    lookback: int = 126  # trading days of return used for ranking
    skip: int = 21  # most recent days excluded (short-term reversal)
    top_n: int = 20
    buffer: int = 10  # a holding is kept while its rank <= top_n + buffer (cuts turnover)
    bear_exit: bool = True  # sell everything when the market turns bearish, not just at rebalance


class AccountCfg(BaseModel):
    """Shared paper account (ledger.py). PROVISIONAL, owner to review."""

    max_sleeve_share: float = 0.40  # a sleeve's positions may not exceed this share of account equity (1.0 = no cap)


class Config(BaseModel):
    mode: Literal["paper", "live"] = "paper"  # "live" is not implemented; nothing in src/ places orders
    capital: float = 100_000
    monthly_contribution: float = 0  # INR added at each month-end close (paper sleeves and research harness)
    risk_per_trade: float = 0.01
    history_years: int = 10
    min_size_fraction: float = 0.5  # skip orders cash-limited below this share of intended size
    universe: UniverseCfg = UniverseCfg()
    momentum: MomentumCfg = MomentumCfg()
    regime: RegimeCfg = RegimeCfg()
    risk: RiskCfg = RiskCfg()
    costs: CostCfg = CostCfg()
    research: ResearchCfg = ResearchCfg()
    account: AccountCfg = AccountCfg()


def load_config(path: Path | None = None) -> Config:
    path = path or ROOT / "config.yaml"
    raw = yaml.safe_load(path.read_text()) if path.exists() else {}
    return Config(**(raw or {}))


def dhan_credentials() -> tuple[str, str]:
    load_dotenv(ROOT / ".env")
    cid, tok = os.getenv("DHAN_CLIENT_ID"), os.getenv("DHAN_ACCESS_TOKEN")
    if not cid or not tok:
        raise SystemExit(
            "DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN missing. Copy .env.example to .env "
            "and fill them in (tokens expire, so regenerate from the Dhan web console)."
        )
    return cid, tok
