from datetime import datetime

import pandas as pd

from trader.data import store


def _frame(closes):
    idx = pd.to_datetime(["2026-11-10", "2026-11-11", "2026-11-12"])[: len(closes)]
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000.0}, index=idx
    )


def test_revised_close_is_persisted_without_new_rows(pg, monkeypatch):
    first = _frame([100.0, 101.0, 102.0])
    revised = first.copy()
    revised.loc["2026-11-12", "close"] = 102.5  # within the 1% split tolerance
    monkeypatch.setattr(store, "_fetch", lambda *a, **k: current["df"].copy())
    current = {"df": first}
    now = datetime(2026, 11, 13, 20, 0)
    store.update_symbol(None, "ABC", 1, now=now)
    assert store.load("ABC")["close"].iloc[-1] == 102.0

    current["df"] = revised
    added = store.update_symbol(None, "ABC", 1, now=now)
    assert added == 0
    assert store.load("ABC")["close"].iloc[-1] == 102.5


def test_load_many_matches_load_and_keeps_order(pg, monkeypatch):
    now = datetime(2026, 11, 13, 20, 0)
    for sym, closes in (("ZZZ", [1.0, 2.0, 3.0]), ("AAA", [5.0, 6.0, 7.0])):
        monkeypatch.setattr(store, "_fetch", lambda *a, _c=closes, **k: _frame(_c))
        store.update_symbol(None, sym, 1, now=now)
    got = store.load_many(["ZZZ", "AAA", "MISSING"])
    assert list(got) == ["ZZZ", "AAA"]
    for sym in got:
        pd.testing.assert_frame_equal(got[sym], store.load(sym))
    assert store.load("MISSING") is None


def test_split_adjustment_rebuilds_history(pg, monkeypatch):
    now = datetime(2026, 11, 13, 20, 0)
    monkeypatch.setattr(store, "_fetch", lambda *a, **k: _frame([100.0, 101.0, 102.0]))
    store.update_symbol(None, "SPL", 1, now=now)
    monkeypatch.setattr(store, "_fetch", lambda *a, **k: _frame([50.0, 50.5, 51.0]))  # 2:1 split, history re-adjusted
    store.update_symbol(None, "SPL", 1, now=now)
    assert store.load("SPL")["close"].tolist() == [50.0, 50.5, 51.0]
