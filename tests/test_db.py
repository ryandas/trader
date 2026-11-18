import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from trader import db


def test_tables_exist(pg):
    with pg.connect() as c:
        names = {r[0] for r in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"))}
    assert {"paper_meta", "trials", "candles", "fundamentals", "output_runs", "job_runs"} <= names


def test_trials_are_append_only(pg):
    with pg.begin() as c:
        c.execute(text("INSERT INTO trials (ts, slug, counted) VALUES ('t', 's', 1)"))
    with pytest.raises(DBAPIError):
        with pg.begin() as c:
            c.execute(text("UPDATE trials SET counted = 0"))
    with pytest.raises(DBAPIError):
        with pg.begin() as c:
            c.execute(text("DELETE FROM trials"))


def test_lock_blocks_second_holder(pg):
    with db.lock("unit"):
        with pytest.raises(SystemExit):
            with db.lock("unit"):
                pass
    with db.lock("unit"):  # released afterwards
        pass


def test_errors_do_not_leak_password(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", "1")
    monkeypatch.setenv("POSTGRES_SCHEMA", "never_created")
    monkeypatch.setenv("POSTGRES_PASSWORD", "s3cretpw")
    db._engine.cache_clear()
    with pytest.raises(SystemExit) as e:
        db.engine()
    assert "s3cretpw" not in str(e.value)
