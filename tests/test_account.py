"""One shared cash account for the paper ledger (swing + momentum).

Written before the engine: these describe the intended behaviour of `trader.ledger`, `accounting`
and the persisted `account_equity` table.
"""
import numpy as np
import pandas as pd
import pytest

from helpers import patch_candles
from test_strategies_backtest import synth
from trader import backtest as bt
from trader import ledger, outputs, paper, report
from trader import momentum as mom
from trader.accounting import CashBox
from trader.config import Config
from trader.selector import Selector
from trader.strategies import ALL

MP = mom.MomParams(lookback=126, skip=21, top_n=5, buffer=3)
CAPITAL, DEPOSIT = 50_000.0, 5_000.0


def _frames():
    frames = {f"S{i}": synth(600, seed=i) for i in range(8)}
    frames["NIFTY500"] = synth(600, seed=99, drift=0.0004)
    return frames


@pytest.fixture
def acct(monkeypatch):
    """(cfg, instruments, index, swing prep, strategies, mom prep) on synthetic candles; no database."""
    frames = _frames()
    patch_candles(monkeypatch, frames)
    inst = pd.DataFrame({"symbol": [f"S{i}" for i in range(8)], "sector": list("AABBCCDD")})
    cfg = Config(capital=CAPITAL, monthly_contribution=DEPOSIT)
    strats = {f"{n}#0": ALL[n]() for n in ALL}
    for k, s in strats.items():
        s.key = k
    sprep = bt.prepare(cfg, inst, list(strats.values()), filters=False)
    mprep = mom.prepare(cfg, inst)
    return cfg, inst, frames["NIFTY500"].index, sprep, strats, mprep


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


def _books(acct, cash):
    cfg, _, idx, sprep, strats, mprep = acct
    box = CashBox(cash)
    swing = bt.SwingBook(cfg, sprep, strats, box, Selector())
    mbook = mom.MomBook(cfg, mprep, MP, box)
    return cfg, idx, sprep, mprep, box, swing, mbook


def test_momentum_rebalance_buy_is_not_starved_by_swing_buy_on_the_same_day(acct):
    d = 400
    sym = "S3"
    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, 10_000.0)
    si = mprep.syms.index(sym)
    target = 9_000.0
    mbook.buys = [(si, target)]
    # a swing order on another name that would eat all the cash if it were processed first
    other = "S5"
    px = float(sprep.data[other].o[d])
    swing.pending = [bt.Order(other, "breakout", "breakout#0", 2, "open", None, None, px * 0.9, None, 1000, px, None)]
    ledger.open_session(d, swing, mbook, cfg.min_size_fraction)
    qty_mom = mbook.pos[si]["qty"]
    fp = mbook.pos[si]["px"]
    assert qty_mom == int(min(target, 10_000.0) // (fp * 1.004))  # full momentum size, as if swing did not exist
    assert box.value >= 0
    # swing got only what was left: cut to the cash available or skipped by min_size_fraction, never negative cash
    assert (other not in swing.positions) or swing.positions[other].qty < 1000


def test_cash_short_buy_is_cut_to_cash_and_tiny_cuts_are_skipped(acct):
    d = 400
    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, 1_000.0)
    si = mprep.syms.index("S3")
    mbook.buys = [(si, 9_000.0)]  # cash covers ~11% of the target: below min_size_fraction -> skipped
    ledger.open_session(d, swing, mbook, cfg.min_size_fraction)
    assert si not in mbook.pos and box.value == 1_000.0
    cfg, idx, sprep, mprep, box, swing, mbook = _books(acct, 6_000.0)
    mbook.buys = [(si, 9_000.0)]  # 67% of target: cut to cash and taken
    ledger.open_session(d, swing, mbook, cfg.min_size_fraction)
    assert si in mbook.pos and 0 <= box.value < 6_000.0


def test_momentum_target_is_a_share_of_total_account_equity(acct):
    """Equal weight of TOTAL equity: target = account equity / top_n, so swing positions count in the denominator."""
    r = _run(acct)
    assert r.mom.pending_buys or r.mom.positions  # scenario exists
    cfg, _, idx, sprep, strats, mprep = acct
    # replay to a month-end signal day and compare the queued targets with total account value there
    for i in range(330, 520):
        if mprep.rebal[i] and mprep.mkt[i] != 0:
            rr = _run(acct, end_i=i)
            if rr.mom.pending_buys:
                assert rr.mom.pending_buys[0][1] == pytest.approx(rr.equity["value"].iloc[-1] / MP.top_n)
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
