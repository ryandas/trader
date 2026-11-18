"""NSE trading-session calendar: weekdays minus the holidays listed in scripts/nse_holidays_*.txt.

Used where the code must guess the NEXT or the LAST session without having the bar yet (is the latest bar a month-end? is the
data stale?). A year with no holiday list is treated as having no holidays, so those guesses fall back to plain weekdays.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import pandas as pd

from .config import ROOT


@lru_cache(maxsize=1)
def holidays() -> frozenset[pd.Timestamp]:
    out = set()
    for f in sorted((ROOT / "scripts").glob("nse_holidays_*.txt")):
        for ln in f.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                out.add(pd.Timestamp(ln))
    return frozenset(out)


def is_session(d) -> bool:
    d = pd.Timestamp(d).normalize()
    return d.weekday() < 5 and d not in holidays()


def next_session(d) -> pd.Timestamp:
    """First session strictly after `d`."""
    n = pd.Timestamp(d).normalize() + timedelta(days=1)
    while not is_session(n):
        n += timedelta(days=1)
    return n


def last_session_on_or_before(d) -> date:
    n = pd.Timestamp(d).normalize()
    while not is_session(n):
        n -= timedelta(days=1)
    return n.date()
