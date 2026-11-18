"""Postgres connection layer: the single store for ledger, trials, market data and generated outputs.

Connection settings come from POSTGRES_HOST / PORT / USER / PASSWORD / DB in `.env`. POSTGRES_SCHEMA
(default "trader") lets tests use a throwaway schema. The password never appears in error messages.
"""
from __future__ import annotations

import io
import json
import os
from contextlib import contextmanager
from functools import lru_cache

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine

from .config import ROOT

REQUIRED = ("POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")

DDL = [
    "CREATE TABLE IF NOT EXISTS paper_meta (key TEXT PRIMARY KEY, value JSONB NOT NULL)",
    """CREATE TABLE IF NOT EXISTS trials (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, ts TEXT, slug TEXT, file_sha256 TEXT,
        hypothesis TEXT, source TEXT, grid JSONB, metrics_json JSONB, gates_json JSONB,
        verdict TEXT, counted INTEGER)""",
    """CREATE OR REPLACE FUNCTION trials_append_only() RETURNS trigger AS $$
       BEGIN RAISE EXCEPTION 'trials is append-only'; END; $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS trials_no_change ON trials",
    """CREATE TRIGGER trials_no_change BEFORE UPDATE OR DELETE ON trials
       FOR EACH ROW EXECUTE FUNCTION trials_append_only()""",
    """CREATE TABLE IF NOT EXISTS candles (
        symbol TEXT NOT NULL, date DATE NOT NULL, open DOUBLE PRECISION, high DOUBLE PRECISION,
        low DOUBLE PRECISION, close DOUBLE PRECISION, volume BIGINT, PRIMARY KEY (symbol, date))""",
    "CREATE TABLE IF NOT EXISTS instruments (ord INTEGER NOT NULL, symbol TEXT PRIMARY KEY, name TEXT, sector TEXT, security_id BIGINT)",
    """CREATE TABLE IF NOT EXISTS membership_snapshots (
        snap_date DATE NOT NULL, company_name TEXT, industry TEXT, symbol TEXT, series TEXT, isin TEXT)""",
    "CREATE INDEX IF NOT EXISTS membership_snapshots_date ON membership_snapshots (snap_date)",
    """CREATE TABLE IF NOT EXISTS membership_events (
        eff_date DATE, symbol TEXT, action INTEGER, release TEXT, note TEXT, manual BOOLEAN DEFAULT FALSE)""",
    "CREATE TABLE IF NOT EXISTS membership_unavailable (symbol TEXT PRIMARY KEY, name TEXT, rows INTEGER, last_seen TEXT)",
    "CREATE TABLE IF NOT EXISTS membership_releases (name TEXT PRIMARY KEY, pdf BYTEA NOT NULL)",
    """CREATE TABLE IF NOT EXISTS fundamentals (
        snap_date DATE NOT NULL, symbol TEXT NOT NULL, market_cap DOUBLE PRECISION, pe DOUBLE PRECISION,
        pb DOUBLE PRECISION, roe DOUBLE PRECISION, debt_to_equity DOUBLE PRECISION, op_margin DOUBLE PRECISION,
        earnings_growth DOUBLE PRECISION, revenue_growth DOUBLE PRECISION, fcf DOUBLE PRECISION,
        PRIMARY KEY (snap_date, symbol))""",
    """CREATE TABLE IF NOT EXISTS output_runs (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL DEFAULT '',
        created TIMESTAMPTZ NOT NULL DEFAULT now(), git_head TEXT, args JSONB)""",
    "CREATE INDEX IF NOT EXISTS output_runs_kind ON output_runs (kind, key, id DESC)",
    """CREATE TABLE IF NOT EXISTS output_items (
        run_id BIGINT NOT NULL REFERENCES output_runs(id) ON DELETE CASCADE, name TEXT NOT NULL,
        format TEXT NOT NULL, body_text TEXT, body_json JSONB, PRIMARY KEY (run_id, name))""",
    """CREATE TABLE IF NOT EXISTS job_runs (
        id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, job TEXT NOT NULL, started TIMESTAMPTZ,
        finished TIMESTAMPTZ NOT NULL DEFAULT now(), exit_code INTEGER, message TEXT, log TEXT)""",
]


def schema() -> str:
    return os.getenv("POSTGRES_SCHEMA", "trader")


def url() -> URL:
    load_dotenv(ROOT / ".env")
    missing = [k for k in REQUIRED if not os.getenv(k)]
    if missing:
        raise SystemExit(f"Postgres settings missing in .env: {', '.join(missing)} (see .env.example).")
    return URL.create(
        "postgresql+psycopg", username=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ["POSTGRES_HOST"], port=int(os.getenv("POSTGRES_PORT", "5432")),
        database=os.environ["POSTGRES_DB"], query={"sslmode": os.getenv("POSTGRES_SSLMODE", "prefer")},
    )


@lru_cache(maxsize=4)
def _engine(sch: str) -> Engine:
    eng = create_engine(url(), pool_pre_ping=True, connect_args={"options": f"-c search_path={sch},public",
                                                                  "connect_timeout": 15})
    with eng.begin() as c:
        c.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{sch}"'))
        for stmt in DDL:
            c.execute(text(stmt))
    return eng


def engine() -> Engine:
    """Engine for the current schema; creates the schema and tables on first use. Raises SystemExit if unreachable."""
    try:
        return _engine(schema())
    except SystemExit:
        raise
    except Exception as e:  # never leak the password
        pw = os.getenv("POSTGRES_PASSWORD") or "\0"
        raise SystemExit(f"Cannot reach Postgres at {os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}: "
                         f"{type(e).__name__}: {str(e).replace(pw, '***')[:300]}") from None


def drop_schema(sch: str) -> None:
    eng = engine()
    with eng.begin() as c:
        c.execute(text(f'DROP SCHEMA IF EXISTS "{sch}" CASCADE'))
    _engine.cache_clear()
    eng.dispose()


@contextmanager
def lock(name: str):
    """Session advisory lock: only one writer per job name across hosts. Exits with a message if held."""
    eng = engine()
    key = hash_i(f"{schema()}:{name}")
    with eng.connect() as c:
        if not c.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar():
            raise SystemExit(f"Another process holds the '{name}' lock (a run is in progress on another host?).")
        try:
            yield
        finally:
            c.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            c.commit()


def hash_i(s: str) -> int:
    import hashlib
    return int.from_bytes(hashlib.sha256(s.encode()).digest()[:8], "big", signed=True)


# ---------------------------------------------------------------- helpers
def qdf(sql: str, **params) -> pd.DataFrame:
    with engine().connect() as c:
        return pd.read_sql(text(sql), c, params=params)


def copy_df(sql: str) -> pd.DataFrame:
    """Bulk read through COPY (one round trip): `sql` is a SELECT without parameters."""
    raw = engine().raw_connection()
    try:
        with raw.cursor() as cur, cur.copy(f"COPY ({sql}) TO STDOUT WITH (FORMAT CSV, HEADER)") as cp:
            buf = io.BytesIO(b"".join(bytes(chunk) for chunk in cp))
        return pd.read_csv(buf)
    finally:
        raw.close()


def jdump(v) -> str:
    return json.dumps(v, default=str)


class Con:
    """Small transactional wrapper over a SQLAlchemy connection.

    `with con:` is a transaction (commit on success, rollback on error) that does NOT close the connection; `close()` does.
    SQL may use `?` placeholders. Used by the ledger, which writes several tables atomically."""

    def __init__(self) -> None:
        self.sa = engine().connect()

    def __enter__(self) -> "Con":
        if not self.sa.in_transaction():
            self.sa.begin()  # explicit, so pandas.to_sql joins it instead of committing on its own
        return self

    def __exit__(self, et, ev, tb) -> None:
        self.sa.commit() if et is None else self.sa.rollback()  # also ends a transaction auto-begun by an earlier read

    @staticmethod
    def _bind(sql: str, params) -> tuple:
        i = iter(range(len(params)))
        out = "".join(f":p{next(i)}" if ch == "?" else ch for ch in sql)
        return text(out), {f"p{k}": v for k, v in enumerate(params)}

    def execute(self, sql: str, params=()):
        stmt, p = self._bind(sql, params)
        return self.sa.execute(stmt, p)

    def to_sql(self, df: pd.DataFrame, name: str) -> None:
        """Replace table `name` with `df` (inside the current transaction)."""
        df.to_sql(name, self.sa, if_exists="replace", index=False)

    def close(self) -> None:
        if self.sa.in_transaction():
            self.sa.rollback()
        self.sa.close()


def connect() -> Con:
    return Con()
