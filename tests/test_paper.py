import json

import pandas as pd
import pytest

from trader import backtest as bt
from helpers import patch_candles
from trader import paper
from trader.config import Config
from trader.data import store
from trader.selector import Selector
from trader.strategies import ALL
from test_strategies_backtest import synth


@pytest.fixture
def world(monkeypatch, tmp_path):
    frames = {f"S{i}": synth(600, seed=i) for i in range(8)}
    frames["NIFTY500"] = synth(600, seed=99, drift=0.0004)
    patch_candles(monkeypatch, frames)
    monkeypatch.setattr(Config, "data_dir", property(lambda self: tmp_path))
    inst = pd.DataFrame({"symbol": [f"S{i}" for i in range(8)], "sector": list("AABBCCDD")})
    (tmp_path / "params.json").write_text(json.dumps(
        {n: {"key": f"{n}#0", "params": {}} for n in ALL}))
    (tmp_path / "selector_stats.json").write_text(json.dumps({}))
    return Config(capital=1_000_000), inst, frames["NIFTY500"].index


def test_replay_is_prefix_consistent_across_days(world):
    """Running one day later must not rewrite the past: earlier trades are unchanged."""
    cfg, inst, idx = world
    strats = {f"{n}#0": ALL[n]() for n in ALL}
    for k, s in strats.items():
        s.key = k
    prep = bt.prepare(cfg, inst, list(strats.values()), filters=False)
    start = idx[300]
    d1, d2 = idx[450], idx[451]
    a = bt.run(cfg, prep, strats, start, d1, emit_last=True)
    b = bt.run(cfg, prep, strats, start, d2, emit_last=True)
    done_a = a.trades
    pd.testing.assert_frame_equal(done_a, b.trades[b.trades["exit_date"] <= d1].reset_index(drop=True))
    pd.testing.assert_series_equal(a.equity["equity"], b.equity["equity"].iloc[:-1])


def test_pending_orders_fill_or_expire_next_day(world):
    cfg, inst, idx = world
    strats = {f"{n}#0": ALL[n]() for n in ALL}
    for k, s in strats.items():
        s.key = k
    prep = bt.prepare(cfg, inst, list(strats.values()), filters=False)
    start = idx[300]
    for i in range(400, 520):
        a = bt.run(cfg, prep, strats, start, idx[i], emit_last=True)
        if a.pending:
            b = bt.run(cfg, prep, strats, start, idx[i + 1], emit_last=True)
            queued = {o.sym for o in a.pending}
            entered = {p.sym for p in b.positions if p.entry_date == idx[i + 1]} | {
                t.symbol for t in b.trades.itertuples() if t.entry_date == idx[i + 1]}
            assert entered <= queued  # nothing enters that wasn't queued
            return
    pytest.fail("no pending orders generated in window")


def test_sync_persists_and_init_refuses_overwrite(world):
    cfg, inst, idx = world
    meta = paper.init(cfg, idx[300])
    assert meta["start"] == str(idx[300].date())
    with pytest.raises(SystemExit):
        paper.init(cfg, idx[300])
    st = paper.sync(cfg, inst, asof=str(idx[450].date()))
    assert st.last_date == idx[450]
    con = paper._db(cfg)
    assert con.execute("SELECT COUNT(*) FROM equity").fetchone()[0] == len(st.result.equity)
    assert json.loads(con.execute("SELECT value FROM meta WHERE key='last_date'").fetchone()[0]) == str(idx[450].date())
    con.close()
    paper.init(cfg, idx[300], reset=True)  # reset allowed


def test_frozen_selector_is_used(world):
    cfg, inst, idx = world
    (cfg.data_dir / "selector_stats.json").write_text(json.dumps(
        {f"{n}|{r}": -1.0 for n in ALL for r in ("bear", "neutral", "bull")}))
    paper.init(cfg, idx[300], reset=True)
    st = paper.sync(cfg, inst, asof=str(idx[450].date()))
    assert len(st.result.trades) == 0 and not st.result.pending  # every strategy switched off


# ---- momentum sleeve
from trader import momentum as mom  # noqa: E402

MP = mom.MomParams(lookback=126, skip=21, top_n=5, buffer=3)


def test_momentum_refuses_overwrite_but_allows_reset(world):
    cfg, inst, idx = world
    paper.init(cfg, idx[300])
    mm = paper.init_momentum(cfg, idx[300], MP, None)
    assert mm["params"]["top_n"] == 5
    with pytest.raises(SystemExit):
        paper.init_momentum(cfg, idx[300], MP, None)
    paper.init_momentum(cfg, idx[300], MP, None, reset=True)


def test_momentum_only_ledger_syncs_without_swing(world):
    cfg, inst, idx = world
    paper.init_momentum(cfg, idx[300], MP, None)  # no swing ledger at all
    st = paper.sync(cfg, inst, asof=str(idx[450].date()))
    assert st.result is None and st.mom is not None
    assert st.last_date == idx[450] and st.regime in ("bear", "neutral", "bull")


def test_sync_with_no_ledger_at_all_fails_clearly(world):
    cfg, inst, idx = world
    with pytest.raises(SystemExit):
        paper.sync(cfg, inst, asof=str(idx[450].date()))


def test_drop_swing_keeps_momentum(world):
    cfg, inst, idx = world
    paper.init(cfg, idx[300])
    paper.init_momentum(cfg, idx[300], MP, None)
    paper.sync(cfg, inst, asof=str(idx[450].date()))
    paper.drop_swing(cfg)
    con = paper._db(cfg)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not tables & set(paper.SWING_TABLES) and {"mom_equity", "mom_positions"} <= tables
    assert set(paper._meta(con)) == {"momentum"}
    con.close()
    st = paper.sync(cfg, inst, asof=str(idx[460].date()))
    assert st.result is None and st.mom is not None


def test_swing_reset_does_not_touch_momentum(world):
    cfg, inst, idx = world
    paper.init(cfg, idx[300])
    paper.init_momentum(cfg, idx[300], MP, None)
    before = paper.sync(cfg, inst, asof=str(idx[450].date())).mom.result.equity
    paper.init(cfg, idx[310], reset=True)  # restart swing only
    after = paper.sync(cfg, inst, asof=str(idx[450].date())).mom.result.equity
    pd.testing.assert_frame_equal(before, after)


def test_sync_persists_momentum_sleeve(world):
    cfg, inst, idx = world
    paper.init(cfg, idx[300])
    paper.init_momentum(cfg, idx[300], MP, None)
    st = paper.sync(cfg, inst, asof=str(idx[500].date()))
    assert st.mom is not None and st.mom.last_date == idx[500]
    con = paper._db(cfg)
    assert con.execute("SELECT COUNT(*) FROM mom_equity").fetchone()[0] == len(st.mom.result.equity)
    assert con.execute("SELECT COUNT(*) FROM mom_positions").fetchone()[0] == len(st.mom.result.positions)
    con.close()


def test_swing_only_ledger_has_no_momentum(world):
    cfg, inst, idx = world
    paper.init(cfg, idx[300])
    assert paper.sync(cfg, inst, asof=str(idx[450].date())).mom is None


def test_momentum_replay_never_rewrites_history_and_fills_only_queued(world):
    cfg, inst, idx = world
    prep = mom.prepare(cfg, inst)
    start = idx[300]
    # pick a month-end signal day so there are queued buys
    d = next(i for i in range(400, 600) if prep.rebal[i] and not prep.mkt[i] == 0)
    a = mom.run(cfg, prep, MP, start, idx[d], emit_last=True)
    b = mom.run(cfg, prep, MP, start, idx[d + 1], emit_last=True)
    assert a.pending_buys, "expected queued buys on a rebalance day"
    pd.testing.assert_series_equal(a.equity["equity"], b.equity["equity"].iloc[:-1])
    queued = {prep.syms[si] for si, _ in a.pending_buys}
    entered = {prep.syms[si] for si, q in b.positions.items() if q["d"] == d + 1} | {
        t.symbol for t in b.trades.itertuples() if t.entry_date == idx[d + 1]}
    assert entered <= queued
