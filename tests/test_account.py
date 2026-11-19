"""One shared cash account for the paper ledger (swing + momentum).

Written before the engine: these describe the intended behaviour of `trader.ledger`, `accounting`
and the persisted `account_equity` table.
"""
import numpy as np
import pandas as pd
import pytest

from helpers import CAPITAL, DEPOSIT, MP, _books, _frames, buy_cost, patch_candles
from trader import backtest as bt
from trader import ledger, outputs, paper, report
from trader import momentum as mom
from trader.config import Config
from trader.selector import Selector
from trader.strategies import ALL


def _run(acct, end_i=520, start_i=300, **kw):
    cfg, _, idx, sprep, strats, mprep = acct
    spec = ledger.AccountSpec(start=idx[start_i], capital=cfg.capital, contribution=cfg.monthly_contribution)
    return ledger.run(
        cfg, spec, swing=ledger.SwingSpec(sprep, strats, Selector(), idx[start_i]),
        mom=ledger.MomSpec(mprep, MP, idx[start_i]), end=idx[end_i], emit_last=True, **kw)


def test_shared_cash_never_negative_and_sleeves_sum_to_account(acct):
    r = _run(acct)
    e = r.equity
    assert len(r.swing.trades) > 0 and len(r.mom.trades) > 0, "scenario must exercise both sleeves"
    assert (e["cash"] >= -1e-6).all()
    np.testing.assert_allclose(e["cash"] + e["swing_value"] + e["mom_value"], e["value"], atol=1e-6)
    assert (e["swing_value"] > 0).any() and (e["mom_value"] > 0).any()


def test_one_deposit_per_month_end_for_the_whole_account(acct):
    cfg, _, idx, _, _, mprep = acct
    r = _run(acct)
    e = r.equity
    month_ends = e.index[mprep.rebal[300:300 + len(e)]]
    steps = e["deposited"].diff().fillna(0.0)
    assert set(e.index[steps > 0]) == set(month_ends) and len(month_ends) > 5
    assert (steps[steps > 0] == DEPOSIT).all()  # 5,000 once, not once per sleeve
    assert e["deposited"].iloc[-1] == CAPITAL + DEPOSIT * len(month_ends)


def test_account_replay_is_identical_when_run_twice(acct):
    a, b = _run(acct), _run(acct)
    pd.testing.assert_frame_equal(a.equity, b.equity)
    pd.testing.assert_frame_equal(a.swing.trades, b.swing.trades)
    pd.testing.assert_frame_equal(a.mom.trades, b.mom.trades)


def test_replay_never_rewrites_history(acct):
    _, _, idx, *_ = acct
    a, b = _run(acct, end_i=450), _run(acct, end_i=451)
    pd.testing.assert_frame_equal(a.equity, b.equity.iloc[:-1])


def test_momentum_only_account_matches_standalone_momentum(acct):
    """Same engine, one sleeve, no swing: identical to mom.run (the backtest path is unchanged)."""
    cfg, _, idx, _, _, mprep = acct
    spec = ledger.AccountSpec(start=idx[300], capital=cfg.capital, contribution=cfg.monthly_contribution)
    r = ledger.run(cfg, spec, mom=ledger.MomSpec(mprep, MP, idx[300]), end=idx[520], emit_last=True)
    solo = mom.run(cfg, mprep, MP, idx[300], idx[520], emit_last=True, contribution=cfg.monthly_contribution)
    np.testing.assert_allclose(r.equity["value"], solo.equity["value"])
    np.testing.assert_allclose(r.equity["equity"], solo.equity["equity"])
    pd.testing.assert_frame_equal(r.mom.trades, solo.trades)


def test_swing_only_account_matches_standalone_backtest(acct):
    cfg, _, idx, sprep, strats, _ = acct
    spec = ledger.AccountSpec(start=idx[300], capital=cfg.capital, contribution=0.0)
    r = ledger.run(cfg, spec, swing=ledger.SwingSpec(sprep, strats, Selector(), idx[300]), end=idx[520], emit_last=True)
    solo = bt.run(cfg, sprep, strats, idx[300], idx[520], Selector(), emit_last=True)
    np.testing.assert_allclose(r.equity["value"], solo.equity["equity"])
    pd.testing.assert_frame_equal(r.swing.trades, solo.trades)


def _swing_order(sprep, sym, qty, d=400):
    px = float(sprep.data[sym].o[d])
    return bt.Order(sym, "breakout", "breakout#0", 2, "open", None, None, px * 0.5, None, qty, px, None)


# Hand calculation (day 400 opens: S1 152.424, S3 304.427, S5 190.739, S6 263.736; buy fill = open x 1.0005;
# momentum qty = floor(limit / (fill x 1.004)); swing qty = min(order qty, floor(cash / (fill x 1.01)), floor(room / fill))):
#   S3 fill 304.579 -> divisor 305.797;  S5 fill 190.834 -> cash divisor 192.742.
# Sleeves: momentum (buying S3), swing (buying S5), and a candidate that only HOLDS 40 x S1 (6,096.96 at the open) -> N = 3.
# Cash 4,000 -> equity 10,096.96 -> budget 3,365.65 each. The holder is over budget (room 0) and sits on its shares, so
# the 4,000 of cash is scarcer than the room of the other two (2 x 3,365).
#   momentum wants 3,300 of S3: min(3,300, 4,000, 3,365.65)/305.797 = 10.79 -> 10 shares; intended floor(3,300/305.797) = 10,
#     so it is a full fill. Spends 10 x 304.579 = 3,045.79 + charges -> cash left ~950.
#   swing's order is 30 x S5 (~5,725 > the whole 4,000 of cash): min(30, floor(950/192.742) = 4, floor(3,365.65/190.834) = 17)
#     = 4 shares, below half of 30 (15) -> SKIPPED. If swing went first it would take 17 (3,244) and momentum would be
#     left with 2 shares of 10 and skipped: that is the starvation this test pins.
def test_momentum_rebalance_buy_is_not_starved_by_swing_buy_on_the_same_day(acct):
    d = 400
    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, 4_000.0)
    holder = mom.MomBook(cfg, mprep, MP, box)
    s1 = mprep.syms.index("S1")
    holder.pos[s1] = {"qty": 40, "px": float(mprep.o[d, s1]), "cost": 0.0, "d": d - 5}
    s3 = mprep.syms.index("S3")
    mbook.buys = [(s3, 3_300.0)]
    swing.pending = [_swing_order(sprep, "S5", 30)]
    ledger.open_session(d, swing, mbook, cfg.min_size_fraction, cands=[holder])
    assert mbook.pos[s3]["qty"] == 10  # momentum first, in full
    assert "S5" not in swing.positions  # swing left with 4 shares of 30: skipped
    assert box.value == pytest.approx(4_000.0 - buy_cost(cfg, float(mprep.o[d, s3]), 10))
    assert list(holder.pos) == [s1] and holder.pos[s1]["qty"] == 40  # the holder only holds


# Hand calculation (S3 divisor 305.797, so a 1,000 cash account buys at most 3 shares; same prices as above):
#   alone: momentum asks 9,000 -> intended floor(9,000/305.797) = 29 shares (half = 14.5).
#     cash 1,000: floor(1,000/305.797) = 3 < 14.5 -> skipped, cash stays exactly 1,000.
#     cash 6,000: floor(6,000/305.797) = 19 >= 14.5 -> taken, 19 shares: 19 x 304.579 = 5,786.99 + charges.
def test_cash_short_buy_is_cut_to_cash_and_tiny_cuts_are_skipped(acct):
    d = 400
    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, 1_000.0)
    si = mprep.syms.index("S3")
    mbook.buys = [(si, 9_000.0)]  # cash covers 3 of 29 shares: below min_size_fraction -> skipped
    ledger.open_session(d, None, mbook, cfg.min_size_fraction)  # momentum alone: its budget is the whole account
    assert si not in mbook.pos and box.value == 1_000.0
    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, 6_000.0)
    mbook.buys = [(si, 9_000.0)]  # 19 of 29 shares: cut to cash and taken
    ledger.open_session(d, None, mbook, cfg.min_size_fraction)
    assert mbook.pos[si]["qty"] == 19
    assert box.value == pytest.approx(6_000.0 - buy_cost(cfg, float(mprep.o[d, si]), 19))


# Hand calculation, with swing present (N = 2, so the budget is equity / 2; S5 fill 190.834, cash divisor 192.742):
#   cash 1,000 -> budget 500. Momentum asks 9,000 (29 shares): min(9,000, 1,000, 500)/305.797 = 1 share < 14.5 -> skipped.
#     Swing asks 20 x S5: min(20, floor(1,000/192.742) = 5, floor(500/190.834) = 2) = 2 < 10 -> skipped. Cash stays 1,000.
#   cash 6,000 -> budget 3,000. Momentum asks 5,000 (intended floor(5,000/305.797) = 16, half = 8): the limit is the budget,
#     floor(3,000/305.797) = 9 >= 8 -> 9 shares (2,741.21 + charges -> cash left ~3,255).
#     Swing asks 20 x S5: min(20, floor(3,255/192.742) = 16, floor(3,000/190.834) = 15) = 15 >= 10 -> 15 shares: the
#     BUDGET (15), not the cash (16) and not the order (20), is what cuts it.
def test_cash_short_buy_with_swing_present_is_cut_by_cash_and_budget(acct):
    d = 400
    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, 1_000.0)
    s3 = mprep.syms.index("S3")
    mbook.buys = [(s3, 9_000.0)]
    swing.pending = [_swing_order(sprep, "S5", 20)]
    ledger.open_session(d, swing, mbook, cfg.min_size_fraction)
    assert s3 not in mbook.pos and "S5" not in swing.positions and box.value == 1_000.0

    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, 6_000.0)
    mbook.buys = [(s3, 5_000.0)]
    swing.pending = [_swing_order(sprep, "S5", 20)]
    ledger.open_session(d, swing, mbook, cfg.min_size_fraction)
    assert mbook.pos[s3]["qty"] == 9
    assert swing.positions["S5"].qty == 15
    spent = buy_cost(cfg, float(mprep.o[d, s3]), 9) + buy_cost(cfg, float(sprep.data["S5"].o[d]), 15)
    assert box.value == pytest.approx(6_000.0 - spent)


def test_momentum_target_is_a_share_of_its_budget(acct):
    """Equal split: with swing present N = 2, so target = (account equity / 2) / top_n (3 sleeves: test_account_budget.py)."""
    r = _run(acct)
    assert r.mom.pending_buys or r.mom.positions  # scenario exists
    cfg, _, idx, sprep, strats, mprep = acct
    # replay to a month-end signal day and compare the queued targets with total account value there
    for i in range(330, 520):
        if mprep.rebal[i] and mprep.mkt[i] != 0:
            rr = _run(acct, end_i=i)
            if rr.mom.pending_buys:
                assert rr.mom.pending_buys[0][1] == pytest.approx(rr.equity["value"].iloc[-1] / 2 / MP.top_n)
                return
    pytest.fail("no month-end with queued momentum buys")


# ---------------------------------------------------------------- persisted ledger + report
@pytest.fixture
def world(monkeypatch, pg):
    patch_candles(monkeypatch, _frames())
    inst = pd.DataFrame({"symbol": [f"S{i}" for i in range(8)], "sector": list("AABBCCDD")})
    outputs.save("walkforward", "", {"params": {n: {"key": f"{n}#0", "params": {}} for n in ALL}, "selector_stats": {}})
    return Config(capital=CAPITAL, monthly_contribution=DEPOSIT), inst, _frames()["NIFTY500"].index


def test_sync_persists_one_account_and_report_shows_it(world):
    cfg, inst, idx = world
    paper.init(cfg, idx[300])
    paper.init_momentum(cfg, idx[300], MP, None)
    st = paper.sync(cfg, inst, asof=str(idx[520].date()))
    e = st.account.equity
    con = paper._db(cfg)
    assert con.execute("SELECT COUNT(*) FROM account_equity").fetchone()[0] == len(e)
    cols = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns "
                                      "WHERE table_schema = current_schema() AND table_name = 'account_equity'")}
    con.close()
    assert {"cash", "swing_value", "mom_value", "value", "deposited"} <= cols
    np.testing.assert_allclose(e["cash"] + e["swing_value"] + e["mom_value"], e["value"], atol=1e-6)
    paper2 = paper.sync(cfg, inst, asof=str(idx[520].date()))
    pd.testing.assert_frame_equal(e, paper2.account.equity)  # replay twice, same ledger, whatever the run order

    report.write_report(cfg, st)
    md = outputs.get("daily", str(st.last_date.date()), "report")
    last = e.iloc[-1]
    assert "Account equity" in md and f"{last['value']:,.0f}" in md
    assert "Cash" in md and f"{last['cash']:,.0f}" in md
    assert "separate" not in md.lower() and "own capital" not in md.lower()


def test_account_start_and_funding_come_from_the_earliest_sleeve(world):
    cfg, inst, idx = world
    paper.init(cfg, idx[310])
    paper.init_momentum(cfg, idx[300], MP, None)
    st = paper.sync(cfg, inst, asof=str(idx[400].date()))
    assert st.account.equity.index[0] == idx[300]
    assert st.account.equity["value"].iloc[0] == pytest.approx(CAPITAL)  # one 50k pot, not two
