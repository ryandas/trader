import json
import sqlite3

import numpy as np
import pandas as pd
import pytest
from typer.testing import CliRunner

from trader import cli, db, migrate, outputs
from trader.data import fundamentals, instruments, membership, store
from trader.research import registry


def test_frame_roundtrip_keeps_index_dtypes_and_nan(pg):
    eq = pd.DataFrame({"equity": [100.0, np.nan, 102.5], "n": [1, 2, 3]},
                      index=pd.DatetimeIndex(pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]), name="date"))
    plain = pd.DataFrame({"symbol": ["A", "B"], "entry_date": pd.to_datetime(["2026-01-01", "2026-01-02"]), "pnl": [1.5, -2.0]})
    rid = outputs.save("unit", "k", {"eq": eq, "plain": plain, "note": "hello", "cfg": {"a": [1, 2]}})
    got = outputs.get("unit", "k")
    pd.testing.assert_frame_equal(got["eq"], eq, check_freq=False)
    pd.testing.assert_frame_equal(got["plain"], plain)
    assert got["note"] == "hello" and got["cfg"] == {"a": [1, 2]}
    rid2 = outputs.save("unit", "k", {"note": "newer"})
    assert outputs.get("unit", "k", "note") == "newer" and outputs.get("unit", "k", "note", run_id=rid) == "hello" and rid2 > rid
    assert outputs.get("unit", "missing") is None


def test_show_prints_latest_report(pg):
    outputs.save("daily", "2026-11-17", {"report": "# Report A"})
    outputs.save("daily", "2026-11-18", {"report": "# Report B", "orders": pd.DataFrame({"symbol": ["X"]})})
    r = CliRunner().invoke(cli.app, ["show", "daily"])
    assert r.exit_code == 0 and "# Report B" in r.output
    r = CliRunner().invoke(cli.app, ["show", "daily", "2026-11-17"])
    assert "# Report A" in r.output
    r = CliRunner().invoke(cli.app, ["show", "daily", "2026-11-18", "orders"])
    assert "X" in r.output


def test_migrate_local_roundtrip(pg, tmp_path, monkeypatch):
    data, reports = tmp_path / "data", tmp_path / "reports"
    for d in ("candles", "fundamentals", "membership/snapshots", "membership/releases"):
        (data / d).mkdir(parents=True)
    (reports / "walkforward").mkdir(parents=True)
    pd.DataFrame({"symbol": [f"S{i}" for i in range(3)], "name": "n", "sector": "x", "security_id": [1, 2, 3]}
                 ).to_csv(data / "instruments.csv", index=False)
    idx = pd.date_range("2026-01-01", periods=5, freq="B", name="date")
    for s in ("S0", "S1"):
        pd.DataFrame({"open": 1.5, "high": 2.0, "low": 1.0, "close": np.linspace(1, 2, 5), "volume": 1000}, index=idx
                     ).to_parquet(data / "candles" / f"{s}.parquet")
    pd.DataFrame([("A", "x", "S0", "EQ", "I1"), ("B", "x", "S1", "EQ", "I2")], columns=membership.SNAP_COLS
                 ).to_csv(data / "membership" / "snapshots" / "20260101.csv", index=False)
    pd.DataFrame({"eff_date": ["2026-02-01"], "symbol": ["S1"], "action": [-1], "release": ["r"]}
                 ).to_csv(data / "membership" / "events.csv", index=False)
    (data / "membership" / "unavailable.csv").write_text("symbol,name,rows,last_seen\nGONE,Gone Ltd,0,2019-02-01\n")
    (data / "membership" / "releases" / "20200101.pdf").write_bytes(b"%PDF-fake")
    pd.DataFrame({"roe": [0.1, 0.2]}, index=pd.Index(["S0", "S1"], name="symbol")).to_parquet(data / "fundamentals" / "2026-01-02.parquet")
    con = sqlite3.connect(data / "paper.db")
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO meta VALUES ('momentum', ?)", (json.dumps({"start": "2026-01-02", "capital": 5000}),))
    con.commit(); con.close()
    con = sqlite3.connect(data / "research.db")
    con.execute("CREATE TABLE trials (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, slug TEXT, file_sha256 TEXT, hypothesis TEXT, "
                "source TEXT, grid TEXT, metrics_json TEXT, gates_json TEXT, verdict TEXT, counted INTEGER)")
    for i in (3, 7):
        con.execute("INSERT INTO trials VALUES (?, 't', 'x', 'sha', 'h', 's', '[{}]', '{\"daily_sharpe\": 0.1}', '{}', 'FAIL', 1)", (i,))
    con.commit(); con.close()
    (data / "params.json").write_text('{"breakout": {"key": "breakout#0", "params": {}}}')
    (data / "selector_stats.json").write_text("{}")
    pd.DataFrame({"fold": [1]}).to_csv(reports / "walkforward" / "folds.csv", index=False)
    pd.DataFrame({"symbol": ["S0"]}).to_csv(reports / "walkforward" / "oos_trades.csv", index=False)
    pd.DataFrame({"equity": [1.0, 2.0]}, index=pd.Index(pd.to_datetime(["2026-01-01", "2026-01-02"]), name="date")
                 ).to_csv(reports / "walkforward" / "oos_equity.csv")
    (reports / "2026-01-02.md").write_text("# Report")

    monkeypatch.setattr(migrate, "ROOT", tmp_path)
    assert migrate.run(log=lambda *_: None)
    with pytest.raises(SystemExit):  # refuses a non-empty database
        migrate.run(log=lambda *_: None)
    assert migrate.run(force=True, log=lambda *_: None)

    assert len(store.load("S0")) == 5 and store.load("S2") is None
    assert list(instruments.load_instruments()["symbol"]) == ["S0", "S1", "S2"]
    assert list(fundamentals.asof("2026-01-03").index) == ["S0", "S1"]
    assert len(membership.load_events()) == 1
    with db.engine().connect() as c:
        assert bytes(c.execute(db.text("SELECT pdf FROM membership_releases")).scalar()) == b"%PDF-fake"
    assert registry.trial_count(None) == 2
    assert registry.record_trial(None, "t", "s", {"hypothesis": "h", "source": "s", "grid": [{}]}, {}, {}, "FAIL") == 8  # ids preserved, sequence continues
    assert outputs.get("walkforward", "", "params") == {"breakout": {"key": "breakout#0", "params": {}}}
    assert outputs.get("daily", "2026-01-02", "report") == "# Report"
    assert outputs.get("walkforward", "", "oos_equity")["equity"].tolist() == [1.0, 2.0]
