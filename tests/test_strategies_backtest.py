import numpy as np
import pandas as pd
import pytest

from trader import backtest as bt
from trader.config import Config
from trader.data import store
from trader.strategies import ALL, features


def synth(n=500, seed=1, drift=0.0006):
    rng = np.random.default_rng(seed)
    close = 200 * np.exp(np.cumsum(rng.normal(drift, 0.015, n)))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
    vol = rng.integers(2_000_000, 6_000_000, n).astype(float)
    vol[::37] *= 3
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=pd.bdate_range("2022-01-03", periods=n, name="date"),
    )


@pytest.mark.parametrize("name", list(ALL))
def test_signals_have_no_lookahead(name):
    df = synth(500)
    t = 350
    full = ALL[name]().signals(features(df))
    part = ALL[name]().signals(features(df.iloc[: t + 1]))
    for field in ("signal", "trigger", "stop", "target", "trail", "exit_now"):
        a, b = getattr(full, field).iloc[: t + 1], getattr(part, field)
        pd.testing.assert_series_equal(a, b, check_names=False, check_exact=False)


def test_strategies_actually_fire():
    f = features(synth(1200, seed=3))
    counts = {n: int(ALL[n]().signals(f).signal.sum()) for n in ALL}
    assert all(c > 0 for c in counts.values()), counts


@pytest.fixture
def synth_backtest(monkeypatch):
    frames = {f"S{i}": synth(500, seed=i) for i in range(8)}
    frames["NIFTY500"] = synth(500, seed=99, drift=0.0004)
    monkeypatch.setattr(store, "load", lambda d, s: frames.get(s))
    inst = pd.DataFrame({"symbol": [k for k in frames if k != "NIFTY500"], "sector": ["A", "A", "B", "B", "C", "C", "D", "D"]})
    cfg = Config(capital=1_000_000)
    strats = {n: ALL[n]() for n in ALL}
    prep = bt.prepare(cfg, inst, list(strats.values()), filters=False)
    return cfg, prep, strats


def test_backtest_invariants(synth_backtest):
    cfg, prep, strats = synth_backtest
    res = bt.run(cfg, prep, strats, pd.Timestamp("2023-06-01"))
    assert len(res.trades) > 0
    assert res.equity["equity"].notna().all() and (res.equity["equity"] > 0).all()
    assert (res.equity["invested"].between(0, 1.0001)).all()
    t = res.trades
    assert (t["exit_date"] >= t["entry_date"]).all()
    assert (t["costs"] > 0).all()
    assert ((t["gross_pnl"] - t["costs"] - t["net_pnl"]).abs() <= 0.02).all()
    # entry exposure cap: never more than max_position_pct of starting capital * growth bound
    assert (t["qty"] * t["entry_price"] <= 0.2 * res.equity["equity"].max() * 1.02).all()


def test_backtest_respects_max_positions(synth_backtest):
    cfg, prep, strats = synth_backtest
    cfg.risk.max_positions = 2
    res = bt.run(cfg, prep, strats, pd.Timestamp("2023-06-01"))
    ev = pd.concat([
        pd.Series(1, index=res.trades["entry_date"]),
        pd.Series(-1, index=res.trades["exit_date"]),
    ]).groupby(level=0).sum().sort_index()
    # same-day exit frees the slot before entry, so net open count is bounded by the cap
    assert ev.cumsum().max() <= 2


def test_backtest_is_deterministic(synth_backtest):
    cfg, prep, strats = synth_backtest
    a = bt.run(cfg, prep, strats, pd.Timestamp("2023-06-01"))
    b = bt.run(cfg, prep, strats, pd.Timestamp("2023-06-01"))
    pd.testing.assert_frame_equal(a.trades, b.trades)
