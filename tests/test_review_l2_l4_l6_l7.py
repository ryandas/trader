from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from typer.testing import CliRunner

from trader import cli, sessions
from trader.config import Config
from trader.data import fundamentals as fund
from trader.data import instruments as inst
from trader.data import store


def _frame(day):
    idx = pd.to_datetime([day])
    return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 10.0}, index=idx)


def test_update_continues_past_failures_and_warns(tmp_path, monkeypatch):
    cfg = Config()
    monkeypatch.setattr(Config, "data_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(
        cli.inst, "load_instruments",
        lambda d: pd.DataFrame({"symbol": ["BAD", "EMPTY", "GOOD"], "security_id": [1, 2, 3]}),
    )

    class Src:
        def daily_candles(self, symbol, sid, start, end):
            if symbol == "BAD":
                raise RuntimeError("boom")
            if symbol == "EMPTY":
                return pd.DataFrame()
            return _frame(str(end))

    monkeypatch.setattr(cli, "YFinanceSource", Src)
    monkeypatch.setattr(store, "last_complete_day", lambda now=None: date(2026, 11, 17))
    res = CliRunner().invoke(cli.app, ["update", "BAD", "EMPTY", "GOOD"])
    assert res.exit_code == 0, res.output
    assert "BAD: ERROR RuntimeError: boom" in res.output
    assert "WARNING: 2 symbols not updated: BAD, EMPTY" in res.output
    assert store.load(tmp_path / "candles", "GOOD") is not None


def _patch_instruments(monkeypatch, n500_rows, eq_rows):
    n500 = pd.DataFrame({"Symbol": [f"S{i}" for i in range(n500_rows)], "Company Name": "x", "Industry": "y"})
    sm = pd.DataFrame({
        "SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "E", "SEM_SERIES": "EQ",
        "SEM_TRADING_SYMBOL": eq_rows, "SEM_SMST_SECURITY_ID": range(len(eq_rows)),
    })
    monkeypatch.setattr(inst, "_get", lambda url: n500 if url == inst.NIFTY500_URL else sm)


def test_instruments_drops_duplicates(tmp_path, monkeypatch, capsys):
    syms = [f"S{i}" for i in range(450)] + ["S0"]  # S0 listed twice in the scrip master
    _patch_instruments(monkeypatch, 450, syms)
    out = inst.build_instruments(tmp_path)
    assert len(out) == 450 and out["symbol"].is_unique
    assert "1 duplicate" in capsys.readouterr().out


def test_instruments_refuses_small_result_and_keeps_file(tmp_path, monkeypatch):
    (tmp_path / "instruments.csv").write_text("symbol\nKEEP\n")
    _patch_instruments(monkeypatch, 10, [f"S{i}" for i in range(10)])
    with pytest.raises(ValueError, match="refusing"):
        inst.build_instruments(tmp_path)
    assert (tmp_path / "instruments.csv").read_text() == "symbol\nKEEP\n"


def test_holiday_warning(tmp_path):
    ist = ZoneInfo("Asia/Kolkata")
    (tmp_path / "nse_holidays_2026.txt").write_text("2026-01-26\n")
    assert sessions.holiday_list_warning(datetime(2026, 6, 1, tzinfo=ist), tmp_path) is None
    w = sessions.holiday_list_warning(datetime(2027, 1, 5, tzinfo=ist), tmp_path)
    assert w.startswith("WARNING") and "2027" in w
    w = sessions.holiday_list_warning(datetime(2026, 12, 3, tzinfo=ist), tmp_path)  # December: next year needed too
    assert w.startswith("WARNING") and "2027" in w
    (tmp_path / "nse_holidays_2027.txt").write_text("2027-01-26\n")
    assert sessions.holiday_list_warning(datetime(2026, 12, 3, tzinfo=ist), tmp_path) is None


def test_ist_today_is_ist_date():
    assert fund.ist_today() == datetime.now(ZoneInfo("Asia/Kolkata")).date()
