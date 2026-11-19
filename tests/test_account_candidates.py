"""Promoted research candidates are folded into the shared account (PROVISIONAL design, owner decision 2026-11-19).

A candidate brings no money: its positions are bought with the account's cash, it adds no deposit, its value counts
toward account equity, and it shares the account equally with the other active sleeves (budget = equity / N; the
budget rules themselves are tested in test_account_budget.py). Arbitration on a shared open: all sells/exits first, then
buys in the order momentum, swing, candidates (promotion order).
"""
import numpy as np
import pandas as pd
import pytest
import yaml

from helpers import CAPITAL, CP, DEPOSIT, HONEST, MP, _books, _ledger, buy_cost
from trader import backtest as bt
from trader import ledger, paper
from trader import momentum as mom
from trader.config import ROOT, Config
from trader.selector import Selector



def _run(acct, n_cands=1, end_i=520, start_i=300, cand_start_i=300, with_swing=True):
    cfg, _, idx, sprep, strats, mprep = acct
    spec = ledger.AccountSpec(start=idx[start_i], capital=cfg.capital, contribution=cfg.monthly_contribution)
    cands = [ledger.CandSpec(f"c{i}", mprep, CP, idx[cand_start_i]) for i in range(n_cands)]
    return ledger.run(
        cfg, spec, swing=ledger.SwingSpec(sprep, strats, Selector(), idx[start_i]) if with_swing else None,
        mom=ledger.MomSpec(mprep, MP, idx[start_i]), cands=cands, end=idx[end_i], emit_last=True)


def test_candidate_takes_cash_from_the_account_and_adds_no_deposit(acct):
    base, with_c = _run(acct, n_cands=0), _run(acct, n_cands=1)
    e = with_c.equity
    assert len(with_c.cands["c0"].trades) > 0 or with_c.cands["c0"].positions, "scenario must exercise the candidate"
    assert e["value"].iloc[0] == pytest.approx(CAPITAL)  # opening: the account's cash only, no extra capital
    pd.testing.assert_series_equal(e["deposited"], base.equity["deposited"])  # same single deposit stream
    steps = e["deposited"].diff().fillna(0.0)
    assert (steps[steps > 0] == DEPOSIT).all()
    assert (e["cash"] >= -1e-6).all()
    assert (e["cand_value"] > 0).any()


def test_account_equals_cash_plus_all_sleeve_values(acct):
    r = _run(acct, n_cands=2)
    e = r.equity
    np.testing.assert_allclose(e["cash"] + e["swing_value"] + e["mom_value"] + e["cand_value"], e["value"], atol=1e-6)
    per_cand = sum(c.equity["value"].reindex(e.index).fillna(0.0) for c in r.cands.values())
    np.testing.assert_allclose(per_cand, e["cand_value"], atol=1e-6)


def test_a_candidate_started_later_changes_nothing_before_its_start(acct):
    _, _, idx, *_ = acct
    a = _run(acct, n_cands=0, end_i=400)
    b = _run(acct, n_cands=1, end_i=400, cand_start_i=390)
    cut = idx[391]  # orders from the start close fill at the next session
    left = [c for c in a.equity.columns if c != "cand_value"]
    pd.testing.assert_frame_equal(a.equity[a.equity.index < cut][left], b.equity[b.equity.index < cut][left])


def _open(acct, cash, momq=None, swingq=None, candq=(), held=None, d=400):
    """One shared open with queued buys: momentum (sym, target), swing (symbol, value), candidates [(sym, target), ...].
    Only the sleeves that have an order (or a holding) take part, so N is the number of those sleeves.
    `held` = (index of the book in [mom, cand0, ...], symbol, qty): a position it already holds."""
    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, cash)
    cbooks = [mom.MomBook(cfg, mprep, CP, box) for _ in candq]
    if momq:
        mbook.buys = [(mprep.syms.index(momq[0]), momq[1])]
    if swingq:
        px = float(sprep.data[swingq[0]].o[d])
        swing.pending = [bt.Order(swingq[0], "breakout", "breakout#0", 2, "open", None, None, px * 0.5, None,
                                  int(swingq[1] // px), px, None)]
    for b, q in zip(cbooks, candq):
        b.buys = [(mprep.syms.index(q[0]), q[1])]
    if held:
        b = ([mbook] + cbooks)[held[0]]
        si = mprep.syms.index(held[1])
        b.pos[si] = {"qty": held[2], "px": float(mprep.o[d, si]), "cost": 0.0, "d": d - 5}
    ledger.open_session(d, swing if swingq else None, mbook if (momq or held and held[0] == 0) else None,
                        cfg.min_size_fraction, cands=cbooks)
    return box, swing, mbook, cbooks, mprep, sprep


# Hand calculation (day 400 opens: S1 152.424, S3 304.427, S5 190.739, S6 263.736, S7 135.447; buy fill = open x 1.0005;
# momentum/candidate qty = floor(min(target, cash, room) / (fill x 1.004)); swing qty = min(order qty, floor(cash / (fill x 1.01)),
# floor(room / fill)); divisors: S3 305.797, S5 190.834 (cash 192.742), S6 264.923).
# Four sleeves: momentum, swing, candidate c0 (the three that buy) and candidate c1, which only HOLDS 30 x S1 (4,572.72).
# Cash 3,000 -> equity 7,572.72 -> budget 1,893.18 each; the holder is over budget (room 0), so cash (3,000) is scarcer
# than the room of the three buyers (3 x 1,893), and the ORDER decides who is cut.
#   1. momentum asks 1,500 of S3: min(1,500, 3,000, 1,893.18)/305.797 = 4.9 -> 4 shares (intended 4: full).
#      Spends 4 x 304.579 = 1,218.32 + ~1.5 charges -> cash ~1,780.
#   2. swing's order is int(1,200 // 190.739) = 6 x S5: min(6, floor(1,780/192.742) = 9, floor(1,893.18/190.834) = 9) = 6 (full).
#      Spends 6 x 190.834 = 1,145.00 + ~1.4 -> cash ~633.8.
#   3. c0 asks 1,000 of S6: intended floor(1,000/264.923) = 3; min(1,000, 633.8, 1,893.18)/264.923 = 2.39 -> 2 shares,
#      2 >= 0.5 x 3 = 1.5 so it is TAKEN (cut to the cash left, not skipped). Cash ends ~ 633.8 - 527.7 - 0.6 = ~105.
#   4. c1 asks 1,000 of S7 but its room is max(1,893.18 - 4,572.72, 0) = 0 -> nothing.
# Candidate before swing would give c0 3 shares and swing 5, so the numbers 4 / 6 / 2 pin momentum -> swing -> candidate.
def test_arbitration_buys_go_momentum_then_swing_then_candidates(acct):
    cfg = acct[0]
    box, swing, mbook, (c0, c1), mprep, sprep = _open(
        acct, 3_000.0, momq=("S3", 1_500.0), swingq=("S5", 1_200.0), candq=[("S6", 1_000.0), ("S7", 1_000.0)],
        held=(2, "S1", 30))
    s1, s3, s6 = (mprep.syms.index(s) for s in ("S1", "S3", "S6"))
    assert {si: q["qty"] for si, q in mbook.pos.items()} == {s3: 4}
    assert {sym: p.qty for sym, p in swing.positions.items()} == {"S5": 6}
    assert {si: q["qty"] for si, q in c0.pos.items()} == {s6: 2}  # the candidate was checked: cut 3 -> 2, not skipped
    assert {si: q["qty"] for si, q in c1.pos.items()} == {s1: 30}  # over budget: bought nothing
    spent = (buy_cost(cfg, float(mprep.o[400, s3]), 4) + buy_cost(cfg, float(sprep.data["S5"].o[400]), 6)
             + buy_cost(cfg, float(mprep.o[400, s6]), 2))
    assert box.value == pytest.approx(3_000.0 - spent)


# Hand calculation (same prices and divisors as above). Three sleeves: momentum (buying S3), swing (buying S5), and a
# candidate that only HOLDS 40 x S1 (6,096.96). Cash 4,000 -> equity 10,096.96 -> budget 3,365.65 (the holder is over it).
#   momentum asks 2,000 of S3: floor(2,000/305.797) = 6 shares (full; 6 x 304.579 = 1,827.47 + ~2.1) -> cash ~2,170.
#   swing's order is 20 x S5 (~3,815, MORE than the 2,170 left): min(20, floor(2,170/192.742) = 11, floor(3,365.65/190.834) = 17)
#     = 11 shares; 11 >= 0.5 x 20 = 10, so it is CUT TO THE REMAINDER and taken (11 x 190.834 = 2,099.17 + ~2.4 -> cash ~69).
#   Swing first would take 17 shares (3,244) and leave momentum 2 shares of 6 (below 3): skipped.
def test_swing_order_larger_than_momentums_leftover_cash_is_cut_to_the_remainder(acct):
    cfg = acct[0]
    box, swing, mbook, (holder,), mprep, sprep = _open(
        acct, 4_000.0, momq=("S3", 2_000.0), swingq=("S5", 3_820.0), candq=[("S7", 100.0)], held=(1, "S1", 40))
    s1, s3 = mprep.syms.index("S1"), mprep.syms.index("S3")  # swing value 3,820 sizes to int(3,820 // 190.739) = 20 shares
    assert {si: q["qty"] for si, q in mbook.pos.items()} == {s3: 6}
    assert {sym: p.qty for sym, p in swing.positions.items()} == {"S5": 11}
    assert {si: q["qty"] for si, q in holder.pos.items()} == {s1: 40}
    spent = buy_cost(cfg, float(mprep.o[400, s3]), 6) + buy_cost(cfg, float(sprep.data["S5"].o[400]), 11)
    assert box.value == pytest.approx(4_000.0 - spent)


def test_candidate_buys_in_promotion_order(acct):
    # c0, c1 and a momentum holding of ~7,000: cash 3,000 of a ~10,000 account; each budget ~3,333, both ask for it
    box, swing, mbook, (c0, c1), mprep, _ = _open(acct, 3_000.0, candq=[("S6", 3_300.0), ("S7", 3_300.0)],
                                                  held=(0, "S1", 70))
    assert c0.pos and not c1.pos  # first promoted is served first; the second is cut below min_size_fraction
    assert box.value >= 0


def test_sells_of_every_sleeve_come_before_any_buy(acct):
    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, 0.0)
    cbook = mom.MomBook(cfg, mprep, CP, box)
    d = 400
    held, want = mprep.syms.index("S1"), mprep.syms.index("S3")
    px = float(mprep.o[d, held])
    cbook.pos[held] = {"qty": 50, "px": px, "cost": 0.0, "d": d - 5}
    cbook.sells = {held: "rebalance"}
    mbook.buys = [(want, 0.4 * 50 * px)]  # needs cash that only the candidate's sell can free; fits half the account
    ledger.open_session(d, None, mbook, cfg.min_size_fraction, cands=[cbook])
    assert held not in cbook.pos and want in mbook.pos


def test_the_account_split_is_not_a_config_value(acct):
    # the old `account.max_sleeve_share` cap was replaced by the equal budget: neither config nor config.yaml has it
    assert not hasattr(Config(), "account")
    assert "account" not in yaml.safe_load((ROOT / "config.yaml").read_text())


# ---------------------------------------------------------------- persisted ledger: the record's capital is ignored
def _record(slug, capital, start):
    from trader.research import registry
    return {"kind": "rotation", "liquid_top": None, "capital": capital, "contribution": 5000.0, "start": str(start.date()),
            "params": dict(lookback=126, skip=21, top_n=3, buffer=2, bear_exit=True, random_seed=None, ranker="momentum",
                           ranker_params=[], rebalance="M"),
            "file_sha256": registry.sha256(slug), "trial_id": 1, "active": True, "tier": "backtest_pass",
            "promoted": "2026-01-01T00:00:00"}


def test_candidate_record_capital_does_not_change_account_equity_or_deposits(lab):
    cfg, inst, idx, cdir = lab
    cfg = cfg.model_copy(update=dict(capital=50_000, monthly_contribution=5_000))
    _ledger((cfg, inst, idx, cdir), "t_cap", HONEST)
    out = {}
    for cap in (5_000.0, 7_500_000.0):
        con = paper._db(cfg)
        with con:
            paper._put_meta(con, "candidates", {"t_cap": _record("t_cap", cap, idx[300])})
        con.close()
        st = paper.sync(cfg, inst, asof=str(idx[450].date()))
        assert "t_cap" in st.cands and not st.cand_errors
        out[cap] = st.account.equity
    pd.testing.assert_frame_equal(out[5_000.0], out[7_500_000.0])  # the record's capital is never used
    e = out[5_000.0]
    assert e["value"].iloc[0] == pytest.approx(50_000)  # no extra 5,000 (or 7.5m) at the candidate's start
    assert e["deposited"].diff().fillna(0.0).isin([0.0, 5_000.0]).all()  # only the account's own deposit
    assert (e["cand_value"] >= 0).all() and (e["cash"] >= -1e-6).all()
    np.testing.assert_allclose(e["cash"] + e["swing_value"] + e["mom_value"] + e["cand_value"], e["value"], atol=1e-6)
