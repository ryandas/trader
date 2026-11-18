"""Fixed evaluation harness for research candidates.

GATES ARE FIXED HERE. A research run must never edit this file to make a candidate pass.

Rotation candidates are walk-forwarded (3y in-sample / 1y out-of-sample, grid point chosen by
in-sample Sharpe) on the liquid-top-100 universe at INR 5,000 with the real cost model, and compared
with controls (index, equal-weight basket, random picks, default momentum). Passing only earns a
forward paper sleeve; it is not evidence of an edge.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import backtest as bt
from .. import momentum as mom
from .. import outputs
from .. import walkforward as wf
from ..config import Config
from ..data import fundamentals
from ..metrics import summarize
from . import dsr, registry

EVAL_CAPITAL = 5000.0
# Harness v3 (2026-11-18, user approved): the account is funded with INR 5,000 plus EVAL_CONTRIBUTION at every month-end, and
# every walk-forward window is a FRESH START (5,000 + deposits for one year), i.e. the first year of a new small account.
# Returns are time-weighted (deposits are not profit). The gate formulas below are unchanged; only the account they run on is.
EVAL_CONTRIBUTION = 5000.0
PRIMARY_LIQUID_TOP = 100
# Informational account sizes, reported next to the gate run (which stays at EVAL_CAPITAL):
# 25k is about where monthly INR 5,000 top-ups take the account in five months (same monthly top-up on top); 100k asks whether the
# idea has merit once the fixed INR 15.34 DP sell charge and whole-share rounding stop dominating.
PROFILE_CAPITALS = (25_000.0, 100_000.0)
RANDOM_SEEDS = 20
LOOKAHEAD_CUTS = 5
# Harness v2 (2026-11-18): every walk-forward window (in-sample and out-of-sample, candidate and controls) starts with an
# initial rebalance, so slow cadences are not penalised for idling in cash at the start of each window. v1 trials lack the
# "harness" field in their recorded metrics.
# Harness v4 (2026-11-18, user asked to fix survivorship bias): the universe is POINT-IN-TIME NIFTY 500 membership (newest dated
# snapshot of NSE's list on or before each day, data/membership) instead of today's constituents. Gate formulas and thresholds are
# unchanged; the equal-weight basket control is built from the same point-in-time universe. Remaining bias: see data/membership.py.
PIT = True
HARNESS_VERSION = "v4-pit-contrib-fresh-start"
WARM_START = True

# ---- gates (fixed) ----
DSR_MIN = 0.95
MAX_ANNUAL_CHARGES_PCT = 3.0
MAX_CORRELATION = 0.9
MIN_FOLD_WIN_SHARE = 2 / 3  # of OOS years must beat the index (4 of 6)


@dataclass
class EvalResult:
    slug: str
    verdict: str  # PASS | FAIL | FORWARD_ONLY
    gates: dict = field(default_factory=dict)  # name -> {"ok": bool, "detail": str}
    metrics: dict = field(default_factory=dict)
    chosen_params: dict = field(default_factory=dict)
    summary_md: str = ""


def _eval_cfg(cfg: Config) -> Config:
    return cfg.model_copy(update={"capital": EVAL_CAPITAL})


def grid_params(m: dict, base: mom.MomParams | None = None) -> list[mom.MomParams]:
    base = base or mom.MomParams(top_n=10, buffer=10)
    out = []
    for point in m["grid"]:
        eng, rp = registry.split_params(point)
        out.append(mom.MomParams(**{
            "lookback": base.lookback, "skip": base.skip, "top_n": base.top_n, "buffer": base.buffer,
            "bear_exit": base.bear_exit, **eng, "ranker": m["slug"], "ranker_params": rp,
        }))
    return out


def lookahead_guard(prep: mom.MomPrep, p: mom.MomParams, seed: int = 0) -> tuple[bool, str]:
    """Score on the full history, then on history cut at random dates: rows up to each cut must match.
    A score that peeks at the future differs as soon as the future is removed."""
    full = prep.ranker_score(p)
    n = len(prep.dates)
    if full.shape != prep.c.shape:
        return False, f"score shape {full.shape} != {prep.c.shape}"
    rng = np.random.default_rng(seed)
    cuts = sorted(int(x) for x in rng.integers(min(300, n // 2), n - 2, size=LOOKAHEAD_CUTS))
    for t in cuts:
        part = mom.truncate(prep, t).ranker_score(p)  # fresh prep: no cache
        if not np.allclose(full[: t + 1], part, rtol=1e-9, atol=1e-12, equal_nan=True):
            bad = int(np.nonzero(~np.isclose(full[: t + 1], part, rtol=1e-9, atol=1e-12, equal_nan=True).all(axis=1))[0][0])
            return False, f"score changes when history is cut at {prep.dates[t].date()} (first differing row {prep.dates[bad].date()}): lookahead"
    return True, f"identical on {LOOKAHEAD_CUTS} truncations"


def _chain_windows(cfg: Config, prep: mom.MomPrep, p: mom.MomParams) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run `p` on each OOS window (no tuning) and chain the equity curves."""
    eqs, trs = [], []
    for _, _, oos_s, oos_e in wf.fold_windows(prep.dates):
        r = mom.run(cfg, prep, p, oos_s, oos_e, warm_start=WARM_START, contribution=EVAL_CONTRIBUTION)
        if len(r.equity):
            eqs.append(r.equity)
            trs.append(r.trades)
    return wf._chain(eqs, cfg.capital), (pd.concat(trs, ignore_index=True) if trs else pd.DataFrame())


def _basket_equity(prep: mom.MomPrep, index: pd.DatetimeIndex, capital: float) -> pd.DataFrame:
    """Equal-weight, daily-rebalanced basket of the universe's liquid names (no costs): the survivorship control."""
    ret = prep.close_df.pct_change().to_numpy()
    held = np.vstack([np.zeros((1, prep.liquid.shape[1]), dtype=bool), prep.liquid[:-1]])  # liquid at the prior close
    masked = np.where(held, ret, np.nan)
    cnt = np.isfinite(masked).sum(axis=1)
    daily = np.where(cnt > 0, np.nansum(masked, axis=1) / np.maximum(cnt, 1), 0.0)
    s = pd.Series(np.nan_to_num(daily), index=prep.dates).reindex(index).fillna(0.0)
    eq = capital * (1 + s).cumprod()
    return pd.DataFrame({"equity": eq, "invested": 1.0})


def _cagr(eq: pd.DataFrame) -> float:
    v = summarize(eq, pd.DataFrame())["cagr_pct"]
    return float("nan") if v is None else float(v)


def _active_candidate_curves(cfg: Config, exclude: str) -> dict[str, pd.Series]:
    from .. import paper

    out = {}
    for slug, e in paper.candidate_entries(cfg).items():
        if slug != exclude and e.get("active", True):
            curve = outputs.get("research-eval", slug, "oos_equity")
            if curve is not None:
                out[slug] = curve["equity"]
    return out


def _corr(a: pd.Series, b: pd.Series) -> float:
    ra, rb = a.pct_change().dropna(), b.pct_change().dropna()
    idx = ra.index.intersection(rb.index)
    return float(ra[idx].corr(rb[idx])) if len(idx) > 60 else float("nan")


def _charges_pct(trades: pd.DataFrame, folds: pd.DataFrame) -> float:
    """Charges per year as a share of the money actually in the account (average value x years, summed over the fresh-start
    years), since deposits make the account grow during each year."""
    base = float((folds["avg_value"] * folds["days"] / 365.25).sum())
    return round(100 * float(trades["costs"].sum()) / base, 2) if len(trades) and base > 0 else 0.0


def capital_profile(cfg: Config, prep: mom.MomPrep, params: list[mom.MomParams], capital: float) -> dict:
    """Walk-forward the same grid at another account size and compare with the index and the basket.
    Informational only: it never decides the verdict."""
    ccfg = cfg.model_copy(update={"capital": capital})
    w = mom.walk_forward(ccfg, prep, params, warm_start=WARM_START, contribution=EVAL_CONTRIBUTION)
    folds = pd.DataFrame(w["folds"])
    mt = summarize(w["equity"], w["trades"], bt.load_benchmark(cfg))
    basket = _cagr(_basket_equity(prep, w["equity"].index, capital))
    need = max(1, round(MIN_FOLD_WIN_SHARE * len(folds)))
    wins = int((folds["oos_return_pct"] > folds["bench_return_pct"]).sum())
    grid_ok = all(_cagr(g) > mt.get("benchmark_cagr_pct", np.inf) for g in w["grid"].values())
    return {
        "capital": capital, "cagr_pct": mt["cagr_pct"], "benchmark_cagr_pct": mt.get("benchmark_cagr_pct"),
        "basket_cagr_pct": round(basket, 2), "max_drawdown_pct": mt["max_drawdown_pct"],
        "exposure_pct": mt["exposure_pct"], "trades": mt["trades"], "folds_won": wins, "folds": len(folds),
        "charges_pct_per_year": _charges_pct(w["trades"], folds),
        "beats_index_and_basket": bool(mt["cagr_pct"] > mt.get("benchmark_cagr_pct", np.inf) and mt["cagr_pct"] > basket),
        "beats_index_most_years": wins >= need, "every_grid_point_beats_index": grid_ok,
    }


def _add_money_weighted(prep: mom.MomPrep, folds: pd.DataFrame) -> pd.DataFrame:
    """Per fresh-start year: what the candidate's account ended at versus the same deposits put into the index and into the
    equal-weight basket on the same dates. Informational (the gates stay time-weighted)."""
    folds = folds.copy()
    basket = _basket_equity(prep, prep.dates, 1.0)["equity"]
    vals = []
    for (_, _, oos_s, oos_e), _row in zip(wf.fold_windows(prep.dates), folds.itertuples()):
        dep = mom.deposit_schedule(prep, oos_s, oos_e, EVAL_CAPITAL, EVAL_CONTRIBUTION)
        vals.append(mom.matched_value(basket, dep))
    folds["basket_end_value"] = np.round(vals, 2)
    return folds


def _gate(ok: bool, detail: str) -> dict:
    return {"ok": bool(ok), "detail": detail}


def evaluate(cfg: Config, instruments: pd.DataFrame, slug: str, record: bool = True, counted: bool = True) -> EvalResult:
    m = registry.meta(slug)
    sha = registry.sha256(slug)
    ecfg = _eval_cfg(cfg)
    params = grid_params(m)
    prep = mom.prepare(ecfg, instruments, PRIMARY_LIQUID_TOP, PIT)

    gates: dict[str, dict] = {}
    ok_look, why = lookahead_guard(prep, params[0])
    for p in params[1:]:
        o, w = lookahead_guard(prep, p)
        ok_look, why = ok_look and o, why if o else w
    gates["no_lookahead"] = _gate(ok_look, why)
    res = EvalResult(slug, "FAIL", gates)

    if not ok_look:
        return _finish(cfg, res, m, sha, record, counted, "lookahead guard failed; no backtest run")

    if m.get("uses_fundamentals"):
        return _forward_only(cfg, ecfg, prep, params[0], res, m, sha, record, counted)

    # ---- walk-forward (liquid top 100 = primary) ----
    w = mom.walk_forward(ecfg, prep, params, warm_start=WARM_START, contribution=EVAL_CONTRIBUTION)
    folds = pd.DataFrame(w["folds"])
    eq, trades = w["equity"], w["trades"]
    bench = bt.load_benchmark(cfg)
    mt = summarize(eq, trades, bench)
    cand_cagr, bench_cagr = mt["cagr_pct"], mt.get("benchmark_cagr_pct")
    ew = _basket_equity(prep, eq.index, EVAL_CAPITAL)
    ew_cagr = _cagr(ew)
    ref_p = mom.MomParams(top_n=params[0].top_n, buffer=params[0].buffer, bear_exit=params[0].bear_exit,
                          rebalance=params[0].rebalance)
    rnd = []
    for seed in range(RANDOM_SEEDS):
        rp = mom.MomParams(**{**ref_p.__dict__, "random_seed": seed})
        rnd.append(_cagr(_chain_windows(ecfg, prep, rp)[0]))
    rnd_med = float(np.nanmedian(rnd))
    ref_eq, _ = _chain_windows(ecfg, prep, mom.MomParams(top_n=10, buffer=10))
    ref_cagr = _cagr(ref_eq)

    # full universe: reported only
    prep_full = mom.prepare(ecfg, instruments, None, PIT)
    wf_full = mom.walk_forward(ecfg, prep_full, params, warm_start=WARM_START, contribution=EVAL_CONTRIBUTION)
    full_cagr = summarize(wf_full["equity"], wf_full["trades"], bench)["cagr_pct"]

    n_trials = registry.trial_count(cfg) + (1 if counted else 0)
    past = registry.trial_sharpes(cfg)
    r = eq["equity"].pct_change().dropna()
    daily_sharpe = float(r.mean() / r.std()) if r.std() > 0 else 0.0
    dsr_v = dsr.deflated_sharpe(r, n_trials, past)

    charges_pct = _charges_pct(trades, folds)
    folds = _add_money_weighted(prep, folds)
    wins = int((folds["oos_return_pct"] > folds["bench_return_pct"]).sum())
    need = max(1, round(MIN_FOLD_WIN_SHARE * len(folds)))
    grid_cagr = {lab: _cagr(g) for lab, g in w["grid"].items()}
    grid_bad = {lab: c for lab, c in grid_cagr.items() if not (c > bench_cagr)}

    gates["beats_index_and_basket"] = _gate(
        cand_cagr > bench_cagr and cand_cagr > ew_cagr,
        f"candidate {cand_cagr}% vs index {bench_cagr}% vs equal-weight basket {ew_cagr:.1f}%")
    gates["beats_index_most_years"] = _gate(wins >= need, f"{wins} of {len(folds)} OOS years beat the index (need {need})")
    gates["beats_random_picks"] = _gate(cand_cagr > rnd_med, f"candidate {cand_cagr}% vs median random-pick control {rnd_med:.1f}% ({RANDOM_SEEDS} seeds)")
    gates["robust_across_grid"] = _gate(not grid_bad, "every grid point beats the index" if not grid_bad
                                        else "below index: " + ", ".join(f"{k} {v:.1f}%" for k, v in grid_bad.items()))
    gates["deflated_sharpe"] = _gate(dsr_v >= DSR_MIN, f"DSR {dsr_v:.3f} (need {DSR_MIN}) after {n_trials} counted trials")
    gates["charges_under_3pct"] = _gate(charges_pct < MAX_ANNUAL_CHARGES_PCT, f"average annual charges {charges_pct:.2f}% of the money in the account")
    corrs = {"momentum_default": _corr(eq["equity"], ref_eq["equity"])}
    corrs |= {s: _corr(eq["equity"], c) for s, c in _active_candidate_curves(cfg, slug).items()}
    worst = max(corrs.items(), key=lambda kv: -1 if np.isnan(kv[1]) else kv[1])
    gates["not_a_duplicate"] = _gate(not (worst[1] >= MAX_CORRELATION),
                                     "daily-return correlation " + ", ".join(f"{k} {v:.2f}" for k, v in corrs.items()))

    res.metrics = {
        "harness": HARNESS_VERSION,
        "cagr_pct": cand_cagr, "benchmark_cagr_pct": bench_cagr, "basket_cagr_pct": round(ew_cagr, 2),
        "random_median_cagr_pct": round(rnd_med, 2), "momentum_default_cagr_pct": round(ref_cagr, 2),
        "full_universe_cagr_pct": full_cagr, "max_drawdown_pct": mt["max_drawdown_pct"], "sharpe": mt["sharpe"],
        "daily_sharpe": daily_sharpe, "dsr": round(dsr_v, 4), "n_trials": n_trials, "charges_pct_per_year": round(charges_pct, 2),
        "trades": mt["trades"], "folds_won": wins, "folds": len(folds), "grid_cagr": grid_cagr, "correlations": corrs,
        "oos_start": mt["start"], "oos_end": mt["end"],
        "account": f"{EVAL_CAPITAL:,.0f} + {EVAL_CONTRIBUTION:,.0f} each month-end, fresh start every OOS year",
        "money_weighted": {"candidate_end_value": round(float(folds["end_value"].sum()), 2),
                           "index_end_value": round(float(folds["index_end_value"].sum()), 2),
                           "basket_end_value": round(float(folds["basket_end_value"].sum()), 2),
                           "paid_in": round(float(folds["deposited"].sum()), 2)},
    }
    profiles = {}
    for cap in PROFILE_CAPITALS:
        profiles[f"{int(cap):,}"] = capital_profile(cfg, prep, params, cap)
    res.metrics["by_capital"] = profiles
    big = profiles[f"{int(PROFILE_CAPITALS[-1]):,}"]
    res.metrics["merit_at_100k"] = bool(big["beats_index_and_basket"] and big["beats_index_most_years"]
                                        and big["every_grid_point_beats_index"])
    gi = int(folds["grid_index"].iloc[-1])  # grid point chosen on the most recent in-sample window
    res.chosen_params = {"grid_index": gi, "point": m["grid"][gi], "label": params[gi].label()}
    res.verdict = "PASS" if all(g["ok"] for g in gates.values()) else "FAIL"
    return _finish(cfg, res, m, sha, record, counted, "", folds=folds, eq=eq)


def _forward_only(cfg, ecfg, prep, p, res: EvalResult, m: dict, sha: str, record: bool, counted: bool) -> EvalResult:
    """Fundamentals candidates have no point-in-time history to backtest: only sanity checks, then forward paper."""
    from .. import paper

    gates = res.gates
    snaps = len(fundamentals.snapshot_dates())
    gates["has_fundamentals_snapshots"] = _gate(snaps > 0, f"{snaps} snapshot(s) on file")
    # cost estimate: share of capital lost to charges per year for a given monthly turnover of the book
    from ..costs import trade_costs

    pos_val = EVAL_CAPITAL / p.top_n
    sell_cost = trade_costs("sell", pos_val, ecfg.costs)
    est = {f"{int(t * 100)}%_monthly_turnover": round(100 * 12 * t * p.top_n * (sell_cost + trade_costs("buy", pos_val, ecfg.costs)) / EVAL_CAPITAL, 2)
           for t in (0.1, 0.25, 0.5)}
    last = prep.ranker_score(p)
    li = int(np.nonzero(np.isfinite(last).any(axis=1))[0][-1]) if np.isfinite(last).any() else -1
    corr = float("nan")
    if li >= 0:
        base = prep.score(126, 21)[li]
        ok = np.isfinite(last[li]) & np.isfinite(base) & prep.liquid[li]
        if ok.sum() > 10:
            corr = float(pd.Series(last[li][ok]).rank().corr(pd.Series(base[ok]).rank()))
    gates["not_a_duplicate"] = _gate(not (corr >= MAX_CORRELATION),
                                     f"rank correlation with the momentum score on the latest scored day: {corr:.2f}" if not np.isnan(corr)
                                     else "no scored day yet to compare")
    res.metrics = {"estimated_annual_charges_pct": est, "snapshots": snaps}
    res.chosen_params = {"grid_index": 0, "point": m["grid"][0], "label": p.label()}
    res.verdict = "FORWARD_ONLY" if all(g["ok"] for g in gates.values()) else "FAIL"
    return _finish(cfg, res, m, sha, record, counted, "no point-in-time fundamentals history: forward paper only")


def _finish(cfg: Config, res: EvalResult, m: dict, sha: str, record: bool, counted: bool, note: str,
            folds: pd.DataFrame | None = None, eq: pd.DataFrame | None = None) -> EvalResult:
    res.summary_md = render_summary(res, m, note, folds)
    items: dict = {"summary": res.summary_md}
    if folds is not None:
        items["folds"] = folds
    if eq is not None:
        items["oos_equity"] = eq
    outputs.save("research-eval", res.slug, items, {"verdict": res.verdict, "recorded": record, "counted": counted})
    if record:
        tid = registry.record_trial(cfg, res.slug, sha, m, {**res.metrics, "chosen": res.chosen_params, "note": note},
                                    {k: v for k, v in res.gates.items()}, res.verdict, counted)
        res.metrics["trial_id"] = tid
    return res


def render_summary(res: EvalResult, m: dict, note: str, folds: pd.DataFrame | None) -> str:
    lines = [f"# Research evaluation: {res.slug}", "", f"**Verdict: {res.verdict}**" + (f" ({note})" if note else ""), "",
             f"- Hypothesis: {m['hypothesis']}", f"- Source: {m['source']}", f"- Grid: `{m['grid']}`", ""]
    lines += ["## Gates", "| gate | result | detail |", "|---|---|---|"]
    lines += [f"| {k} | {'pass' if g['ok'] else 'FAIL'} | {g['detail']} |" for k, g in res.gates.items()]
    prof = res.metrics.get("by_capital")
    if prof:
        g = {"cagr_pct": res.metrics["cagr_pct"], "benchmark_cagr_pct": res.metrics["benchmark_cagr_pct"],
             "basket_cagr_pct": res.metrics["basket_cagr_pct"], "max_drawdown_pct": res.metrics["max_drawdown_pct"],
             "exposure_pct": None, "charges_pct_per_year": res.metrics["charges_pct_per_year"], "trades": res.metrics["trades"],
             "folds_won": res.metrics["folds_won"], "folds": res.metrics["folds"], "capital": EVAL_CAPITAL}
        rows = [("5,000 (gate run)", g)] + list(prof.items())
        lines += ["", "## By starting account size (same INR 5,000 monthly deposit and fresh-start years; informational, only the 5,000 run decides the verdict)",
                  "| account INR | candidate CAGR % | index % | basket % | max DD % | charges %/yr | trades | years beating index |",
                  "|---|---|---|---|---|---|---|---|"]
        lines += [f"| {k} | {v['cagr_pct']} | {v['benchmark_cagr_pct']} | {v['basket_cagr_pct']} | {v['max_drawdown_pct']} "
                  f"| {v['charges_pct_per_year']} | {v['trades']} | {v['folds_won']}/{v['folds']} |" for k, v in rows]
        lines += ["", f"Merit at 100,000 (beats index and basket, most years, every grid point): "
                      f"**{'yes' if res.metrics.get('merit_at_100k') else 'no'}**"
                      + ("" if res.verdict == "PASS" or not res.metrics.get("merit_at_100k") else
                         " - the idea may work but is cost- or affordability-limited at 5,000; consider a variant (fewer slots, "
                         "affordable-price filter) as a new trial.")]
    if res.metrics:
        lines += ["", "## Metrics", *[f"- {k}: {v}" for k, v in res.metrics.items() if k != "by_capital"]]
    if folds is not None:
        lines += ["", "## OOS folds", folds.to_markdown(index=False) if hasattr(folds, "to_markdown") and _has_tabulate() else folds.to_string(index=False)]
    lines += ["", "> A backtest verdict is permission to paper trade, not evidence of an edge. Universe = NIFTY 500 members per dated snapshots "
              "(survivorship bias, reduced by point-in-time membership but not removed); only forward paper results count."]
    return "\n".join(lines) + "\n"


def _has_tabulate() -> bool:
    try:
        import tabulate  # noqa: F401
        return True
    except ImportError:
        return False
