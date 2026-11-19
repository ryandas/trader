import numpy as np

from trader.research.candidates import quality_india as q


class _Prep:
    def __init__(self, panels):
        self.p = panels

    def fund_panel(self, name):
        return self.p[name]


def test_quality_prefers_profitable_low_debt_and_needs_all_fields():
    roe = np.array([[0.30, 0.10, 0.20, np.nan]])
    opm = np.array([[0.25, 0.05, 0.15, 0.20]])
    de = np.array([[10.0, 200.0, 50.0, 30.0]])
    s = q.score(_Prep({"roe": roe, "op_margin": opm, "debt_to_equity": de}))
    assert s[0, 0] > s[0, 2] > s[0, 1]
    assert np.isnan(s[0, 3])  # missing ROE -> not eligible


def test_quality_nan_before_first_snapshot():
    nan = np.full((3, 2), np.nan)
    s = q.score(_Prep({"roe": nan, "op_margin": nan, "debt_to_equity": nan}))
    assert np.isnan(s).all()


def test_meta_is_single_point_fundamentals():
    assert q.META["uses_fundamentals"] and len(q.META["grid"]) == 1
