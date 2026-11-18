"""One-off import of the pre-Postgres local state (data/ and reports/) into the database.

Local files are left untouched as a backup. The import refuses a non-empty database unless forced, and finishes by
comparing row counts per table against the sources (exit code != 0 on any mismatch).
"""
from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from . import db, outputs
from .config import ROOT
from .data import fundamentals, instruments, membership

TABLES = ["candles", "instruments", "membership_snapshots", "membership_events", "membership_unavailable",
          "membership_releases", "fundamentals", "paper_meta", "trials", "output_runs"]


def counts() -> dict[str, int]:
    with db.engine().connect() as c:
        return {t: int(c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()) for t in TABLES}


def clear() -> None:
    with db.engine().begin() as c:
        c.execute(text("ALTER TABLE trials DISABLE TRIGGER trials_no_change"))
        for t in TABLES:
            c.execute(text(f"DELETE FROM {t}"))
        c.execute(text("ALTER TABLE trials ENABLE TRIGGER trials_no_change"))
        c.execute(text("DELETE FROM job_runs"))


def _candles(data: Path, log) -> int:
    files = sorted((data / "candles").glob("*.parquet"))
    raw = db.engine().raw_connection()
    n = 0
    try:
        for i, f in enumerate(files, 1):
            df = pd.read_parquet(f)
            out = pd.DataFrame({"symbol": f.stem, "date": df.index.strftime("%Y-%m-%d"), "open": df["open"].astype(float),
                                "high": df["high"].astype(float), "low": df["low"].astype(float),
                                "close": df["close"].astype(float), "volume": df["volume"].astype("int64")})
            buf = io.StringIO()
            out.to_csv(buf, index=False, header=False, float_format="%.17g")
            with raw.cursor() as cur, cur.copy("COPY candles (symbol, date, open, high, low, close, volume) FROM STDIN WITH (FORMAT CSV)") as cp:
                cp.write(buf.getvalue())
            n += len(out)
            if i % 100 == 0 or i == len(files):
                raw.commit()
                log(f"  candles {i}/{len(files)} symbols, {n:,} rows")
        raw.commit()
    finally:
        raw.close()
    return n


def _membership(data: Path) -> dict:
    m = data / "membership"
    out = {"snapshots": 0, "events": 0, "unavailable": 0, "releases": 0}
    for f in sorted((m / "snapshots").glob("*.csv")):
        out["snapshots"] += membership.save_snapshot(pd.Timestamp(f.stem), pd.read_csv(f))
    for name, manual in (("events.csv", False), ("manual_events.csv", True)):
        if (m / name).exists():
            d = pd.read_csv(m / name, parse_dates=["eff_date"])
            out["events"] += membership.save_events(d, manual=manual)
    if (m / "unavailable.csv").exists():
        d = pd.read_csv(m / "unavailable.csv")
        d["last_seen"] = d["last_seen"].astype(object).where(d["last_seen"].notna(), None)
        membership.save_unavailable(d)
        out["unavailable"] = len(d)
    with db.engine().begin() as c:
        for f in sorted((m / "releases").glob("*")):
            if f.is_file():
                c.execute(text("INSERT INTO membership_releases (name, pdf) VALUES (:n, :b) ON CONFLICT (name) DO UPDATE SET pdf = EXCLUDED.pdf"),
                          {"n": f.name, "b": f.read_bytes()})
                out["releases"] += 1
    return out


def _ledger(data: Path) -> int:
    p = data / "paper.db"
    if not p.exists():
        return 0
    con = sqlite3.connect(p)
    try:
        rows = con.execute("SELECT key, value FROM meta").fetchall()
    except sqlite3.OperationalError:
        rows = []
    con.close()
    with db.engine().begin() as c:
        for k, v in rows:
            c.execute(text("INSERT INTO paper_meta (key, value) VALUES (:k, CAST(:v AS jsonb))"), {"k": k, "v": v})
    return len(rows)  # sleeve tables (mom_*, cand_*, ...) are rebuilt from this meta by the next `trader daily`


def _trials(data: Path) -> int:
    p = data / "research.db"
    if not p.exists():
        return 0
    con = sqlite3.connect(p)
    rows = con.execute("SELECT id, ts, slug, file_sha256, hypothesis, source, grid, metrics_json, gates_json, verdict, counted FROM trials ORDER BY id").fetchall()
    con.close()
    with db.engine().begin() as c:
        for r in rows:
            c.execute(text("INSERT INTO trials (id, ts, slug, file_sha256, hypothesis, source, grid, metrics_json, gates_json, verdict, counted) "
                           "OVERRIDING SYSTEM VALUE VALUES (:i, :ts, :sl, :sh, :h, :so, CAST(:g AS jsonb), CAST(:m AS jsonb), CAST(:ga AS jsonb), :v, :n)"),
                      dict(zip("i ts sl sh h so g m ga v n".split(), r)))
        c.execute(text("SELECT setval(pg_get_serial_sequence('trials', 'id'), COALESCE((SELECT MAX(id) FROM trials), 1), (SELECT COUNT(*) FROM trials) > 0)"))
    return len(rows)


def _read_csv(p: Path, **kw) -> pd.DataFrame:
    if not p.read_text().strip():  # e.g. an orders file with no orders: no header either
        return pd.DataFrame()
    return pd.read_csv(p, **kw)


def _outputs(data: Path, reports: Path) -> dict:
    n = {"runs": 0}
    wf = reports / "walkforward"
    if (wf / "oos_equity.csv").exists():
        items = {"folds": _read_csv(wf / "folds.csv"), "oos_trades": _read_csv(wf / "oos_trades.csv"),
                 "oos_equity": _read_csv(wf / "oos_equity.csv", index_col=0, parse_dates=True)}
        for name, f in (("params", "params.json"), ("selector_stats", "selector_stats.json")):
            if (data / f).exists():
                items[name] = json.loads((data / f).read_text())
        outputs.save("walkforward", "", items, {"imported": True}); n["runs"] += 1
    elif (data / "params.json").exists():
        items = {"params": json.loads((data / "params.json").read_text())}
        if (data / "selector_stats.json").exists():
            items["selector_stats"] = json.loads((data / "selector_stats.json").read_text())
        outputs.save("walkforward", "", items, {"imported": True}); n["runs"] += 1
    for kind, d in (("momentum-wf", reports / "momentum-wf"), ("momentum", reports / "momentum"), ("backtest", reports / "backtest")):
        items = {}
        for f in sorted(d.glob("*.csv")) if d.exists() else []:
            items[f.stem] = _read_csv(f, index_col=0, parse_dates=True) if f.stem in ("oos_equity", "equity") else _read_csv(f)
        if items:
            outputs.save(kind, "", items, {"imported": True}); n["runs"] += 1
    for d in sorted((reports / "research").glob("*/")) if (reports / "research").exists() else []:
        if not d.is_dir():
            continue
        items = {}
        if (d / "summary.md").exists():
            items["summary"] = (d / "summary.md").read_text()
        if (d / "folds.csv").exists():
            items["folds"] = _read_csv(d / "folds.csv")
        if (d / "oos_equity.csv").exists():
            items["oos_equity"] = _read_csv(d / "oos_equity.csv", index_col=0, parse_dates=True)
        if items:
            outputs.save("research-eval", d.name, items, {"imported": True}); n["runs"] += 1
    for f in sorted(reports.glob("????-??-??.md")) if reports.exists() else []:
        items = {"report": f.read_text()}
        for suffix in ("momentum-orders", "orders"):
            c = reports / f"{f.stem}-{suffix}.csv"
            if c.exists():
                items[suffix] = _read_csv(c)
        outputs.save("daily", f.stem, items, {"imported": True}); n["runs"] += 1
    return n


def run(force: bool = False, log=print) -> bool:
    data, reports = ROOT / "data", ROOT / "reports"
    have = counts()
    if any(have.values()) and not force:
        raise SystemExit(f"The database already holds data ({ {k: v for k, v in have.items() if v} }). Use --force to replace it.")
    if force:
        clear()
    expect: dict[str, int] = {}
    if (data / "instruments.csv").exists():
        d = pd.read_csv(data / "instruments.csv")
        instruments.save_instruments(d)
        expect["instruments"] = len(d)
    log("candles...")
    expect["candles"] = sum(len(pd.read_parquet(f)) for f in (data / "candles").glob("*.parquet"))
    _candles(data, log)
    log("membership...")
    m = _membership(data)
    expect.update({"membership_snapshots": sum(len(pd.read_csv(f)) for f in (data / "membership" / "snapshots").glob("*.csv")),
                   "membership_unavailable": m["unavailable"], "membership_releases": m["releases"]})
    log("fundamentals...")
    expect["fundamentals"] = 0
    for f in sorted((data / "fundamentals").glob("*.parquet")):
        d = pd.read_parquet(f)
        fundamentals.save_snapshot(pd.Timestamp(f.stem), d)
        expect["fundamentals"] += len(d)
    log("ledger and trials...")
    expect["paper_meta"] = _ledger(data)
    expect["trials"] = _trials(data)
    log("outputs...")
    n = _outputs(data, reports)
    expect["output_runs"] = n["runs"]
    got = counts()
    ok = True
    log(f"\n{'table':26s}{'expected':>12s}{'in db':>12s}")
    for t in TABLES:
        if t in ("membership_events",):
            continue  # events are de-duplicated on load; informational below
        e = expect.get(t)
        bad = e is not None and e != got[t]
        ok &= not bad
        log(f"{t:26s}{'' if e is None else e:>12}{got[t]:>12}{'   <-- MISMATCH' if bad else ''}")
    log(f"membership_events (info): {got['membership_events']} rows")
    return ok
