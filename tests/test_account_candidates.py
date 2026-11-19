"""Promoted research candidates are folded into the shared account (PROVISIONAL design, owner decision 2026-11-19).

Written before the engine change. A candidate brings no money: its positions are bought with the account's cash, it adds
no deposit, its value counts toward account equity, and each sleeve (momentum, swing, candidates) is capped at
`account.max_sleeve_share` of account equity. Arbitration on a shared open: all sells/exits first, then buys in the
order momentum, swing, candidates (promotion order).
"""
import numpy as np
import pandas as pd
import pytest
import yaml

from test_account import CAPITAL, DEPOSIT, MP, _books, acct  # noqa: F401  (acct is a fixture)
from test_research import HONEST, _ledger, lab  # noqa: F401  (lab is a fixture)
from trader import backtest as bt
from trader import ledger, paper
from trader import momentum as mom
from trader.config import ROOT, AccountCfg, Config
from trader.selector import Selector

CP = mom.MomParams(lookback=60, skip=5, top_n=3, buffer=2)  # a candidate sleeve: different ranking, 3 names


def _cfg(acct, share):
    return acct[0].model_copy(update=dict(account=AccountCfg(max_sleeve_share=share)))


def _run(acct, share=1.0, n_cands=1, end_i=520, start_i=300, cand_start_i=300, with_swing=True):
    cfg, _, idx, sprep, strats, mprep = acct
    cfg = _cfg(acct, share)
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


def _open(acct, cash, share, momq=None, swingq=None, candq=(), d=400):
    """One shared open with queued buys: momentum (sym, target), swing (symbol, value), candidates [(sym, target), ...]."""
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
    ledger.open_session(d, swing, mbook, cfg.min_size_fraction, cands=cbooks, max_share=share)
    return box, swing, mbook, cbooks, mprep, sprep


def test_arbitration_buys_go_momentum_then_swing_then_candidates(acct):
    # momentum takes 6,000 of 10,000; swing wants 7,000 and is cut to what is left (~4,000); the candidate gets nothing
    box, swing, mbook, (c0,), mprep, sprep = _open(acct, 10_000.0, 1.0, momq=("S3", 6_000.0), swingq=("S5", 7_000.0),
                                                   candq=[("S6", 6_000.0)])
    si = mprep.syms.index("S3")
    assert mbook.pos[si]["qty"] == int(6_000.0 // (mbook.pos[si]["px"] * 1.004))
    intended = int(7_000.0 // float(sprep.data["S5"].o[400]))
    assert "S5" in swing.positions and swing.positions["S5"].qty < intended  # cut to the cash that was left
    assert not c0.pos
    assert box.value >= 0


def test_candidate_buys_in_promotion_order(acct):
    box, swing, mbook, (c0, c1), mprep, _ = _open(acct, 7_000.0, 1.0, candq=[("S6", 6_000.0), ("S7", 6_000.0)])
    assert c0.pos and not c1.pos  # first promoted is served first; the second is cut below min_size_fraction
    assert box.value >= 0


def test_sells_of_every_sleeve_come_before_any_buy(acct):
    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, 0.0)
    cbook = mom.MomBook(cfg, mprep, CP, box)
    d = 400
    held, want = mprep.syms.index("S1"), mprep.syms.index("S3")
    cbook.pos[held] = {"qty": 50, "px": float(mprep.o[d, held]), "cost": 0.0, "d": d - 5}
    cbook.sells = {held: "rebalance"}
    mbook.buys = [(want, 5_000.0)]  # momentum's buy needs cash that only the candidate's sell can free
    ledger.open_session(d, swing, mbook, cfg.min_size_fraction, cands=[cbook], max_share=1.0)
    assert held not in cbook.pos and want in mbook.pos


def test_sleeve_cap_cuts_a_buy_and_skips_it_below_min_size(acct):
    # 40% of equity 10,000 = 4,000: a 6,000 target is cut to the cap (67% of intended) and taken
    box, _, mbook, _, mprep, _ = _open(acct, 10_000.0, 0.4, momq=("S3", 6_000.0))
    q = mbook.pos[mprep.syms.index("S3")]
    assert 0.3 * 10_000.0 < q["qty"] * q["px"] <= 0.4 * 10_000.0  # cut TO the cap, not skipped
    # a 2% cap leaves room for under half the intended quantity: skipped, like a cash-short buy
    box, _, mbook, _, mprep, _ = _open(acct, 10_000.0, 0.02, momq=("S3", 6_000.0))
    assert not mbook.pos and box.value == 10_000.0


def test_cap_applies_to_every_sleeve_and_counts_what_the_sleeve_already_holds(acct):
    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, 10_000.0)
    cbook = mom.MomBook(cfg, mprep, CP, box)
    d = 400
    held = mprep.syms.index("S1")
    cbook.pos[held] = {"qty": 10, "px": float(mprep.o[d, held]), "cost": 0.0, "d": d - 5}
    equity = 10_000.0 + 10 * float(mprep.o[d, held])
    cbook.buys = [(mprep.syms.index("S6"), 6_000.0)]
    px = float(sprep.data["S5"].o[d])
    swing.pending = [bt.Order("S5", "breakout", "breakout#0", 2, "open", None, None, px * 0.5, None,
                              int(6_000 // px), px, None)]
    ledger.open_session(d, swing, mbook, cfg.min_size_fraction, cands=[cbook], max_share=0.4)
    cand_value = sum(q["qty"] * mprep.o[d, si] for si, q in cbook.pos.items())
    assert cand_value <= 0.4 * equity * 1.0001  # the existing holding counts toward the cap
    sw_value = sum(p.qty * sprep.data[s].o[d] for s, p in swing.positions.items())
    assert 0 < sw_value <= 0.4 * equity * 1.0001


def test_cap_is_a_config_value_not_a_constant(acct):
    assert Config().account.max_sleeve_share == 0.40
    assert yaml.safe_load((ROOT / "config.yaml").read_text())["account"]["max_sleeve_share"] == 0.40
    tight, loose = _run(acct, share=0.15), _run(acct, share=1.0)
    assert tight.equity["mom_value"].max() < loose.equity["mom_value"].max()


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
    assert (e["cand_value"] > 0).any() and (e["cash"] >= -1e-6).all()
    np.testing.assert_allclose(e["cash"] + e["swing_value"] + e["mom_value"] + e["cand_value"], e["value"], atol=1e-6)
