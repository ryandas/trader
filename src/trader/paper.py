"""Paper-trading ledger.

The ledger is a deterministic replay of the backtest engines (same fills, costs, sizing and
risk rules) from a fixed start date, using parameters and selector statistics FROZEN at init.
Nothing fitted after the start date can leak into it, so its results are genuine forward
evidence. State is persisted to Postgres for reporting and for Claude to read.

ONE ACCOUNT: the swing and momentum sleeves share a single cash balance (`ledger.run`; the arbitration rule is in
that module's docstring). The account's start, opening capital and monthly contribution are not stored separately:
they are derived at sync time from the frozen sleeve records (the earliest-starting sleeve defines them), so there is
no extra state to drift. Research candidate sleeves (`cand_*`) are NOT part of the account: each is an isolated
research replay with its own capital.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime

import numpy as np
import pandas as pd

from . import backtest as bt
from . import ledger
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
    account: ledger.AccountResult | None = None  # the shared cash account (swing + momentum)
    account_spec: ledger.AccountSpec | None = None


def _db(cfg: Config) -> db.Con:
    return db.connect()


def _meta(con: db.Con) -> dict:
    return {k: v for k, v in con.execute("SELECT key, value FROM paper_meta").fetchall()}


def _put_meta(con: db.Con, key: str, value) -> None:
    con.execute("INSERT INTO paper_meta (key, value) VALUES (?, CAST(? AS jsonb)) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, json.dumps(value, default=str)))


SWING_TABLES = ("trades", "equity", "positions", "orders")
SWING_KEYS = ("start", "capital", "params", "selector", "created", "last_date", "regime", "contribution")


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
        "contribution": cfg.monthly_contribution,
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
    # The momentum sleeve records its own start/capital/contribution; the shared account derives from these (see account_spec).
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
    pos, orders = _rotation_frames(prep, res, last)
    return MomState(res, prep, p, entry.get("liquid_top"), start, entry["capital"], last, slug, tier,
                    entry.get("contribution", 0.0)), pos, orders


def _rotation_frames(prep: mom.MomPrep, res: mom.MomResult, last: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Open positions and queued orders of a rotation sleeve as tables."""
    li = prep.dates.get_loc(last)
    pos = pd.DataFrame(
        [{"symbol": prep.syms[si], "qty": q["qty"], "entry_price": q["px"], "entry_date": str(prep.dates[q["d"]].date()),
          "last_close": float(prep.c[li, si]), "bars_held": li - q["d"]} for si, q in res.positions.items()],
        columns=["symbol", "qty", "entry_price", "entry_date", "last_close", "bars_held"])
    orders = pd.DataFrame(
        [{"side": "sell", "symbol": prep.syms[si], "reason": why, "target_value": None} for si, why in res.pending_sells.items()]
        + [{"side": "buy", "symbol": prep.syms[si], "reason": "rebalance", "target_value": tv} for si, tv in res.pending_buys],
        columns=["side", "symbol", "reason", "target_value"])
    return pos, orders


def account_spec(meta: dict) -> ledger.AccountSpec | None:
    """Start, opening cash and monthly deposit of the shared account, derived from the frozen sleeve records.

    The earliest-starting sleeve defines them (a tie goes to momentum). A swing record written before the account
    existed has no `contribution`; it then takes the other sleeve's value, else 0. Nothing here is stored or mutable."""
    recs = []
    if "momentum" in meta:
        m = meta["momentum"]
        recs.append((pd.Timestamp(m["start"]), 0, m["capital"], m.get("contribution")))
    if "params" in meta:
        recs.append((pd.Timestamp(meta["start"]), 1, meta["capital"], meta.get("contribution")))
    if not recs:
        return None
    recs.sort(key=lambda r: (r[0], r[1]))
    start, _, capital, contribution = recs[0]
    if contribution is None:
        contribution = next((r[3] for r in recs if r[3] is not None), 0.0)
    return ledger.AccountSpec(start=start, capital=capital, contribution=contribution)


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
    spec = account_spec(meta)
    sw = mo = None
    prep = mprep = start = capital = None
    if "params" in meta:
        strats = strategies_from(meta["params"])
        prep = bt.prepare(cfg, instruments, list(strats.values()), filters=True)
        start, capital = pd.Timestamp(meta["start"]), meta["capital"]
        sw = ledger.SwingSpec(prep, strats, Selector.from_dict(meta["selector"]), start)
    mm = meta.get("momentum")
    if mm:
        mprep = mom.prepare(cfg, instruments, mm["liquid_top"])
        mo = ledger.MomSpec(mprep, mom.MomParams(**mm["params"]), pd.Timestamp(mm["start"]))
    acct = ledger.run(cfg, spec, swing=sw, mom=mo, end=end, emit_last=True)  # ONE replay, ONE cash balance
    if acct.equity.empty:
        raise SystemExit(f"No trading days on/after ledger start {spec.start.date()} yet. Update data.")
    last = acct.equity.index[-1]
    mkt_prep = prep if prep is not None else mprep
    regime = NAMES[int(mkt_prep.mkt[mkt_prep.dates.get_loc(last)])]

    with con:
        # explicit columns so empty frames still create valid tables
        con.to_sql(acct.equity.reset_index(), "account_equity")
        if sw:
            res = acct.swing
            orders = pd.DataFrame([asdict(o) for o in res.pending], columns=[f.name for f in fields(bt.Order)])
            positions = pd.DataFrame([asdict(p) for p in res.positions], columns=[f.name for f in fields(bt.Position)])
            trades = res.trades if len(res.trades) else pd.DataFrame(columns=["symbol", "strategy", "net_pnl"])
            con.to_sql(trades, "trades")
            con.to_sql(res.equity.reset_index(), "equity")  # date, value: the sleeve's positions value
            con.to_sql(positions, "positions")
            con.to_sql(orders, "orders")
            for k, v in (("last_date", str(last.date())), ("regime", regime)):
                _put_meta(con, k, v)
        mstate = None
        if mo:
            r = acct.mom
            mstate = MomState(r, mprep, mo.params, mm["liquid_top"], mo.start, mm["capital"], last,
                              contribution=mm.get("contribution", 0.0))
            pos, morders = _rotation_frames(mprep, r, last)
            con.to_sql(r.trades if len(r.trades) else pd.DataFrame(columns=["symbol", "net_pnl"]), "mom_trades")
            con.to_sql(r.equity.reset_index(), "mom_equity")  # date, value: the sleeve's positions value
            con.to_sql(pos, "mom_positions")
            con.to_sql(morders, "mom_orders")
    cands, cand_errors = _sync_candidates(cfg, instruments, meta, asof, con)
    con.close()
    stale = asof is None and is_stale(last, store.last_complete_day())
    return PaperState(acct.swing, prep, last, regime, start, capital, stale, mstate, cands, cand_errors, acct, spec)
