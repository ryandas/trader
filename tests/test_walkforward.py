import pandas as pd
import pytest

from trader import walkforward as wf


def test_folds_never_overlap_and_oos_follows_is():
    dates = pd.bdate_range("2016-11-17", "2026-11-17")
    folds = wf.fold_windows(dates)
    assert len(folds) >= 5
    for is_s, is_e, oos_s, oos_e in folds:
        assert is_s < is_e < oos_s <= oos_e <= dates[-1]
        assert (is_e - is_s).days > 365 * 3 - 5
        assert is_s >= dates[wf.WARMUP_BARS]  # indicators warmed up before in-sample starts
    # OOS windows are disjoint and ascending
    for a, b in zip(folds, folds[1:]):
        assert a[3] < b[2]


def test_little_history_gives_few_or_no_folds():
    assert len(wf.fold_windows(pd.bdate_range("2021-11-17", "2026-11-17"))) == 1  # 5y: one fold
    assert wf.fold_windows(pd.bdate_range("2023-11-17", "2026-11-17")) == []


def test_chain_carries_equity_forward():
    a = pd.DataFrame({"equity": [100.0, 110.0], "invested": 0.5}, index=pd.to_datetime(["2020-01-01", "2020-12-31"]))
    b = pd.DataFrame({"equity": [100.0, 90.0], "invested": 0.5}, index=pd.to_datetime(["2021-01-01", "2021-12-31"]))
    c = wf._chain([a, b], 100.0)
    assert c["equity"].tolist() == pytest.approx([100.0, 110.0, 110.0, 99.0])


def test_chain_keeps_first_day_return_of_each_fold():
    # both folds start from 100 and earn +10% on their first day, then are flat
    a = pd.DataFrame({"equity": [110.0, 110.0]}, index=pd.to_datetime(["2020-01-01", "2020-12-31"]))
    b = pd.DataFrame({"equity": [110.0, 110.0]}, index=pd.to_datetime(["2021-01-01", "2021-12-31"]))
    c = wf._chain([a, b], 100.0)
    # old code rescaled each fold to start at the carried level, giving [100, 100, 110, 110]
    assert c["equity"].tolist() == pytest.approx([110.0, 110.0, 121.0, 121.0])


def test_grid_keys_and_defaults():
    g = wf.build_grid()
    for name in wf.GRIDS:
        assert f"{name}#0" in g and g[f"{name}#0"].params == {}
    assert g["breakout#1"].vol_mult == 2.0
