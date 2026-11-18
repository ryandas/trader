import importlib
import math
import sys
import types

import numpy as np
import pandas as pd
import pytest

from trader import momentum as mom
from trader import paper
from trader.config import Config
from trader.data import fundamentals as fund
from trader.data import store
from trader.research import candidates as cand_pkg
from trader.research import dsr, evaluate, registry
from test_momentum import world as mom_world
from test_strategies_backtest import synth

P = mom.MomParams(lookback=126, skip=21, top_n=5, buffer=3)


# ---------------------------------------------------------------- deflated Sharpe
def test_dsr_single_trial_is_probabilistic_sharpe():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.1, 1.0, 400))
    sr = r.mean() / r.std()
    got = dsr.deflated_sharpe(r, n_trials=1)
    assert math.isclose(got, dsr._N.cdf(sr * math.sqrt(399)), abs_tol=0.03)  # normal returns: skew/kurt terms ~ 0


def test_dsr_falls_as_trials_grow_and_zero_edge_is_not_credited():
    rng = np.random.default_rng(1)
    good = pd.Series(rng.normal(0.08, 1.0, 750))
    assert dsr.deflated_sharpe(good, 1) > dsr.deflated_sharpe(good, 50) > dsr.deflated_sharpe(good, 5000)
    flat = pd.Series(rng.normal(0.0, 1.0, 750))
    assert dsr.deflated_sharpe(flat, 20) < 0.5


# ---------------------------------------------------------------- engine plumbing
def _as_candidate(monkeypatch, fn, slug="tmpcand"):
    monkeypatch.setattr(registry, "load", lambda s: types.SimpleNamespace(score=fn))
    return mom.MomParams(**{**P.__dict__, "ranker": slug})


def test_default_momentum_unchanged_by_new_params(monkeypatch):
    cfg, prep, idx = mom_world(monkeypatch)
    assert P.label() == "lb126-skip21-top5-buf3-bearexit"  # label of the running sleeve is untouched
    base = mom.run(cfg, prep, P, idx[300])
    # a ranker returning exactly the momentum score must reproduce the default run bit for bit
    p2 = _as_candidate(monkeypatch, lambda prep, **k: prep.score(126, 21))
    via = mom.run(cfg, prep, p2, idx[300])
    pd.testing.assert_frame_equal(base.equity, via.equity)
    pd.testing.assert_frame_equal(base.trades, via.trades)


def test_old_meta_without_new_fields_loads_and_json_roundtrip():
    old = {"lookback": 126, "skip": 21, "top_n": 10, "buffer": 10, "bear_exit": True, "random_seed": None}
    assert mom.MomParams(**old).ranker == "momentum"
    p = mom.MomParams(ranker="x", ranker_params=(("window", 252),))
    import json
    from dataclasses import asdict
    assert mom.MomParams(**json.loads(json.dumps(asdict(p)))) == p  # lists from JSON become tuples again


def test_weekly_rebalance_trades_more_often(monkeypatch):
    cfg, prep, idx = mom_world(monkeypatch)
    m = mom.run(cfg, prep, P, idx[300])
    w = mom.run(cfg, prep, mom.MomParams(**{**P.__dict__, "rebalance": "W"}), idx[300])
    assert prep.rebal_w.sum() > prep.rebal.sum()
    assert len(w.trades) >= len(m.trades)


# ---------------------------------------------------------------- lookahead guard
def test_lookahead_guard_passes_honest_and_catches_leaky(monkeypatch):
    cfg, prep, idx = mom_world(monkeypatch)
    honest = _as_candidate(monkeypatch, lambda prep, **k: (prep.close_df / prep.close_df.shift(60) - 1).to_numpy())
    ok, why = evaluate.lookahead_guard(prep, honest)
    assert ok, why
    leaky = _as_candidate(monkeypatch, lambda prep, **k: (prep.close_df.shift(-1) / prep.close_df - 1).to_numpy(), "leaky")
    ok, why = evaluate.lookahead_guard(prep, leaky)
    assert not ok and "lookahead" in why


# ---------------------------------------------------------------- registry
@pytest.fixture
def lab(monkeypatch, tmp_path):
    """Synthetic market + temp data dir + temp candidates dir + temp reports root."""
    frames = {f"S{i}": synth(700, seed=i, drift=0.0005 + 0.0002 * (i % 5)) for i in range(30)}
    frames["NIFTY500"] = synth(700, seed=99, drift=0.0004)
    monkeypatch.setattr(store, "load", lambda d, s: frames.get(s))
    monkeypatch.setattr(Config, "data_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(evaluate, "ROOT", tmp_path)
    monkeypatch.setattr(evaluate, "PIT", False)  # synthetic market has no membership snapshots; tests cover gate logic
    cdir = tmp_path / "cands"
    cdir.mkdir()
    monkeypatch.setattr(registry, "CANDIDATES_DIR", cdir)
    monkeypatch.setattr(cand_pkg, "__path__", [str(cdir)])
    sys.modules.pop("trader.research.candidates.t_leaky", None)
    inst = pd.DataFrame({"symbol": [f"S{i}" for i in range(30)], "sector": "X"})
    return Config(capital=1_000_000), inst, frames["NIFTY500"].index, cdir


def write_cand(cdir, slug, body, grid="[{}]", extra=""):
    (cdir / f"{slug}.py").write_text(
        f'META = {{"slug": "{slug}", "kind": "rotation", "hypothesis": "h", "source": "s", "grid": {grid}{extra}}}\n{body}\n')
    sys.modules.pop(f"trader.research.candidates.{slug}", None)
    importlib.invalidate_caches()  # FileFinder caches dir listings; same-second writes are otherwise missed


def test_registry_is_append_only_and_counts(lab):
    cfg, inst, idx, cdir = lab
    write_cand(cdir, "t_a", "def score(prep, **k):\n    return prep.score(126, 21)")
    m = registry.meta("t_a")
    assert registry.trial_count(cfg) == 0
    registry.record_trial(cfg, "t_a", "sha1", m, {"daily_sharpe": 0.01}, {}, "FAIL")
    registry.record_trial(cfg, "t_a", "sha1", m, {"daily_sharpe": 0.02}, {}, "FAIL", counted=False)  # a recheck
    assert registry.trial_count(cfg) == 1 and registry.trial_sharpes(cfg) == [0.01]
    assert len(registry.recent_trials(cfg)) == 2


def test_bad_slug_and_bad_grid_rejected(lab):
    cfg, inst, idx, cdir = lab
    with pytest.raises(SystemExit):
        registry.check_slug("../evil")
    write_cand(cdir, "t_big", "def score(prep, **k):\n    return prep.score(126, 21)", grid="[{}, {}, {}, {}, {}]")
    with pytest.raises(SystemExit):
        registry.meta("t_big")
    write_cand(cdir, "t_fund2", "def score(prep, **k):\n    return prep.score(126, 21)", grid="[{}, {}]",
               extra=', "uses_fundamentals": True')
    with pytest.raises(SystemExit):
        registry.meta("t_fund2")


def test_evaluate_fails_a_leaky_candidate_without_backtesting(lab):
    cfg, inst, idx, cdir = lab
    write_cand(cdir, "t_leaky", "def score(prep, **k):\n    return (prep.close_df.shift(-1) / prep.close_df - 1).to_numpy()")
    res = evaluate.evaluate(cfg, inst, "t_leaky")
    assert res.verdict == "FAIL" and not res.gates["no_lookahead"]["ok"]
    assert "beats_index_and_basket" not in res.gates  # nothing was backtested
    assert registry.trial_count(cfg) == 1  # but the attempt is counted


# ---------------------------------------------------------------- fundamentals
def test_fundamentals_asof_and_panel_never_use_later_snapshots(tmp_path):
    d = tmp_path / "f"
    d.mkdir()
    for day, roe in (("2026-01-10", 0.10), ("2026-03-10", 0.30)):
        pd.DataFrame({"roe": [roe, roe]}, index=pd.Index(["A", "B"], name="symbol")).to_parquet(d / f"{day}.parquet")
    assert fund.asof(d, "2026-01-09").empty
    assert fund.asof(d, "2026-03-09")["roe"].iloc[0] == 0.10
    assert fund.asof(d, "2026-03-10")["roe"].iloc[0] == 0.30
    dates = pd.bdate_range("2026-01-05", "2026-04-01")
    pan = fund.panel(d, dates, ["A", "B", "C"], "roe")
    assert np.isnan(pan[dates < "2026-01-10"]).all()  # nothing known before the first snapshot
    assert (pan[(dates >= "2026-01-10") & (dates < "2026-03-10"), 0] == 0.10).all()
    assert (pan[dates >= "2026-03-10", 0] == 0.30).all()
    assert np.isnan(pan[:, 2]).all()  # unknown symbol


# ---------------------------------------------------------------- promotion into the ledger
def _ledger(lab, slug, body, extra=""):
    cfg, inst, idx, cdir = lab
    write_cand(cdir, slug, body, extra=extra)
    paper.init_momentum(cfg, idx[300], mom.MomParams(top_n=5, buffer=3), None)
    return cfg, inst, idx, cdir


HONEST = "def score(prep, **k):\n    return (prep.close_df / prep.close_df.shift(60) - 1).to_numpy()"


def test_promote_requires_passing_trial_then_sync_runs_sleeve_and_leaves_momentum_alone(lab):
    cfg, inst, idx, cdir = _ledger(lab, "t_ok", HONEST)
    with pytest.raises(SystemExit):  # never evaluated
        paper.promote_candidate(cfg, inst, "t_ok", idx[300])
    m, sha = registry.meta("t_ok"), registry.sha256("t_ok")
    registry.record_trial(cfg, "t_ok", sha, m, {"chosen": {"grid_index": 0}}, {}, "FAIL")
    with pytest.raises(SystemExit):  # failed trial
        paper.promote_candidate(cfg, inst, "t_ok", idx[300])
    before = paper.sync(cfg, inst, asof=str(idx[450].date()))
    registry.record_trial(cfg, "t_ok", sha, m, {"chosen": {"grid_index": 0}}, {}, "PASS")
    e = paper.promote_candidate(cfg, inst, "t_ok", idx[300])
    assert e["tier"] == "backtest_pass" and e["active"]
    st = paper.sync(cfg, inst, asof=str(idx[450].date()))
    assert "t_ok" in st.cands and not st.cand_errors
    pd.testing.assert_frame_equal(before.mom.result.equity, st.mom.result.equity)  # momentum sleeve untouched
    import sqlite3
    con = sqlite3.connect(cfg.data_dir / "paper.db")
    assert con.execute("select count(*) from cand_equity where sleeve='t_ok'").fetchone()[0] > 0
    assert con.execute("select count(*) from mom_equity").fetchone()[0] == len(before.mom.result.equity)
    con.close()
    with pytest.raises(SystemExit):  # already active
        paper.promote_candidate(cfg, inst, "t_ok", idx[300])
    paper.retire_candidate(cfg, "t_ok")
    assert paper.sync(cfg, inst, asof=str(idx[450].date())).cands == {}


def test_code_freeze_refuses_changed_candidate(lab):
    cfg, inst, idx, cdir = _ledger(lab, "t_frz", HONEST)
    registry.record_trial(cfg, "t_frz", registry.sha256("t_frz"), registry.meta("t_frz"),
                          {"chosen": {"grid_index": 0}}, {}, "PASS")
    paper.promote_candidate(cfg, inst, "t_frz", idx[300])
    write_cand(cdir, "t_frz", HONEST.replace("60", "90"))  # logic edited after promotion
    st = paper.sync(cfg, inst, asof=str(idx[450].date()))
    assert st.cands == {} and "code freeze" in st.cand_errors["t_frz"]


def test_candidate_cap(lab, monkeypatch):
    cfg, inst, idx, cdir = _ledger(lab, "t_c0", HONEST)
    monkeypatch.setattr(paper, "MAX_ACTIVE_CANDIDATES", 1)
    for s in ("t_c0", "t_c1"):
        write_cand(cdir, s, HONEST)
        registry.record_trial(cfg, s, registry.sha256(s), registry.meta(s), {"chosen": {"grid_index": 0}}, {}, "PASS")
    paper.promote_candidate(cfg, inst, "t_c0", idx[300])
    with pytest.raises(SystemExit, match="max"):
        paper.promote_candidate(cfg, inst, "t_c1", idx[300])


def test_fundamentals_candidate_is_forward_only_never_pass(lab):
    cfg, inst, idx, cdir = lab
    fdir = cfg.data_dir / "fundamentals"
    fdir.mkdir()
    pd.DataFrame({"roe": np.linspace(0.05, 0.4, 30)}, index=pd.Index([f"S{i}" for i in range(30)], name="symbol")
                 ).to_parquet(fdir / f"{idx[400].date()}.parquet")
    paper.init_momentum(cfg, idx[300], mom.MomParams(top_n=5, buffer=3), None)
    write_cand(cdir, "t_fund", 'def score(prep, **k):\n    return prep.fund_panel("roe")', extra=', "uses_fundamentals": True')
    res = evaluate.evaluate(cfg, inst, "t_fund")
    assert res.verdict == "FORWARD_ONLY" and "beats_index_and_basket" not in res.gates  # no backtest gates applied
    e = paper.promote_candidate(cfg, inst, "t_fund", idx[300])
    assert e["tier"] == "forward_only"
    st = paper.sync(cfg, inst, asof=str(idx[450].date()))
    assert st.cands["t_fund"].tier == "forward_only"


def test_capital_profile_costs_bite_small_accounts(monkeypatch):
    frames = {f"S{i}": synth(1700, seed=i, drift=0.0005 + 0.0002 * (i % 5)) for i in range(30)}
    frames["NIFTY500"] = synth(1700, seed=99, drift=0.0004)
    monkeypatch.setattr(store, "load", lambda d, s: frames.get(s))
    inst = pd.DataFrame({"symbol": [f"S{i}" for i in range(30)], "sector": "X"})
    cfg = Config(capital=5000)
    prep = mom.prepare(cfg, inst, 100)
    params = [mom.MomParams(top_n=10, buffer=10)]
    small = evaluate.capital_profile(cfg, prep, params, 5_000)
    big = evaluate.capital_profile(cfg, prep, params, 100_000)
    assert small["capital"] == 5_000 and big["capital"] == 100_000
    assert small["charges_pct_per_year"] > big["charges_pct_per_year"]  # fixed DP charge hurts small accounts more
    assert set(big) >= {"cagr_pct", "benchmark_cagr_pct", "basket_cagr_pct", "beats_index_and_basket", "folds_won"}


def test_quarterly_and_semiannual_masks(monkeypatch):
    cfg, prep, idx = mom_world(monkeypatch)
    months = lambda mask: {(idx[i].year, idx[i].month) for i in np.nonzero(mask[:-1])[0]}  # noqa: E731
    assert {m for _, m in months(prep.rebal_q)} <= {3, 6, 9, 12}
    assert {m for _, m in months(prep.rebal_s)} <= {6, 12}
    assert prep.rebal.sum() > prep.rebal_q.sum() > prep.rebal_s.sum() > 0
    assert (prep.rebal_s <= prep.rebal_q).all() and (prep.rebal_q <= prep.rebal).all()  # nested: S in Q in M
    # a semi-annual book trades only on the first session after a Jun/Dec month end
    r = mom.run(cfg, prep, mom.MomParams(**{**P.__dict__, "rebalance": "S"}), idx[300])
    firsts = {idx[i + 1] for i in np.nonzero(prep.rebal_s[:-1])[0]}
    entries = set(r.trades["entry_date"]) | {idx[q["d"]] for q in r.positions.values()}
    assert len(entries) > 0 and entries <= firsts
    with pytest.raises(ValueError):
        mom.MomParams(rebalance="X")


def test_warm_start_invests_at_window_start_and_is_off_by_default(monkeypatch):
    cfg, prep, idx = mom_world(monkeypatch)
    semi = mom.MomParams(**{**P.__dict__, "rebalance": "S"})
    # a window opening in the middle of a half-year: no signal is due for months
    ok = [i for i in range(300, 600) if prep.mkt[i] != 0 and prep.above200[i].sum() >= 5 and not prep.rebal_s[i - 1:i + 35].any()]
    assert ok, "synthetic world has no suitable non-bear start"
    start = idx[ok[0]]  # not bearish, stocks eligible, and no semi-annual signal due for weeks
    cold = mom.run(cfg, prep, semi, start, idx[-1])
    warm = mom.run(cfg, prep, semi, start, idx[-1], warm_start=True)
    assert cold.equity["invested"].iloc[:30].max() == 0  # idles in cash until its own signal
    assert warm.equity["invested"].iloc[3] > 0.5  # invested within days, like a running account
    # off by default: identical to a plain call, and a monthly cold start is unaffected when a signal is due on day one
    pd.testing.assert_frame_equal(cold.equity, mom.run(cfg, prep, semi, start, idx[-1], warm_start=False).equity)


def test_frog_pan_prefers_smooth_winner_over_jumpy_winner():
    from trader.research.candidates import frog_pan

    n = 320
    idx = pd.bdate_range("2023-01-02", periods=n)
    smooth = 100 * 1.002 ** np.arange(n)
    jumpy_r = np.full(n, -0.0005)
    jumpy_r[10::25] = 0.04
    jumpy = 100 * np.cumprod(1 + jumpy_r)
    loser = 100 * 0.999 ** np.arange(n)
    close = pd.DataFrame({"SMOOTH": smooth, "JUMPY": jumpy, "LOSER": loser}, index=idx)
    prep = type("P", (), {"close_df": close})()
    s = frog_pan.score(prep, lookback=252, skip=21)
    assert np.isnan(s[:200]).all()  # needs the full formation window
    # NB: ID is sign-adjusted, so a smooth LOSER also scores high on the ID rank (known flaw, see journal); test winners only
    assert s[-1, 0] > s[-1, 1]
    assert s[-1, 2] < s[-1, 0]


def test_int_mom_ignores_recent_months():
    from trader.research.candidates import int_mom

    n = 300
    idx = pd.bdate_range("2023-01-02", periods=n)
    old_winner = np.concatenate([np.linspace(100, 200, 150), np.linspace(200, 100, 150)])  # up early, crashes recently
    recent_winner = np.concatenate([np.full(150, 100.0), np.linspace(100, 300, 150)])
    prep = type("P", (), {"close_df": pd.DataFrame({"OLD": old_winner, "NEW": recent_winner}, index=idx)})()
    s = int_mom.score(prep, far=252, near=126)
    assert np.isnan(s[:251]).all()
    assert s[-1, 0] > s[-1, 1]  # the early winner outranks the recent one


def test_max_lottery_penalises_a_single_huge_day():
    from trader.research.candidates import max_lottery

    n = 60
    idx = pd.bdate_range("2024-01-01", periods=n)
    calm = 100 * np.cumprod(np.full(n, 1.002))
    r = np.full(n, 0.001)
    r[50] = 0.30  # one lottery-like day
    lotto = 100 * np.cumprod(1 + r)
    prep = type("P", (), {"close_df": pd.DataFrame({"CALM": calm, "LOTTO": lotto}, index=idx)})()
    s = max_lottery.score(prep, window=21, k=5)
    assert np.isnan(s[:20]).all()
    assert s[55, 0] > s[55, 1]  # window still contains the jump
    assert s[45, 1] > s[45, 0]  # before the jump LOTTO has the smaller max return, so it ranks higher: the jump flips it
