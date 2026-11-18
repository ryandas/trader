from datetime import datetime

import pandas as pd

from trader.data import store


class FakeSource:
    def __init__(self, df):
        self.df = df

    def fetch(self, *args, **kwargs):  # signature-agnostic
        return self.df.copy()


def _frame(closes):
    idx = pd.to_datetime(["2026-11-10", "2026-11-11", "2026-11-12"])[: len(closes)]
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 1000.0}, index=idx
    )


def test_revised_close_is_persisted_without_new_rows(tmp_path, monkeypatch):
    first = _frame([100.0, 101.0, 102.0])
    revised = first.copy()
    revised.loc["2026-11-12", "close"] = 102.5  # within the 1% split tolerance
    monkeypatch.setattr(store, "_fetch", lambda *a, **k: current["df"].copy())
    current = {"df": first}
    now = datetime(2026, 11, 13, 20, 0)
    store.update_symbol(None, tmp_path, "ABC", 1, now=now)
    assert store.load(tmp_path, "ABC")["close"].iloc[-1] == 102.0

    current["df"] = revised
    added = store.update_symbol(None, tmp_path, "ABC", 1, now=now)
    assert added == 0
    assert store.load(tmp_path, "ABC")["close"].iloc[-1] == 102.5
