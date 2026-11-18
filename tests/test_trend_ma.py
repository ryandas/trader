from types import SimpleNamespace

import numpy as np
import pandas as pd

from trader.research.candidates.trend_ma import score

LENS = (20, 50, 100, 200)


def _prep(df):
    return SimpleNamespace(close_df=df)


def _frame(n=300):
    idx = pd.bdate_range("2020-01-01", periods=n)
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "UP": 100 * 1.002 ** np.arange(n),
        "DOWN": 100 * 0.998 ** np.arange(n),
        "RND": 100 + np.cumsum(rng.normal(0, 1, n)),
    }, index=idx)


def test_rising_scores_above_falling():
    s = score(_prep(_frame()), ma_lengths=LENS)
    assert s[-1, 0] > s[-1, 1]
    assert np.isnan(s[:max(LENS) - 1]).all()
    assert not np.isnan(s[max(LENS) - 1:]).any()


def test_no_lookahead():
    df = _frame()
    t = 250
    full = score(_prep(df), ma_lengths=LENS)
    trunc = score(_prep(df.iloc[: t + 1]), ma_lengths=LENS)
    np.testing.assert_allclose(full[t], trunc[t])
    altered = df.copy()
    altered.iloc[t + 1:] *= 3.0
    np.testing.assert_allclose(score(_prep(altered), ma_lengths=LENS)[t], full[t])
