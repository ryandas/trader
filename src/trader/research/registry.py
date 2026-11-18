"""Candidate loading and the append-only trial registry (data/research.db).

Every evaluation is a row in `trials`; nothing is ever updated or deleted. The deflated Sharpe's
trial count comes from here, so a researcher cannot hide failed attempts.

Candidate contract (src/trader/research/candidates/<slug>.py):
    META = {"slug", "kind": "rotation", "hypothesis", "source", "grid": [ {param: value}, ... up to 4 ]}
    optional META["uses_fundamentals"] = True  (forward-paper only: grid must have one point)
    def score(prep: MomPrep, **params) -> ndarray (dates x syms), higher = buy, using only data <= each row's date.
    Grid keys top_n / buffer / bear_exit / rebalance configure the rotation engine; every other key is
    passed to score().
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from ..config import Config

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
CANDIDATES_DIR = Path(__file__).parent / "candidates"
ENGINE_KEYS = ("top_n", "buffer", "bear_exit", "rebalance")
MAX_GRID = 4
DDL = """CREATE TABLE IF NOT EXISTS trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, slug TEXT, file_sha256 TEXT, hypothesis TEXT,
    source TEXT, grid TEXT, metrics_json TEXT, gates_json TEXT, verdict TEXT, counted INTEGER)"""


def check_slug(slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise SystemExit(f"Bad candidate slug {slug!r}: use lowercase letters, digits and underscores.")
    return slug


def candidate_path(slug: str) -> Path:
    return CANDIDATES_DIR / f"{check_slug(slug)}.py"


def sha256(slug: str) -> str:
    return hashlib.sha256(candidate_path(slug).read_bytes()).hexdigest()


def load(slug: str):
    """Import the candidate module (fresh from disk)."""
    if not candidate_path(slug).exists():
        raise SystemExit(f"No candidate file {candidate_path(slug)}")
    name = f"trader.research.candidates.{slug}"
    mod = importlib.import_module(name)
    return importlib.reload(mod)


def meta(slug: str) -> dict:
    mod = load(slug)
    m = dict(getattr(mod, "META", {}))
    missing = [k for k in ("slug", "kind", "hypothesis", "source", "grid") if k not in m]
    if missing:
        raise SystemExit(f"{slug}: META is missing {missing}")
    if m["slug"] != slug:
        raise SystemExit(f"{slug}: META['slug'] is {m['slug']!r}")
    if m["kind"] != "rotation":
        raise SystemExit(f"{slug}: only kind='rotation' is supported by research-eval (got {m['kind']!r})")
    if not callable(getattr(mod, "score", None)):
        raise SystemExit(f"{slug}: no score(prep, **params) function")
    g = m["grid"]
    if not (isinstance(g, list) and 1 <= len(g) <= MAX_GRID and all(isinstance(x, dict) for x in g)):
        raise SystemExit(f"{slug}: grid must be a list of 1-{MAX_GRID} dicts")
    if m.get("uses_fundamentals") and len(g) != 1:
        raise SystemExit(f"{slug}: a fundamentals candidate has no backtest to choose with, so its grid must be one point")
    return m


def split_params(point: dict) -> tuple[dict, tuple]:
    """grid point -> (MomParams engine kwargs, ranker_params as sorted pairs)."""
    eng = {k: v for k, v in point.items() if k in ENGINE_KEYS}
    rp = tuple(sorted((k, v) for k, v in point.items() if k not in ENGINE_KEYS))
    return eng, rp


# ---------------------------------------------------------------- trial log
def _con(cfg: Config) -> sqlite3.Connection:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(cfg.data_dir / "research.db")
    con.execute(DDL)
    return con


def record_trial(cfg: Config, slug: str, sha: str, m: dict, metrics: dict, gates: dict, verdict: str,
                 counted: bool = True) -> int:
    con = _con(cfg)
    with con:
        cur = con.execute(
            "INSERT INTO trials (ts, slug, file_sha256, hypothesis, source, grid, metrics_json, gates_json, verdict, counted)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), slug, sha, m["hypothesis"], m["source"],
             json.dumps(m["grid"]), json.dumps(metrics, default=float), json.dumps(gates, default=str), verdict, int(counted)),
        )
    con.close()
    return int(cur.lastrowid)


def trial_count(cfg: Config) -> int:
    con = _con(cfg)
    n = con.execute("SELECT COUNT(*) FROM trials WHERE counted = 1").fetchone()[0]
    con.close()
    return int(n)


def trial_sharpes(cfg: Config) -> list[float]:
    """Per-period (daily) Sharpe of every counted trial that recorded one."""
    con = _con(cfg)
    rows = con.execute("SELECT metrics_json FROM trials WHERE counted = 1").fetchall()
    con.close()
    out = []
    for (mj,) in rows:
        v = json.loads(mj).get("daily_sharpe")
        if v is not None:
            out.append(float(v))
    return out


def latest_trial(cfg: Config, slug: str, sha: str | None = None) -> dict | None:
    con = _con(cfg)
    q, args = "SELECT id, ts, file_sha256, metrics_json, gates_json, verdict FROM trials WHERE slug = ?", [slug]
    if sha:
        q, args = q + " AND file_sha256 = ?", args + [sha]
    row = con.execute(q + " ORDER BY id DESC LIMIT 1", args).fetchone()
    con.close()
    if not row:
        return None
    return {"id": row[0], "ts": row[1], "sha": row[2], "metrics": json.loads(row[3]),
            "gates": json.loads(row[4]), "verdict": row[5]}


def recent_trials(cfg: Config, limit: int = 10) -> list[dict]:
    con = _con(cfg)
    rows = con.execute("SELECT id, ts, slug, verdict, counted FROM trials ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    return [{"id": r[0], "ts": r[1], "slug": r[2], "verdict": r[3], "counted": bool(r[4])} for r in rows]
