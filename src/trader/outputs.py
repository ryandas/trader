"""Generated outputs (reports, backtest and walk-forward results, research-eval results) stored in Postgres.

Each save appends one `output_runs` row (kind, key, time, git head, args) plus one `output_items` row per item:
  - text  (markdown report, summary)          -> body_text
  - json  (params, selector stats, any dict)  -> body_json
  - frame (DataFrame, index kept when it is not a plain range) -> body_json {columns, data, index, dtypes}
History is kept: every run is a new row, `latest`/`get` read the newest one.
"""
from __future__ import annotations

import json
import subprocess

import pandas as pd
from sqlalchemy import text

from . import db
from .config import ROOT


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5).stdout.strip() or None
    except Exception:
        return None


def encode_frame(df: pd.DataFrame) -> dict:
    keep_index = not (isinstance(df.index, pd.RangeIndex) and df.index.name is None)
    body = json.loads(df.to_json(orient="split", date_format="iso", double_precision=15, index=keep_index))
    return {"columns": body["columns"], "data": body["data"], "index": body.get("index") if keep_index else None,
            "index_name": df.index.name if keep_index else None,
            "index_dtype": str(df.index.dtype) if keep_index else None,
            "dtypes": {str(c): str(t) for c, t in df.dtypes.items()}}


def decode_frame(b: dict) -> pd.DataFrame:
    df = pd.DataFrame(b["data"], columns=b["columns"])
    for c, t in b["dtypes"].items():
        try:
            if t.startswith("datetime"):
                df[c] = pd.to_datetime(df[c])
            elif t in ("float64", "float32", "int64", "int32", "bool"):
                df[c] = df[c].astype("float64" if t.startswith("float") or df[c].isna().any() else t)
        except (ValueError, TypeError):
            pass
    if b.get("index") is not None:
        idx = pd.Index(b["index"], name=b.get("index_name"))
        if str(b.get("index_dtype", "")).startswith("datetime"):
            idx = pd.DatetimeIndex(pd.to_datetime(idx), name=b.get("index_name"))
        df.index = idx
    return df


def save(kind: str, key: str, items: dict, args: dict | None = None) -> int:
    """Append a run holding `items` (name -> DataFrame | str | dict | list). Returns the run id."""
    with db.engine().begin() as c:
        rid = int(c.execute(text("INSERT INTO output_runs (kind, key, git_head, args) VALUES (:k, :y, :g, CAST(:a AS jsonb)) RETURNING id"),
                            {"k": kind, "y": key, "g": _git_head(), "a": json.dumps(args or {}, default=str)}).scalar())
        for name, v in items.items():
            if isinstance(v, pd.DataFrame):
                fmt, bt, bj = "frame", None, json.dumps(encode_frame(v))
            elif isinstance(v, str):
                fmt, bt, bj = "text", v, None
            else:
                fmt, bt, bj = "json", None, json.dumps(v, default=str)
            c.execute(text("INSERT INTO output_items (run_id, name, format, body_text, body_json) VALUES (:r, :n, :f, :t, CAST(:j AS jsonb))"),
                      {"r": rid, "n": name, "f": fmt, "t": bt, "j": bj})
    return rid


def latest_run(kind: str, key: str = "") -> int | None:
    with db.engine().connect() as c:
        return c.execute(text("SELECT id FROM output_runs WHERE kind = :k AND key = :y ORDER BY id DESC LIMIT 1"),
                         {"k": kind, "y": key}).scalar()


def get(kind: str, key: str = "", name: str | None = None, run_id: int | None = None):
    """One item of the newest run of (kind, key), or all items as a dict when `name` is None. None if absent."""
    rid = run_id or latest_run(kind, key)
    if rid is None:
        return None
    with db.engine().connect() as c:
        rows = c.execute(text("SELECT name, format, body_text, body_json FROM output_items WHERE run_id = :r"
                              + (" AND name = :n" if name else "")), {"r": rid, **({"n": name} if name else {})}).fetchall()
    out = {n: (bt if f == "text" else decode_frame(bj) if f == "frame" else bj) for n, f, bt, bj in rows}
    return (out.get(name) if name else out) if rows else None


def listing(kind: str | None = None, limit: int = 20) -> pd.DataFrame:
    q = "SELECT id, kind, key, created, git_head FROM output_runs" + (" WHERE kind = :k" if kind else "") + " ORDER BY id DESC LIMIT :n"
    return db.qdf(q, **({"k": kind} if kind else {}), n=limit)


def render(item) -> str:
    if isinstance(item, pd.DataFrame):
        return item.to_string()
    if isinstance(item, str):
        return item
    return json.dumps(item, indent=2, default=str)
