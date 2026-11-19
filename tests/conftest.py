"""Shared fixtures. DB-backed tests run in a throwaway Postgres schema on the configured server."""
import os
import sys
import uuid

import pandas as pd
import pytest

from helpers import CAPITAL, DEPOSIT, patch_candles, synth, _frames
from trader import backtest as bt
from trader import db
from trader import momentum as mom
from trader.config import Config
from trader.research import candidates as cand_pkg
from trader.research import evaluate, registry
from trader.strategies import ALL


@pytest.fixture(scope="session")
def pg_schema():
    from dotenv import load_dotenv
    load_dotenv(db.ROOT / ".env")
    if any(not os.getenv(k) for k in db.REQUIRED):
        pytest.skip("POSTGRES_* not configured in .env")
    old = os.environ.get("POSTGRES_SCHEMA")
    sch = f"trader_test_{uuid.uuid4().hex[:10]}"
    os.environ["POSTGRES_SCHEMA"] = sch
    try:
        db.engine()
    except SystemExit as e:
        pytest.skip(str(e))
    yield sch
    db.drop_schema(sch)
    if old is None:
        os.environ.pop("POSTGRES_SCHEMA", None)
    else:
        os.environ["POSTGRES_SCHEMA"] = old


@pytest.fixture
def pg(pg_schema):
    """Empty tables in the test schema for each test."""
    from sqlalchemy import text
    eng = db.engine()
    with eng.begin() as c:
        rows = c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = :s"), {"s": pg_schema}).fetchall()
        for (t,) in rows:
            if t != "trials":
                c.execute(text(f'DROP TABLE IF EXISTS "{t}" CASCADE'))
        c.execute(text("ALTER TABLE trials DISABLE TRIGGER trials_no_change"))
        c.execute(text("DELETE FROM trials"))
        c.execute(text("ALTER TABLE trials ENABLE TRIGGER trials_no_change"))
    db._engine.cache_clear()
    db.engine()
    return eng


@pytest.fixture
def acct(monkeypatch):
    """(cfg, instruments, index, swing prep, strategies, mom prep) on synthetic candles; no database."""
    frames = _frames()
    patch_candles(monkeypatch, frames)
    inst = pd.DataFrame({"symbol": [f"S{i}" for i in range(8)], "sector": list("AABBCCDD")})
    cfg = Config(capital=CAPITAL, monthly_contribution=DEPOSIT)
    strats = {f"{n}#0": ALL[n]() for n in ALL}
    for k, s in strats.items():
        s.key = k
    sprep = bt.prepare(cfg, inst, list(strats.values()), filters=False)
    mprep = mom.prepare(cfg, inst)
    return cfg, inst, frames["NIFTY500"].index, sprep, strats, mprep


@pytest.fixture
def lab(monkeypatch, tmp_path, pg):
    """Synthetic market + temp candidates dir; ledger, trials and outputs in the throwaway Postgres schema."""
    frames = {f"S{i}": synth(700, seed=i, drift=0.0005 + 0.0002 * (i % 5)) for i in range(30)}
    frames["NIFTY500"] = synth(700, seed=99, drift=0.0004)
    patch_candles(monkeypatch, frames)
    monkeypatch.setattr(evaluate, "PIT", False)  # synthetic market has no membership snapshots; tests cover gate logic
    cdir = tmp_path / "cands"
    cdir.mkdir()
    monkeypatch.setattr(registry, "CANDIDATES_DIR", cdir)
    monkeypatch.setattr(cand_pkg, "__path__", [str(cdir)])
    sys.modules.pop("trader.research.candidates.t_leaky", None)
    inst = pd.DataFrame({"symbol": [f"S{i}" for i in range(30)], "sector": "X"})
    return Config(capital=1_000_000), inst, frames["NIFTY500"].index, cdir
