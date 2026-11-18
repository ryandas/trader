"""Shared fixtures. DB-backed tests run in a throwaway Postgres schema on the configured server."""
import os
import uuid

import pytest

from trader import db


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
