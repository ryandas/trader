"""The paper ledger's shared account: swing and momentum replayed together against ONE cash balance.

Design (owner decision, 2026-11-19): the ledger is a single cash account, not one pot per sleeve.

- One cash balance. It starts at `capital` and receives `contribution` once per month-end for the whole account.
- Both sleeves draw on that cash. Account equity = cash + swing positions + momentum positions.
- Momentum targets are an equal share (1 / top_n) of TOTAL account equity; swing sizing (risk per trade, position and heat
  caps, `min_size_fraction`) also uses TOTAL account equity. Position COUNTS (`max_positions`, `max_per_sector`) stay per
  sleeve, since they describe how many names a sleeve may hold.
- ARBITRATION on a shared session (the order cash is handed out at the open):
    1. every sell and exit first, swing (stop/target/rule/time exits) then momentum (rebalance/bear sells), so the
       cash they free is available to all buys;
    2. then buys: momentum's rebalance buys BEFORE swing's entries, so a month-end rebalance is never starved by swing;
    3. a buy is cut to the cash left; if the cut quantity is below `min_size_fraction` (0.5) of the intended quantity the
       buy is skipped. Cash never goes negative.
  Orders are queued from the previous close without reserving cash against each other; arbitration happens only when
  they fill, so the result does not depend on which sleeve is listed first in the code path that queues them.
- Like every sleeve, the account is a deterministic replay from its start date with frozen parameters (`paper.py`).
  Nothing incremental is stored, so re-running the replay gives the identical ledger.

This engine is used by the paper ledger only. `trader backtest`, `trader momentum`, walk-forward and the research
harness stay single-sleeve (`backtest.run`, `momentum.run`), each with its own pot, and are unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import backtest as bt
from . import momentum as mm
from .accounting import CashBox, Nav
from .config import Config
from .selector import Selector


@dataclass
class AccountSpec:
    start: pd.Timestamp  # first session of the account (earliest sleeve start)
    capital: float  # opening cash
    contribution: float = 0.0  # INR added once per month-end close, for the whole account


@dataclass
class SwingSpec:
    prep: bt.Prepared
    strategies: dict
    selector: Selector
    start: pd.Timestamp  # sleeve start: no orders are queued before it
    only: set[str] | None = None


@dataclass
class MomSpec:
    prep: mm.MomPrep
    params: mm.MomParams
    start: pd.Timestamp


@dataclass
class AccountResult:
    equity: pd.DataFrame  # index date; equity (time-weighted), invested (fraction), value, cash, swing_value, mom_value, deposited
    swing: bt.Result | None = None  # sleeve result: trades, open positions, queued orders; equity has column `value`
    mom: mm.MomResult | None = None  # same for the momentum sleeve
    cash: float = 0.0
    extra: dict = field(default_factory=dict)


def open_session(d: int, swing: bt.SwingBook | None, mbook: mm.MomBook | None, min_fraction: float) -> None:
    """The cash arbitration rule: all sells and exits, then momentum buys, then swing buys (see module docstring)."""
    if swing is not None:
        swing.exits(d)
    if mbook is not None:
        mbook.sell_at_open(d)
        mbook.buy_at_open(d, min_fraction)
    if swing is not None:
        swing.fills(d, min_fraction)


def run(
    cfg: Config,
    account: AccountSpec,
    swing: SwingSpec | None = None,
    mom: MomSpec | None = None,
    end: pd.Timestamp | None = None,
    emit_last: bool = False,
) -> AccountResult:
    """Replay the account from `account.start` to `end` (default: last bar). `emit_last` also queues orders from the
    final close (paper trading)."""
    if swing is None and mom is None:
        raise ValueError("an account needs at least one sleeve")
    dates = (swing.prep if swing else mom.prep).dates
    if swing and mom and not swing.prep.dates.equals(mom.prep.dates):
        raise ValueError("swing and momentum preps cover different dates; they must be built from the same candles")
    i0 = int(dates.searchsorted(account.start))
    i1 = int(dates.searchsorted(end, side="right")) if end is not None else len(dates)
    month_end = mm.month_end_mask(dates)  # deposit days: last session of each month

    cash = CashBox(account.capital)
    navs = Nav(account.capital, account.contribution)
    sbook = bt.SwingBook(cfg, swing.prep, swing.strategies, cash, swing.selector, swing.only) if swing else None
    mbook = mm.MomBook(cfg, mom.prep, mom.params, cash) if mom else None
    s0 = int(dates.searchsorted(swing.start)) if swing else None
    m0 = int(dates.searchsorted(mom.start)) if mom else None
    rows, s_rows, m_rows = [], [], []

    for d in range(i0, i1):
        s_on, m_on = swing is not None and d >= s0, mom is not None and d >= m0
        open_session(d, sbook, mbook, cfg.min_size_fraction)
        s_val = sbook.end_of_day(d) if sbook else 0.0
        m_val = mbook.invested(d) if mbook else 0.0
        nav, value, deposited = navs.mark(cash, s_val + m_val, bool(month_end[d]))
        rows.append((dates[d], nav, (s_val + m_val) / value if value > 0 else 0.0, value, cash.value, s_val, m_val, deposited))
        if s_on:
            s_rows.append((dates[d], s_val))
        if m_on:
            m_rows.append((dates[d], m_val))
        if d == i1 - 1 and not emit_last:
            continue
        if m_on:  # sleeve targets and risk are measured against TOTAL account value (cash + both sleeves)
            mbook.decide(d, value)
        if s_on:
            sbook.decide(d, value)

    eq = pd.DataFrame(rows, columns=["date", "equity", "invested", "value", "cash", "swing_value", "mom_value",
                                     "deposited"]).set_index("date")
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9) if len(eq) else 1
    avg = eq["value"].mean() if len(eq) else 1.0
    s_res = bt.Result(pd.DataFrame(sbook.trades), pd.DataFrame(s_rows, columns=["date", "value"]).set_index("date"),
                      list(sbook.positions.values()), sbook.pending) if sbook else None
    m_res = mm.MomResult(
        pd.DataFrame(mbook.trades), pd.DataFrame(m_rows, columns=["date", "value"]).set_index("date"),
        mbook.pos, mbook.sells, mbook.buys, mbook.traded_value / avg / years,
    ) if mbook else None
    return AccountResult(eq, s_res, m_res, cash.value)
