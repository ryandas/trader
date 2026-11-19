import importlib.util
from pathlib import Path

from trader.config import ROOT, load_config

_spec = importlib.util.spec_from_file_location("format_daily_message", ROOT / "scripts" / "format_daily_message.py")
fmt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fmt)

LOG = """2026-11-18 | regime bull
account | equity 5,100 | cash 400 | paid in 5,000
swing sleeve | positions 300 | 1 open | 1 orders for next session
momentum sleeve | positions 4,400 | 7 holdings | 1 sells, 2 buys queued
candidate my_cand (forward_only) | value 5,010 (paid in 5,000) | 3 holdings | 0 sells, 0 buys queued
report: reports/2026-11-18.md
orders: reports/2026-11-18-momentum_orders.csv
WARNING: 3 symbols not updated: AB_C, D*E
WARNING: no NSE holiday list for 2027 (scripts/nse_holidays_2027.txt); holidays are not skipped until it is added.
"""


def _run(tmp_path, capsys):
    p = tmp_path / "log.txt"
    p.write_text(LOG)
    assert fmt.main(["x", str(p)]) == 0
    return capsys.readouterr().out


def test_formatter_uses_configured_top_n_and_escapes(tmp_path, capsys):
    out = _run(tmp_path, capsys)
    assert f"Holdings 7/{load_config().momentum.top_n}" in out
    assert "Equity ₹5,100 · cash ₹400 · paid in ₹5,000" in out
    assert "P&L so far +₹100" in out
    assert "Positions ₹4,400" in out and "positions 300" in out
    assert "AB\\_C, D\\*E" in out
    assert "my\\_cand" in out
    assert "momentum\\_orders" in out
    assert "⚠️ no NSE holiday list for 2027" in out


def test_esc():
    assert fmt.esc("a_b*c`d[e") == "a\\_b\\*c\\`d\\[e"
