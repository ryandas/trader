from types import SimpleNamespace

import numpy as np
import pandas as pd

from trader.research.candidates.str_rev import META, score


def _prep(df):
    return SimpleNamespace(close_df=df)


def _frame(n=120):
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame({
        "LOSER": 100 * 0.995 ** np.arange(n),
        "WINNER": 100 * 1.005 ** np.arange(n),
    }, index=idx)


def test_recent_loser_scores_higher():
    s = score(_prep(_frame()), lookback=21)
    assert s[-1, 0] > s[-1, 1]


def test_no_lookahead():
    df = _frame()
    t = 80
    full = score(_prep(df), lookback=21)
    trunc = score(_prep(df.iloc[: t + 1]), lookback=21)
    np.testing.assert_allclose(full[t], trunc[t])
    altered = df.copy()
    altered.iloc[t + 1:] *= 3.0
    np.testing.assert_allclose(score(_prep(altered), lookback=21)[t], full[t])


def test_grid_fixed_at_four_points():
    assert len(META["grid"]) == 4
