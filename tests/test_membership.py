import numpy as np
import pandas as pd

from trader.data import membership


def _snap(tmp_path, date, rows):
    d = tmp_path / "membership" / "snapshots"
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["Company Name", "Industry", "Symbol", "Series", "ISIN Code"]).to_csv(d / f"{date}.csv", index=False)


def test_membership_is_newest_snapshot_on_or_before_the_day(tmp_path):
    _snap(tmp_path, "20200101", [("A", "x", "AAA", "EQ", "I1"), ("B", "x", "BBB", "EQ", "I2")])
    _snap(tmp_path, "20200201", [("A", "x", "AAA", "EQ", "I1"), ("C", "x", "CCC", "EQ", "I3")])
    dates = pd.DatetimeIndex(["2019-12-31", "2020-01-01", "2020-01-31", "2020-02-01", "2020-03-01"])
    m = membership.member_panel(tmp_path, dates, ["AAA", "BBB", "CCC"])
    assert m.tolist() == [[True, True, False]] * 3 + [[True, False, True]] * 2  # before the first snapshot: the first one


def test_rename_keeps_one_identity_by_isin(tmp_path):
    _snap(tmp_path, "20200101", [("Old name", "x", "OLD", "EQ", "I1")])
    _snap(tmp_path, "20200201", [("New name", "x", "NEW", "EQ", "I1")])
    m = membership.member_panel(tmp_path, pd.DatetimeIndex(["2020-01-15", "2020-02-15"]), ["NEW"])
    assert m.tolist() == [[True], [True]]
    info = membership.isin_symbols(membership.load_snapshots(tmp_path))
    assert info.loc[0, "symbol"] == "NEW"


def test_split_new_isin_is_the_same_company(tmp_path):
    """A split gives the company a new ISIN; the symbol on the row keeps the identity."""
    _snap(tmp_path, "20200101", [("A", "x", "AAA", "EQ", "OLDISIN")])
    _snap(tmp_path, "20200301", [("A", "x", "AAA", "EQ", "NEWISIN")])
    keyof, table = membership.companies(membership.load_snapshots(tmp_path))
    assert keyof["OLDISIN"] == keyof["NEWISIN"] == "AAA" and len(table) == 1


def test_press_release_events_apply_between_snapshots_on_effective_date(tmp_path):
    _snap(tmp_path, "20200101", [("A", "x", "AAA", "EQ", "I1"), ("B", "x", "BBB", "EQ", "I2")])
    _snap(tmp_path, "20200601", [("A", "x", "AAA", "EQ", "I1"), ("C", "x", "CCC", "EQ", "I3")])
    pd.DataFrame({"eff_date": ["2020-03-31", "2020-03-31"], "symbol": ["BBB", "CCC"], "action": [-1, 1]}).to_csv(
        tmp_path / "membership" / "events.csv", index=False)
    dates = pd.DatetimeIndex(["2020-03-30", "2020-03-31", "2020-05-01"])
    m = membership.member_panel(tmp_path, dates, ["AAA", "BBB", "CCC"])
    assert m.tolist() == [[True, True, False], [True, False, True], [True, False, True]]
    _, rep = membership.timeline(tmp_path)
    assert rep[0]["events"] == 2 and rep[0]["unexplained_in"] == 0 and rep[0]["unexplained_out"] == 0


def test_parse_release_reads_only_the_nifty_500_section():
    text = """These changes shall become effective from March 31, 2022 (close of March 30, 2022).
1) NIFTY Alpha 50
The following companies are being excluded:
  Sr. No.   Company Name   Symbol
     1      Other Ltd.     OTHER
3) NIFTY 500
The following companies are being excluded:
     1      Old Co Ltd.                  OLDCO
The following companies are being included:
     1      New Co Ltd.                  NEWCO
The above replacements will also apply to X.
4) NIFTY Midcap 150
The following companies are being included:
     1      Mid Ltd.                     MIDCO
"""
    eff, ev = membership.parse_release(text)
    assert eff == pd.Timestamp("2022-03-31") and ev == [("OLDCO", -1), ("NEWCO", 1)]
