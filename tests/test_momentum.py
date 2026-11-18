import numpy as np
import pandas as pd
import pytest

from trader import momentum as mom
from trader.config import Config
from trader.data import store
from test_strategies_backtest import synth

N_SYM, N_BARS = 30, 700
P = mom.MomParams(lookback=126, skip=21, top_n=5, buffer=3)


def world(monkeypatch, bench_drift=0.0004, truncate=None):
    frames = {f"S{i}": synth(N_BARS, seed=i, drift=0.0005 + 0.0002 * (i % 5)) for i in range(N_SYM)}
    frames["NIFTY500"] = synth(N_BARS, seed=99, drift=bench_drift)
    if truncate is not None:
        frames = {k: v.iloc[: truncate + 1] for k, v in frames.items()}
    monkeypatch.setattr(store, "load", lambda d, s: frames.get(s))
    inst = pd.DataFrame({"symbol": [f"S{i}" for i in range(N_SYM)], "sector": "X"})
    cfg = Config(capital=1_000_000)
    return cfg, mom.prepare(cfg, inst), frames["NIFTY500"].index


def test_no_lookahead_equity_identical_on_truncated_history(monkeypatch):
    cfg, full, idx = world(monkeypatch)
    t = 500
    a = mom.run(cfg, full, P, idx[300], idx[t])
    cfg2, trunc, _ = world(monkeypatch, truncate=t)
    b = mom.run(cfg2, trunc, P, idx[300], idx[t])
    pd.testing.assert_frame_equal(a.equity, b.equity)
    assert len(a.trades) > 0


def test_invariants_and_position_cap(monkeypatch):
    cfg, prep, idx = world(monkeypatch)
    r = mom.run(cfg, prep, P, idx[300])
    assert len(r.trades) > 0
    assert (r.equity["equity"] > 0).all() and r.equity["invested"].between(0, 1.0001).all()
    t = r.trades
    assert ((t["gross_pnl"] - t["costs"] - t["net_pnl"]).abs() <= 0.02).all()
    assert (t["exit_date"] >= t["entry_date"]).all() and (t["costs"] > 0).all()
    ev = pd.concat([
        pd.Series(1, index=list(t["entry_date"]) + [idx[q["d"]] for q in r.positions.values()]),
        pd.Series(-1, index=t["exit_date"]),
    ]).groupby(level=0).sum().sort_index()
    assert ev.cumsum().max() <= P.top_n


def test_trades_only_enter_on_first_session_of_month(monkeypatch):
    """Rebalance signals fire at month end and fill at the next open."""
    cfg, prep, idx = world(monkeypatch)
    r = mom.run(cfg, prep, P, idx[300])
    first_of_month = {idx[i] for i in range(1, len(idx)) if idx[i].month != idx[i - 1].month}
    entries = set(r.trades["entry_date"]) | {idx[q["d"]] for q in r.positions.values()}
    assert entries <= first_of_month


def test_bear_market_means_cash(monkeypatch):
    cfg, prep, idx = world(monkeypatch, bench_drift=-0.004)  # index in a steady decline
    r = mom.run(cfg, prep, P, idx[450])
    assert len(r.trades) == 0 and not r.positions
    assert (r.equity["invested"] == 0).all()


def test_bear_exit_flag_sells_midmonth(monkeypatch):
    cfg, prep, idx = world(monkeypatch)
    firsts = [i for i in range(1, len(idx)) if idx[i].month != idx[i - 1].month]
    flip = next(i for i in firsts if i >= 480) + 1  # a mid-month bar, one session after a month start
    prep.mkt = prep.mkt.copy()
    prep.mkt[:] = 2
    prep.mkt[flip:] = 0  # market turns bearish at `flip`
    off_p = mom.MomParams(P.lookback, P.skip, P.top_n, P.buffer, False)
    end = idx[flip + 40]
    on, off = mom.run(cfg, prep, P, idx[300], end), mom.run(cfg, prep, off_p, idx[300], end)
    bear_on = on.trades[on.trades["reason"] == "bear"]
    assert len(bear_on) > 0 and (bear_on["exit_date"] == idx[flip + 1]).all()  # next open, not month end
    assert not on.positions
    bear_off = off.trades[off.trades["reason"] == "bear"]
    assert bear_off.empty or bear_off["exit_date"].min() > idx[flip + 1]  # waits for the rebalance


def test_random_control_is_deterministic_per_seed(monkeypatch):
    cfg, prep, idx = world(monkeypatch)
    q = mom.MomParams(126, 21, 5, 3, True, random_seed=3)
    a, b = mom.run(cfg, prep, q, idx[300]), mom.run(cfg, prep, q, idx[300])
    pd.testing.assert_frame_equal(a.trades, b.trades)
    c = mom.run(cfg, prep, mom.MomParams(126, 21, 5, 3, True, random_seed=4), idx[300])
    assert not a.trades.equals(c.trades)


def test_zero_contribution_value_equals_equity(monkeypatch):
    cfg, prep, idx = world(monkeypatch)
    r = mom.run(cfg, prep, P, idx[300])
    assert (r.equity["value"] == r.equity["equity"]).all()
    assert (r.equity["deposited"] == cfg.capital).all()


def test_deposits_are_not_returns(monkeypatch):
    """With deposits, `equity` is time-weighted: the same fills give the same daily returns as the lump-sum run when cash
    is idle, and a deposit day never shows up as a jump."""
    cfg, prep, idx = world(monkeypatch)
    r = mom.run(cfg, prep, P, idx[300], contribution=50_000)
    e = r.equity
    assert e["deposited"].iloc[-1] > cfg.capital and e["value"].iloc[-1] > e["equity"].iloc[-1]
    month_end = prep.rebal[300:300 + len(e)]
    dep_days = e.index[np.diff(e["deposited"].to_numpy(), prepend=e["deposited"].iloc[0]) > 0]
    assert len(dep_days) > 5 and set(dep_days) <= set(e.index[month_end])
    ret = e["equity"].pct_change().dropna()
    assert ret.abs().max() < 0.2  # no 5%-of-capital deposit masquerading as a return
    assert abs(e["value"].iloc[-1] - e["deposited"].iloc[-1]) < e["deposited"].iloc[-1]  # sanity: same order of magnitude


def test_contribution_deployed_at_next_rebalance(monkeypatch):
    cfg, prep, idx = world(monkeypatch)
    a = mom.run(cfg, prep, P, idx[300])
    b = mom.run(cfg, prep, P, idx[300], contribution=200_000)
    assert b.equity["value"].iloc[-1] > a.equity["value"].iloc[-1]
    assert b.equity["invested"].iloc[-1] <= 1.0001


def test_deposit_schedule_and_matched_value(monkeypatch):
    cfg, prep, idx = world(monkeypatch)
    dep = mom.deposit_schedule(prep, idx[300], idx[500], 1000.0, 100.0)
    assert dep.iloc[0] >= 1000.0 and dep.sum() == 1000.0 + 100.0 * prep.rebal[300:501].sum()
    flat = pd.Series(100.0, index=prep.dates)
    assert mom.matched_value(flat, dep) == pytest.approx(dep.sum())
    doubling = pd.Series(np.linspace(100, 200, len(prep.dates)), index=prep.dates)
    assert mom.matched_value(doubling, dep) > dep.sum()
