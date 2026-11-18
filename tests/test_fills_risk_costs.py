import pytest

from trader.config import CostCfg, RiskCfg
from trader.costs import apply_slippage, trade_costs
from trader.fills import check_exit, fill_entry
from trader.risk import can_open, position_size


# ---- fills
def test_open_entry_fills_at_open():
    assert fill_entry("open", None, None, 100, 105, 99) == 100


def test_open_entry_rejected_above_cap():
    assert fill_entry("open", None, 101, 102, 105, 99) is None


def test_buy_stop_not_triggered():
    assert fill_entry("stop", 110, None, 100, 109.9, 99) is None


def test_buy_stop_triggered_intraday_fills_at_trigger():
    assert fill_entry("stop", 110, None, 100, 112, 99) == 110


def test_buy_stop_gap_up_fills_at_open():
    assert fill_entry("stop", 110, None, 115, 118, 114) == 115


def test_gap_through_stop_exits_at_open():
    assert check_exit(95, 120, 90, 96, 88) == (90, "stop_gap")


def test_stop_hit_intraday():
    assert check_exit(95, 120, 100, 101, 94) == (95, "stop")


def test_stop_and_target_same_bar_stop_wins():
    assert check_exit(95, 110, 100, 112, 94) == (95, "stop")


def test_target_hit():
    assert check_exit(95, 110, 100, 111, 99) == (110, "target")


def test_no_exit():
    assert check_exit(95, 110, 100, 105, 97) is None
    assert check_exit(95, None, 100, 500, 97) is None


# ---- costs
def test_slippage_is_adverse():
    assert apply_slippage(100, "buy", 10) == pytest.approx(100.1)
    assert apply_slippage(100, "sell", 10) == pytest.approx(99.9)


def test_costs_positive_and_sell_has_dp_buy_has_stamp():
    c = CostCfg()
    buy, sell = trade_costs("buy", 100_000, c), trade_costs("sell", 100_000, c)
    assert buy > 100 and sell > 100  # STT alone is Rs 100
    assert sell - buy == pytest.approx(c.dp_charge - 100_000 * c.stamp_pct)


# ---- risk
def test_size_risks_one_percent():
    # equity 100k, 1% = 1000 risk, Rs 10/share risk -> 100 shares (Rs 10k, under 20% cap)
    assert position_size(100_000, 0.01, 100, 90, 0.20, 100_000) == 100


def test_size_capped_by_position_pct():
    # risk-based qty would be 1000 but 20% cap = Rs 20k / Rs 100 = 200
    assert position_size(100_000, 0.01, 100, 99, 0.20, 100_000) == 200


def test_size_capped_by_cash_and_invalid_stop():
    assert position_size(100_000, 0.01, 100, 90, 0.20, 500) == 5
    assert position_size(100_000, 0.01, 100, 100, 0.20, 100_000) == 0
    assert position_size(100_000, 0.01, 100, 110, 0.20, 100_000) == 0


def test_can_open_constraints():
    r = RiskCfg()
    assert can_open(0, 0, 0, 1000, 100_000, r)
    assert not can_open(r.max_positions, 0, 0, 1000, 100_000, r)
    assert not can_open(0, r.max_per_sector, 0, 1000, 100_000, r)
    assert not can_open(0, 0, 5500, 1000, 100_000, r)  # heat 6.5% > 6%
