"""Equal split of the shared account across active sleeves (PROVISIONAL, owner decision 2026-11-19).

Written before the engine change. N = active sleeves (momentum once started, swing if present, each promoted candidate).
Sleeve budget = account equity / N, measured at the open after sells. A sleeve may hold at most its budget; momentum's
(and a candidate's) per-name target is budget / top_n. Unused budget stays as cash (never handed to another sleeve).
Arbitration order is unchanged: sells first, then buys momentum, swing, candidates, each cut to the cash left.
"""
import numpy as np
import pandas as pd
import pytest

from helpers import CP, MP, _books, buy_cost
from trader import backtest as bt
from trader import ledger
from trader import momentum as mom
from trader.selector import Selector

D = 400
TOL = 1.0001


def _open(acct, cash, momq=None, swingq=None, candq=(), with_swing=True, with_mom=True):
    """One shared open. Queued buys: momentum (sym, target), swing (sym, value), candidates [(sym, target), ...]."""
    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, cash)
    cbooks = [mom.MomBook(cfg, mprep, CP, box) for _ in candq]
    if momq:
        mbook.buys = [(mprep.syms.index(momq[0]), momq[1])]
    if swingq:
        px = float(sprep.data[swingq[0]].o[D])
        swing.pending = [bt.Order(swingq[0], "breakout", "breakout#0", 2, "open", None, None, px * 0.5, None,
                                  int(swingq[1] // px), px, None)]
    for b, q in zip(cbooks, candq):
        b.buys = [(mprep.syms.index(q[0]), q[1])]
    ledger.open_session(D, swing if with_swing else None, mbook if with_mom else None, cfg.min_size_fraction,
                        cands=cbooks)
    sval = sum(p.qty * sprep.data[s].o[D] for s, p in swing.positions.items())
    _open.books = (swing, mbook, cbooks, mprep, sprep, cfg)  # for tests that assert exact quantities
    return box, mbook.value_at_open(D), sval, [c.value_at_open(D) for c in cbooks]


def _qty(book, sym):
    """Shares held in `sym` by a momentum/candidate book or a swing book (0 when none)."""
    if hasattr(book, "positions"):
        return book.positions[sym].qty if sym in book.positions else 0
    mprep = _open.books[3]
    si = mprep.syms.index(sym)
    return book.pos[si]["qty"] if si in book.pos else 0


# Hand calculation (day 400 opens: S3 304.427, S5 190.739, S6 263.736; buy fill = open x 1.0005; momentum/candidate qty =
# floor(min(target, cash, room) / (fill x 1.004)); swing qty = min(order qty, floor(cash / (fill x 1.01)), floor(room / fill))).
# Equity 90,000 (all cash), N = 3 -> budget 30,000 each; every sleeve asks for 50,000, so the budget is what cuts it.
#   momentum S3: divisor 305.797; floor(30,000/305.797) = 98 (intended floor(50,000/305.797) = 163; 98 >= 81.5) -> 98 shares.
#   swing S5: order int(50,000 // 190.739) = 262; budget limit floor(30,000/190.834) = 157 (157 >= 131) -> 157 shares.
#   candidate S6: divisor 264.923; floor(30,000/264.923) = 113 (intended 188; 113 >= 94) -> 113 shares.
#   Spend ~ 29,849 + 29,961 + 29,816 + ~105 charges = ~89,730, so cash (30,000 left before the candidate) never binds.
def test_a_three_sleeves_each_stay_within_a_third_of_equity_at_the_open(acct):
    box, m, s, (c,) = _open(acct, 90_000.0, momq=("S3", 50_000.0), swingq=("S5", 50_000.0), candq=[("S6", 50_000.0)])
    swing, mbook, (c0,), mprep, sprep, cfg = _open.books
    assert _qty(mbook, "S3") == 98
    assert _qty(swing, "S5") == 157
    assert _qty(c0, "S6") == 113
    spent = (buy_cost(cfg, float(mprep.o[D, mprep.syms.index("S3")]), 98) + buy_cost(cfg, float(sprep.data["S5"].o[D]), 157)
             + buy_cost(cfg, float(mprep.o[D, mprep.syms.index("S6")]), 113))
    assert box.value == pytest.approx(90_000.0 - spent)


def test_b_momentum_alone_has_the_whole_account_as_budget(acct):
    # holds a position, cash 4,000: the buy is limited by cash only, never by a share of equity
    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, 4_000.0)
    held = mprep.syms.index("S1")
    mbook.pos[held] = {"qty": 10, "px": float(mprep.o[D, held]), "cost": 0.0, "d": D - 5}
    equity = 4_000.0 + mbook.value_at_open(D)
    si = mprep.syms.index("S3")
    mbook.buys = [(si, 6_000.0)]  # cash covers 67% of it: cut to cash and taken
    ledger.open_session(D, None, mbook, cfg.min_size_fraction)
    q = mbook.pos[si]
    assert q["qty"] == int(4_000.0 // (q["px"] * 1.004))  # cash-limited: the whole account was its budget
    assert mbook.value_at_open(D) <= equity * TOL


# Hand calculation (prices as above): equity 10,000, N = 2 -> budget 5,000 each. Both ask for 9,000.
#   momentum S3: floor(min(9,000, 10,000, 5,000)/305.797) = 16 (intended 29; 16 >= 14.5) -> 16 shares (4,873.27 + ~5.7), cash ~5,121.
#   swing S5: order int(9,000 // 190.739) = 47; min(47, floor(5,121/192.742) = 26, floor(5,000/190.834) = 26) = 26 (26 >= 23.5)
#     -> 26 shares (4,961.69 + ~5.8). Momentum is capped at its half although it asked for 9,000 and cash allowed it; if the
#     budget were a third (3,333) momentum would get 10 shares (< 14.5) and be skipped.
def test_c_two_sleeves_get_half_each(acct):
    box, m, s, _ = _open(acct, 10_000.0, momq=("S3", 9_000.0), swingq=("S5", 9_000.0))
    swing, mbook, _c, mprep, sprep, cfg = _open.books
    assert _qty(mbook, "S3") == 16
    assert _qty(swing, "S5") == 26
    spent = buy_cost(cfg, float(mprep.o[D, mprep.syms.index("S3")]), 16) + buy_cost(cfg, float(sprep.data["S5"].o[D]), 26)
    assert box.value == pytest.approx(10_000.0 - spent)


# Hand calculation: equity 10,000, N = 2 (momentum is active but asks for nothing) -> budget 5,000. Swing S5 asks for 9,000:
#   min(47, floor(10,000/192.742) = 51, floor(5,000/190.834) = 26) = 26 shares (4,961.69 + ~5.8): the idle half is NOT
#   handed to swing (it would take 47), so cash ends ~5,032.5.
def test_unused_budget_is_not_reassigned(acct):
    box, m, s, _ = _open(acct, 10_000.0, swingq=("S5", 9_000.0))
    swing, mbook, _c, mprep, sprep, cfg = _open.books
    assert m == 0 and not mbook.pos
    assert _qty(swing, "S5") == 26
    assert box.value == pytest.approx(10_000.0 - buy_cost(cfg, float(sprep.data["S5"].o[D]), 26))


def test_existing_holdings_count_towards_the_budget(acct):
    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, 10_000.0)
    held = mprep.syms.index("S1")
    mbook.pos[held] = {"qty": 10, "px": float(mprep.o[D, held]), "cost": 0.0, "d": D - 5}
    mbook.buys = [(mprep.syms.index("S3"), 9_000.0)]
    equity = 10_000.0 + mbook.value_at_open(D)
    ledger.open_session(D, swing, mbook, cfg.min_size_fraction)  # swing + momentum: N = 2
    assert mbook.value_at_open(D) <= equity / 2 * TOL


def test_d_momentum_target_is_budget_over_top_n(acct):
    cfg, _, idx, sprep, strats, mprep = acct
    spec = ledger.AccountSpec(start=idx[300], capital=cfg.capital, contribution=cfg.monthly_contribution)

    def run(end_i):
        return ledger.run(cfg, spec, swing=ledger.SwingSpec(sprep, strats, Selector(), idx[300]),
                          mom=ledger.MomSpec(mprep, MP, idx[300]),
                          cands=[ledger.CandSpec("c0", mprep, CP, idx[300])], end=idx[end_i], emit_last=True)

    for i in range(330, 520):
        if mprep.rebal[i] and mprep.mkt[i] != 0:
            r = run(i)
            if r.mom.pending_buys:
                budget = r.equity["value"].iloc[-1] / 3  # momentum + swing + one candidate
                assert r.mom.pending_buys[0][1] == pytest.approx(budget / MP.top_n)
                return
    pytest.fail("no month-end with queued momentum buys")


def test_e_cash_never_negative_with_three_sleeves(acct):
    cfg, _, idx, sprep, strats, mprep = acct
    spec = ledger.AccountSpec(start=idx[300], capital=cfg.capital, contribution=cfg.monthly_contribution)
    r = ledger.run(cfg, spec, swing=ledger.SwingSpec(sprep, strats, Selector(), idx[300]),
                   mom=ledger.MomSpec(mprep, MP, idx[300]), cands=[ledger.CandSpec("c0", mprep, CP, idx[300])],
                   end=idx[520], emit_last=True)
    e = r.equity
    assert (e["swing_value"] > 0).any() and (e["mom_value"] > 0).any() and (e["cand_value"] > 0).any()
    assert (e["cash"] >= -1e-6).all()
    np.testing.assert_allclose(e["cash"] + e["swing_value"] + e["mom_value"] + e["cand_value"], e["value"], atol=1e-6)
