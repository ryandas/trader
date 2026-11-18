"""Paper-trading ledger.

The ledger is a deterministic replay of the backtest engine (same fills, costs, sizing and
risk rules) from a fixed start date, using parameters and selector statistics FROZEN at init.
Nothing fitted after the start date can leak into it, so its results are genuine forward
evidence. State is persisted to SQLite (data/paper.db) for reporting and for Claude to read.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime

import numpy as np
import pandas as pd

from . import backtest as bt
from . import momentum as mom
from . import sessions
from . import db, outputs
from .config import Config
from .data import store
from .regime import NAMES
from .selector import Selector
from .strategies import ALL, Strategy


@dataclass
class MomState:
    result: mom.MomResult
    prep: mom.MomPrep
    params: mom.MomParams
    liquid_top: int | None
    start: pd.Timestamp
    capital: float
    last_date: pd.Timestamp
    slug: str = ""  # research candidate slug ("" for the main momentum sleeve)
    tier: str = ""  # candidate tier: "backtest_pass" or "forward_only"
    contribution: float = 0.0  # INR deposited at each month-end close (frozen at init)


@dataclass
class PaperState:
    """Swing fields are None when the swing sleeve is not in the ledger (momentum-only)."""

    result: bt.Result | None
    prep: bt.Prepared | None
    last_date: pd.Timestamp
    regime: str
    start: pd.Timestamp | None
    capital: float | None
    stale: bool
    mom: MomState | None = None
    cands: dict = field(default_factory=dict)  # slug -> MomState for active research candidate sleeves
    cand_errors: dict = field(default_factory=dict)  # slug -> reason the sleeve was not replayed


def _db(cfg: Config) -> db.Con:
    return db.connect()


def _meta(con: db.Con) -> dict:
    return {k: v for k, v in con.execute("SELECT key, value FROM paper_meta").fetchall()}


def _put_meta(con: db.Con, key: str, value) -> None:
    con.execute("INSERT INTO paper_meta (key, value) VALUES (?, CAST(? AS jsonb)) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, json.dumps(value, default=str)))


SWING_TABLES = ("trades", "equity", "positions", "orders")
SWING_KEYS = ("start", "capital", "params", "selector", "created", "last_date", "regime")


def _drop_swing(con: db.Con) -> None:
    for t in SWING_TABLES:
        con.execute(f"DROP TABLE IF EXISTS {t}")
    for k in SWING_KEYS:
        con.execute("DELETE FROM paper_meta WHERE key = ?", (k,))


def drop_swing(cfg: Config) -> None:
    """Remove the swing sleeve from the ledger. The momentum sleeve is untouched."""
    con = _db(cfg)
    with con:
        _drop_swing(con)
    con.close()


def init(cfg: Config, start: pd.Timestamp, reset: bool = False) -> dict:
    """Freeze the fitted parameters and selector stats and start the swing sleeve at `start`."""
    params, sel = outputs.get("walkforward", "", "params"), outputs.get("walkforward", "", "selector_stats")
    if params is None or sel is None:
        raise SystemExit("Run `trader walkforward` first: it stores the params/selector to freeze.")
    con = _db(cfg)
    if "params" in _meta(con) and not reset:
        raise SystemExit("A swing ledger already exists. Use --reset to discard it and start over.")
    meta = {
        "start": str(start.date()),
        "capital": cfg.capital,
        "params": params,
        "selector": sel,
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    with con:
        _drop_swing(con)  # momentum tables and meta are left alone
        for k, v in meta.items():
            _put_meta(con, k, v)
    con.close()
    return meta


def init_momentum(
    cfg: Config, start: pd.Timestamp, params: mom.MomParams, liquid_top: int | None, reset: bool = False
) -> dict:
    """Add a momentum-rotation sleeve (own capital, frozen params) to the ledger."""
    con = _db(cfg)
    try:
        return _init_momentum(con, cfg, start, params, liquid_top, reset)
    finally:
        con.close()


def _init_momentum(con, cfg, start, params, liquid_top, reset) -> dict:
    meta = _meta(con)
    if "momentum" in meta and not reset:
        raise SystemExit("A momentum sleeve already exists. Use --reset to discard it and start over.")
    mm = {"start": str(start.date()), "capital": cfg.capital, "params": asdict(params), "liquid_top": liquid_top,
          "contribution": cfg.monthly_contribution}
    with con:
        for t in ("mom_trades", "mom_equity", "mom_positions", "mom_orders"):
            con.execute(f"DROP TABLE IF EXISTS {t}")
        _put_meta(con, "momentum", mm)
    con.close()
    return mm


def _replay_rotation(
    cfg: Config, prep: mom.MomPrep, entry: dict, asof: str | None, slug: str = "", tier: str = ""
) -> tuple[MomState, pd.DataFrame, pd.DataFrame]:
    """Deterministic replay of one rotation sleeve (momentum or a research candidate) from its start."""
    p = mom.MomParams(**entry["params"])
    mcfg = cfg.model_copy(update={"capital": entry["capital"]})
    start, end = pd.Timestamp(entry["start"]), (pd.Timestamp(asof) if asof else None)
    res = mom.run(mcfg, prep, p, start, end, emit_last=True, contribution=entry.get("contribution", 0.0))
    if res.equity.empty:
        raise SystemExit(f"No trading days on/after sleeve start {start.date()} yet. Update data.")
    last = res.equity.index[-1]
    li = prep.dates.get_loc(last)
    pos = pd.DataFrame(
        [{"symbol": prep.syms[si], "qty": q["qty"], "entry_price": q["px"], "entry_date": str(prep.dates[q["d"]].date()),
          "last_close": float(prep.c[li, si]), "bars_held": li - q["d"]} for si, q in res.positions.items()],
        columns=["symbol", "qty", "entry_price", "entry_date", "last_close", "bars_held"])
    orders = pd.DataFrame(
        [{"side": "sell", "symbol": prep.syms[si], "reason": why, "target_value": None} for si, why in res.pending_sells.items()]
        + [{"side": "buy", "symbol": prep.syms[si], "reason": "rebalance", "target_value": tv} for si, tv in res.pending_buys],
        columns=["side", "symbol", "reason", "target_value"])
    return MomState(res, prep, p, entry.get("liquid_top"), start, entry["capital"], last, slug, tier,
                    entry.get("contribution", 0.0)), pos, orders


def _sync_momentum(cfg: Config, instruments: pd.DataFrame, meta: dict, asof: str | None, con) -> MomState | None:
    mm = meta.get("momentum")
    if not mm:
        return None
    prep = mom.prepare(cfg.model_copy(update={"capital": mm["capital"]}), instruments, mm["liquid_top"])
    state, pos, orders = _replay_rotation(cfg, prep, mm, asof)
    res = state.result
    trades = res.trades if len(res.trades) else pd.DataFrame(columns=["symbol", "net_pnl"])
    with con:
        con.to_sql(trades, "mom_trades")
        con.to_sql(res.equity.reset_index(), "mom_equity")
        con.to_sql(pos, "mom_positions")
        con.to_sql(orders, "mom_orders")
    return state


# ---------------------------------------------------------------- research candidate sleeves
MAX_ACTIVE_CANDIDATES = 5


def candidate_entries(cfg: Config) -> dict:
    """All candidate sleeve records in the ledger (active and retired), slug -> entry."""
    con = _db(cfg)
    try:
        return _meta(con).get("candidates", {})
    finally:
        con.close()


def promote_candidate(cfg: Config, instruments: pd.DataFrame, slug: str, start: pd.Timestamp | None = None) -> dict:
    """Freeze a candidate that passed research-eval into the ledger as its own forward-only sleeve."""
    from .data.sources import BENCHMARK
    from .research import evaluate as ev
    from .research import registry

    m = registry.meta(slug)
    sha = registry.sha256(slug)
    trial = registry.latest_trial(cfg, slug, sha)
    if trial is None or trial["verdict"] not in ("PASS", "FORWARD_ONLY"):
        got = "no evaluation of the current file" if trial is None else f"verdict {trial['verdict']}"
        raise SystemExit(f"{slug}: cannot promote ({got}). Run `trader research-eval {slug}` and it must PASS.")
    con = _db(cfg)
    try:
        return _promote(con, cfg, slug, m, sha, trial, start)
    finally:
        con.close()


def _promote(con, cfg, slug, m, sha, trial, start) -> dict:
    from .data.sources import BENCHMARK
    from .research import evaluate as ev

    meta = _meta(con)
    cands = meta.get("candidates", {})
    if cands.get(slug, {}).get("active"):
        con.close()
        raise SystemExit(f"{slug} is already an active sleeve.")
    n_active = sum(1 for e in cands.values() if e.get("active"))
    if n_active >= MAX_ACTIVE_CANDIDATES:
        con.close()
        raise SystemExit(f"{n_active} candidate sleeves already active (max {MAX_ACTIVE_CANDIDATES}). Retire one first.")
    gi = int(trial["metrics"]["chosen"]["grid_index"])
    params = ev.grid_params(m)[gi]
    if start is None:
        start = store.load(BENCHMARK).index.max()
    entry = {
        "kind": m["kind"], "params": asdict(params), "liquid_top": ev.PRIMARY_LIQUID_TOP, "capital": ev.EVAL_CAPITAL, "contribution": ev.EVAL_CONTRIBUTION,
        "start": str(pd.Timestamp(start).date()), "file_sha256": sha, "trial_id": trial["id"], "active": True,
        "tier": "forward_only" if trial["verdict"] == "FORWARD_ONLY" else "backtest_pass",
        "promoted": datetime.now().isoformat(timespec="seconds"),
    }
    cands[slug] = entry
    with con:
        _put_meta(con, "candidates", cands)
    con.close()
    return entry


def retire_candidate(cfg: Config, slug: str) -> None:
    con = _db(cfg)
    try:
        _retire(con, slug)
    finally:
        con.close()


def _retire(con, slug) -> None:
    cands = _meta(con).get("candidates", {})
    if slug not in cands or not cands[slug].get("active"):
        con.close()
        raise SystemExit(f"{slug} is not an active candidate sleeve.")
    cands[slug].update(active=False, retired=datetime.now().isoformat(timespec="seconds"))
    with con:
        _put_meta(con, "candidates", cands)
    con.close()


def _sync_candidates(cfg: Config, instruments: pd.DataFrame, meta: dict, asof: str | None, con) -> tuple[dict, dict]:
    from .research import registry

    states, errors, preps = {}, {}, {}
    frames = {"cand_trades": [], "cand_equity": [], "cand_positions": [], "cand_orders": []}
    for slug, e in meta.get("candidates", {}).items():
        if not e.get("active"):
            continue
        try:
            if registry.sha256(slug) != e["file_sha256"]:
                errors[slug] = "candidate file changed since promotion (code freeze): sleeve not replayed"
                continue
        except (SystemExit, FileNotFoundError):
            errors[slug] = "candidate file missing: sleeve not replayed"
            continue
        key = e["liquid_top"]
        if key not in preps:
            preps[key] = mom.prepare(cfg.model_copy(update={"capital": e["capital"]}), instruments, key)
        try:
            state, pos, orders = _replay_rotation(cfg, preps[key], e, asof, slug, e.get("tier", ""))
        except SystemExit as ex:  # e.g. no trading day on/after start yet
            errors[slug] = str(ex)
            continue
        states[slug] = state
        r = state.result
        for name, df in (("cand_trades", r.trades), ("cand_equity", r.equity.reset_index()), ("cand_positions", pos),
                         ("cand_orders", orders)):
            if len(df):
                frames[name].append(df.assign(sleeve=slug))
    with con:
        for name, parts in frames.items():
            df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame({"sleeve": []})
            con.to_sql(df, name)
    return states, errors


def strategies_from(params: dict) -> dict[str, Strategy]:
    out = {}
    for name, v in params.items():
        st = ALL[name](**v["params"])
        st.key, st.params = v["key"], v["params"]
        out[st.key] = st
    return out


def is_stale(last_bar, last_complete_day) -> bool:
    """True when the newest bar is older than the last session that should already have a final bar."""
    return pd.Timestamp(last_bar).date() < sessions.last_session_on_or_before(last_complete_day)


def sync(cfg: Config, instruments: pd.DataFrame, asof: str | None = None) -> PaperState:
    """Replay each sleeve from its start to `asof` (default: latest bar) and persist the state."""
    con = _db(cfg)
    try:
        return _sync(con, cfg, instruments, asof)
    finally:
        con.close()


def _sync(con, cfg, instruments, asof) -> PaperState:
    meta = _meta(con)
    if "params" not in meta and "momentum" not in meta:
        raise SystemExit("No paper ledger. Run `trader paper-momentum` (or `trader paper-init`) first.")
    end = pd.Timestamp(asof) if asof else None
    res = prep = start = capital = None
    last = regime = None
    if "params" in meta:
        strats = strategies_from(meta["params"])
        sel = Selector.from_dict(meta["selector"])
        pcfg = cfg.model_copy(update={"capital": meta["capital"]})
        prep = bt.prepare(pcfg, instruments, list(strats.values()), filters=True)
        start, capital = pd.Timestamp(meta["start"]), meta["capital"]
        res = bt.run(pcfg, prep, strats, start, end, sel, emit_last=True)
        if res.equity.empty:
            raise SystemExit(f"No trading days on/after paper start {start.date()} yet. Update data.")
        last = res.equity.index[-1]
        regime = NAMES[int(prep.mkt[prep.dates.get_loc(last)])]

        # explicit columns so empty frames still create valid tables
        orders = pd.DataFrame([asdict(o) for o in res.pending], columns=[f.name for f in fields(bt.Order)])
        positions = pd.DataFrame([asdict(p) for p in res.positions], columns=[f.name for f in fields(bt.Position)])
        trades = res.trades if len(res.trades) else pd.DataFrame(columns=["symbol", "strategy", "net_pnl"])
        with con:
            con.to_sql(trades, "trades")
            con.to_sql(res.equity.reset_index(), "equity")
            con.to_sql(positions, "positions")
            con.to_sql(orders, "orders")
            for k, v in (("last_date", str(last.date())), ("regime", regime)):
                _put_meta(con, k, v)
    mstate = _sync_momentum(cfg, instruments, meta, asof, con)
    cands, cand_errors = _sync_candidates(cfg, instruments, meta, asof, con)
    con.close()
    if last is None:  # momentum-only ledger
        last = mstate.last_date
        regime = NAMES[int(mstate.prep.mkt[mstate.prep.dates.get_loc(last)])]
    stale = asof is None and is_stale(last, store.last_complete_day())
    return PaperState(res, prep, last, regime, start, capital, stale, mstate, cands, cand_errors)
