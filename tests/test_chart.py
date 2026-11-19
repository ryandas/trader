"""The ledger chart script, run against the throwaway test schema (never the live ledger)."""
import importlib.util

import numpy as np
import pandas as pd
import pytest

from test_account import MP, _frames  # noqa: F401  (also provides the `world` fixture below)
from trader import db, paper
from trader.config import ROOT, Config
from helpers import patch_candles
from trader import outputs
from trader.strategies import ALL

_spec = importlib.util.spec_from_file_location("paper_report_chart", ROOT / "scripts" / "paper_report_chart.py")
chart = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chart)


@pytest.fixture
def world(monkeypatch, pg):
    patch_candles(monkeypatch, _frames())
    inst = pd.DataFrame({"symbol": [f"S{i}" for i in range(8)], "sector": list("AABBCCDD")})
    outputs.save("walkforward", "", {"params": {n: {"key": f"{n}#0", "params": {}} for n in ALL}, "selector_stats": {}})
    return Config(capital=50_000, monthly_contribution=5_000), inst, _frames()["NIFTY500"].index


def test_chart_from_a_synced_two_sleeve_ledger(world, tmp_path):
    cfg, inst, idx = world
    paper.init(cfg, idx[300])
    paper.init_momentum(cfg, idx[300], MP, None)
    paper.sync(cfg, inst, asof=str(idx[520].date()))
    out = chart.build(tmp_path / "c.png")
    assert out.exists() and out.stat().st_size > 10_000


def test_chart_with_ten_holdings_and_no_swing_tables(world, tmp_path):
    """Synthetic rows: 10 momentum holdings and the account table only (no swing tables at all)."""
    d = pd.bdate_range("2026-11-17", periods=5)
    acct = pd.DataFrame({"date": d, "equity": 25_000.0, "invested": 0.9, "value": np.linspace(25_000, 25_600, 5),
                         "cash": 500.0, "swing_value": 0.0, "mom_value": np.linspace(24_500, 25_100, 5),
                         "deposited": 25_000.0})
    pos = pd.DataFrame({"symbol": [f"SYM{i}" for i in range(10)], "qty": 3, "entry_price": 800.0,
                        "entry_date": "2026-11-18", "last_close": 810.0, "bars_held": 2})
    orders = pd.DataFrame({"side": ["sell"], "symbol": ["SYM0"], "reason": ["rebalance"], "target_value": [None]},
                          dtype=object)
    con = db.connect()
    with con:
        con.to_sql(acct, "account_equity")
        con.to_sql(pos, "mom_positions")
        con.to_sql(orders, "mom_orders")
    con.close()
    out = chart.build(tmp_path / "ten.png")
    assert out.exists() and out.stat().st_size > 10_000


def test_chart_on_an_empty_database_does_not_crash(pg, tmp_path):
    assert chart.build(tmp_path / "empty.png").exists()
