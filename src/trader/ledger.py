"""The paper ledger's shared account: swing and momentum replayed together against ONE cash balance.

Design (owner decision, 2026-11-19): the ledger is a single cash account, not one pot per sleeve.

- One cash balance. It starts at `capital` and receives `contribution` once per month-end for the whole account.
- Both sleeves draw on that cash. Account equity = cash + swing positions + momentum positions.
- EQUAL SPLIT (provisional, owner decision 2026-11-19): N = active sleeves (momentum once started, swing if present, each
  started promoted candidate). Each sleeve's BUDGET = account equity / N, measured at the open after sells. A sleeve
  may hold at most its budget (what it already holds counts); a buy is cut to the room left. Momentum's and a candidate's
  per-name target is budget / top_n. Swing risk per trade, `max_position_pct` and `max_heat` are still sized on TOTAL
  account equity, but its positions stay within its budget. Unused budget stays CASH: it is never reassigned to another
  sleeve. A lone sleeve's budget is the whole account. This one rule replaced the old `account.max_sleeve_share` cap.
  Position COUNTS (`max_positions`, `max_per_sector`) stay per sleeve.
- ARBITRATION on a shared session (the order cash is handed out at the open):
    1. every sell and exit first, swing (stop/target/rule/time exits) then momentum (rebalance/bear sells), so the
       cash they free is available to all buys;
    2. then buys: momentum's rebalance buys BEFORE swing's entries, so a month-end rebalance is never starved by swing;
    3. a buy is cut to the cash left and to the sleeve's budget room; if the cut quantity is below `min_size_fraction` (0.5) of the intended quantity the
       buy is skipped. Cash never goes negative.
- PROMOTED RESEARCH CANDIDATES (provisional, owner decision 2026-11-19) are further sleeves of this account (`CandSpec`).
  A candidate brings NO money: its positions are bought with the account's cash, it adds no deposit (the single
  month-end deposit is the only one), and its value counts toward account equity. Its promotion record's `capital` is the
  research harness's and is never read here. Its targets are budget / top_n, like momentum's.
  Candidates buy last, after momentum and swing, in promotion order. Research itself (`research-eval`, the trial
  registry) stays unfolded and does not touch the account.
- Orders are queued from the previous close without reserving cash against each other; arbitration happens only when
  they fill, so the result does not depend on which sleeve is listed first in the code path that queues them.
- Like every sleeve, the account is a deterministic replay from its start date with frozen parameters (`paper.py`).
  Nothing incremental is stored, so re-running the replay gives the identical ledger.

This engine is used by the paper ledger only. `trader backtest`, `trader momentum`, walk-forward and the research
harness stay single-sleeve (`backtest.run`, `momentum.run`), each with its own pot, and are unchanged.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
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
class CandSpec:
    """A promoted research candidate folded into the account. It has NO capital and NO contribution of its own: it
    buys with the account's cash and its value counts toward account equity. (The `capital` in its promotion record
    belongs to the research harness and is ignored here.)"""
    slug: str
    prep: mm.MomPrep
    params: mm.MomParams
    start: pd.Timestamp


@dataclass
class AccountResult:
    equity: pd.DataFrame  # index date; equity (time-weighted), invested (fraction), value, cash, swing_value, mom_value, cand_value, deposited
    swing: bt.Result | None = None  # sleeve result: trades, open positions, queued orders; equity has column `value`
    mom: mm.MomResult | None = None  # same for the momentum sleeve
    cash: float = 0.0
    cands: dict = field(default_factory=dict)  # slug -> mm.MomResult, in promotion order
    extra: dict = field(default_factory=dict)


def open_session(d: int, swing: bt.SwingBook | None, mbook: mm.MomBook | None, min_fraction: float,
                 cands: Sequence[mm.MomBook] = ()) -> None:
    """The cash arbitration rule: all sells and exits (every sleeve) first, then buys in the order momentum, swing,
    candidates (promotion order). Pass only the ACTIVE sleeves (started ones): N = how many are passed. Each sleeve's
    budget is account equity at the open (after sells) / N; a buy is cut to the cash left and to the budget room (the
    budget minus what the sleeve already holds), and skipped below `min_fraction` of its intended size. Unused budget
    stays cash: it is never handed to another sleeve."""
    if swing is not None:
        swing.exits(d)
    if mbook is not None:
        mbook.sell_at_open(d)
    for c in cands:
        c.sell_at_open(d)
    books = ([swing] if swing is not None else []) + ([mbook] if mbook is not None else []) + list(cands)
    if not books:
        return
    equity = (swing or mbook or cands[0]).cash.value + sum(b.value_at_open(d) for b in books)  # at the open, after sells

    budget = equity / len(books)

    def room(b) -> float:  # a lone sleeve's budget is the whole account: cash is the only limit
        return math.inf if len(books) == 1 else max(budget - b.value_at_open(d), 0.0)

    if mbook is not None:
        mbook.buy_at_open(d, min_fraction, room(mbook))
    if swing is not None:
        swing.fills(d, min_fraction, room(swing))
    for c in cands:
        c.buy_at_open(d, min_fraction, room(c))


def run(
    cfg: Config,
    account: AccountSpec,
    swing: SwingSpec | None = None,
    mom: MomSpec | None = None,
    end: pd.Timestamp | None = None,
    emit_last: bool = False,
    cands: Sequence[CandSpec] = (),
) -> AccountResult:
    """Replay the account from `account.start` to `end` (default: last bar). `emit_last` also queues orders from the
    final close (paper trading). `cands` are promoted research candidates in promotion order: they buy with the
    account's cash, add no deposit, and count toward account equity."""
    if swing is None and mom is None:
        raise ValueError("an account needs a swing or momentum sleeve")
    dates = (swing.prep if swing else mom.prep).dates
    if any(not s.prep.dates.equals(dates) for s in [x for x in (swing, mom) if x] + list(cands)):
        raise ValueError("sleeve preps cover different dates; they must be built from the same candles")
    i0 = int(dates.searchsorted(account.start))
    i1 = int(dates.searchsorted(end, side="right")) if end is not None else len(dates)
    month_end = mm.month_end_mask(dates)  # deposit days: last session of each month

    cash = CashBox(account.capital)
    navs = Nav(account.capital, account.contribution)
    sbook = bt.SwingBook(cfg, swing.prep, swing.strategies, cash, swing.selector, swing.only) if swing else None
    mbook = mm.MomBook(cfg, mom.prep, mom.params, cash) if mom else None
    s0 = int(dates.searchsorted(swing.start)) if swing else None
    m0 = int(dates.searchsorted(mom.start)) if mom else None
    cbooks = [mm.MomBook(cfg, c.prep, c.params, cash) for c in cands]  # same box: no capital of their own
    c0 = [int(dates.searchsorted(c.start)) for c in cands]
    rows, s_rows, m_rows, c_rows = [], [], [], [[] for _ in cands]

    for d in range(i0, i1):
        s_on, m_on = swing is not None and d >= s0, mom is not None and d >= m0
        c_on = [d >= c0[k] for k in range(len(cbooks))]
        n_active = int(s_on) + int(m_on) + sum(c_on)  # sleeves that share the account's equity equally
        open_session(d, sbook if s_on else None, mbook if m_on else None, cfg.min_size_fraction,
                     [b for b, on in zip(cbooks, c_on) if on])
        s_val = sbook.end_of_day(d) if sbook else 0.0
        m_val = mbook.invested(d) if mbook else 0.0
        c_vals = [b.invested(d) for b in cbooks]
        c_val = sum(c_vals)
        nav, value, deposited = navs.mark(cash, s_val + m_val + c_val, bool(month_end[d]))
        rows.append((dates[d], nav, (s_val + m_val + c_val) / value if value > 0 else 0.0, value, cash.value, s_val, m_val,
                     c_val, deposited))
        if s_on:
            s_rows.append((dates[d], s_val))
        if m_on:
            m_rows.append((dates[d], m_val))
        for k, v in enumerate(c_vals):
            if d >= c0[k]:
                c_rows[k].append((dates[d], v))
        if d == i1 - 1 and not emit_last:
            continue
        if m_on:  # momentum and candidate targets are a share of the sleeve's BUDGET (account equity / N)
            mbook.decide(d, value / n_active)
        if s_on:  # swing risk and position caps are measured against TOTAL account value
            sbook.decide(d, value)
        for k, b in enumerate(cbooks):
            if c_on[k]:
                b.decide(d, value / n_active)

    eq = pd.DataFrame(rows, columns=["date", "equity", "invested", "value", "cash", "swing_value", "mom_value",
                                     "cand_value", "deposited"]).set_index("date")
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9) if len(eq) else 1
    avg = eq["value"].mean() if len(eq) else 1.0
    s_res = bt.Result(pd.DataFrame(sbook.trades), pd.DataFrame(s_rows, columns=["date", "value"]).set_index("date"),
                      list(sbook.positions.values()), sbook.pending) if sbook else None
    m_res = mm.MomResult(
        pd.DataFrame(mbook.trades), pd.DataFrame(m_rows, columns=["date", "value"]).set_index("date"),
        mbook.pos, mbook.sells, mbook.buys, mbook.traded_value / avg / years,
    ) if mbook else None
    c_res = {c.slug: mm.MomResult(
        pd.DataFrame(b.trades), pd.DataFrame(rows_k, columns=["date", "value"]).set_index("date"),
        b.pos, b.sells, b.buys, b.traded_value / avg / years,
    ) for c, b, rows_k in zip(cands, cbooks, c_rows)}
    return AccountResult(eq, s_res, m_res, cash.value, c_res)
