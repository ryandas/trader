import pandas as pd

from trader import momentum as mom
from trader import paper, sessions
from test_momentum import world


def _month_end_pos(idx, start=300):
    return next(i for i in range(start, len(idx) - 1) if idx[i].month != idx[i + 1].month)


def test_last_bar_is_month_end_when_remaining_weekdays_are_holidays(monkeypatch):
    """The newest bar is the last session before a holiday that closes out the month: the rebalance must be flagged on it
    (a later replay with the next bar present flags it, so the live-day order list must too)."""
    cfg, full, idx = world(monkeypatch)
    t = _month_end_pos(idx)
    assert full.rebal[t - 1] is not None and not full.rebal[t - 1]  # actual data: t-1 is not the last session
    monkeypatch.setattr(sessions, "holidays", lambda: frozenset({idx[t]}))
    _, cut, _ = world(monkeypatch, truncate=t - 1)
    assert cut.rebal[-1], "last bar before a month-end holiday must be a rebalance day"
    # control: with no holiday known, the next weekday is still in the month
    monkeypatch.setattr(sessions, "holidays", lambda: frozenset())
    _, cut2, _ = world(monkeypatch, truncate=t - 1)
    assert not cut2.rebal[-1]


def test_last_bar_week_end_with_friday_holiday(monkeypatch):
    cfg, _, idx = world(monkeypatch)
    thu = next(i for i in range(300, len(idx) - 1) if idx[i].weekday() == 3)
    monkeypatch.setattr(sessions, "holidays", lambda: frozenset({idx[thu + 1]}))  # the Friday
    _, cut, _ = world(monkeypatch, truncate=thu)
    assert cut.rebal_w[-1]


def test_next_session_skips_weekend_and_holiday(monkeypatch):
    monkeypatch.setattr(sessions, "holidays", lambda: frozenset({pd.Timestamp("2026-03-31")}))
    assert sessions.next_session("2026-03-30") == pd.Timestamp("2026-04-01")
    assert sessions.next_session("2026-04-03") == pd.Timestamp("2026-04-06")  # Friday -> Monday


def test_stale_detects_one_missing_day(monkeypatch):
    monkeypatch.setattr(sessions, "holidays", lambda: frozenset())
    # 16:30 run on Wed 2026-11-18: today's bar is missing, yesterday's is present -> stale
    assert paper.is_stale("2026-11-17", pd.Timestamp("2026-11-18").date())
    assert not paper.is_stale("2026-11-18", pd.Timestamp("2026-11-18").date())
    # weekend run: last completed day is Sunday, the Friday bar is current
    assert not paper.is_stale("2026-11-20", pd.Timestamp("2026-11-22").date())
    assert paper.is_stale("2026-11-19", pd.Timestamp("2026-11-22").date())


def test_stale_ignores_exchange_holiday(monkeypatch):
    monkeypatch.setattr(sessions, "holidays", lambda: frozenset({pd.Timestamp("2026-11-24")}))
    assert not paper.is_stale("2026-11-23", pd.Timestamp("2026-11-24").date())
