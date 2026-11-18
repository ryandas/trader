import types

import numpy as np
import pandas as pd

from trader.research.candidates import vol_mom


def _prep(n=400):
    idx = pd.bdate_range("2020-01-01", periods=n)
    rng = np.random.default_rng(0)
    smooth = 100 * np.cumprod(1 + 0.001 + rng.normal(0, 0.002, n))
    noisy = 100 * np.cumprod(1 + 0.001 + rng.normal(0, 0.03, n))
    return types.SimpleNamespace(close_df=pd.DataFrame({"S": smooth, "N": noisy}, index=idx))


def test_smooth_winner_outranks_noisy_one():
    s = vol_mom.score(_prep(), window=63)
    assert s[-1, 0] > s[-1, 1]


def test_no_lookahead_truncated_history_matches():
    p = _prep()
    full = vol_mom.score(p, window=63)
    cut = types.SimpleNamespace(close_df=p.close_df.iloc[:350])
    short = vol_mom.score(cut, window=63)
    np.testing.assert_allclose(full[349], short[-1], equal_nan=True)
