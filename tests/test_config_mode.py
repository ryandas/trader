from pathlib import Path

from trader.config import Config, load_config

ROOT = Path(__file__).resolve().parents[1]


def test_default_mode_is_paper():
    assert Config().mode == "paper"


def test_repo_config_is_paper():
    assert load_config(ROOT / "config.yaml").mode == "paper"


def test_holiday_file_is_tracked_and_well_formed():
    lines = (ROOT / "scripts" / "nse_holidays_2026.txt").read_text().splitlines()
    dates = [ln for ln in lines if ln and not ln.startswith("#")]
    assert dates and all(len(d) == 10 and d.startswith("2026-") for d in dates)
    assert dates == sorted(dates)


def test_no_order_placing_code_in_src():
    # Guard: if order placement is ever added to src/, it must check Config.mode == "live".
    src = ROOT / "src" / "trader"
    hits = [p.name for p in src.rglob("*.py") if "place_order" in p.read_text() or "/orders" in p.read_text()]
    assert hits == []
