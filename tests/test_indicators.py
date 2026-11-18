import numpy as np
import pandas as pd
import pytest

from trader import indicators as ind


def make_df(n=300, seed=0):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0.1, 1, n)
    low = close - rng.uniform(0.1, 1, n)
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close,
         "volume": rng.integers(1000, 5000, n).astype(float)},
        index=pd.bdate_range("2022-01-03", periods=n),
    )


def test_sma_hand_computed():
    s = pd.Series([1.0, 2, 3, 4, 5])
    assert ind.sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    assert np.isnan(ind.sma(s, 3).iloc[1])


def test_rsi_extremes():
    up = pd.Series(np.arange(1.0, 50))
    assert ind.rsi(up, 14).iloc[-1] == 100.0
    assert ind.rsi(up[::-1].reset_index(drop=True), 14).iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_atr_constant_range():
    df = pd.DataFrame({"open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0,
                       "volume": 1.0}, index=pd.bdate_range("2022-01-03", periods=60))
    assert ind.atr(df, 14).iloc[-1] == pytest.approx(2.0)


def test_donchian_excludes_current_bar():
    df = make_df(60)
    df.loc[df.index[-1], "high"] = 1e6
    assert ind.donchian_high(df, 20).iloc[-1] < 1e6


def test_adx_bounds():
    a = ind.adx(make_df()).dropna()
    assert ((a >= 0) & (a <= 100)).all()


@pytest.mark.parametrize("fn", [
    lambda d: ind.sma(d["close"], 50), lambda d: ind.ema(d["close"], 50),
    lambda d: ind.atr(d), lambda d: ind.rsi(d["close"]), lambda d: ind.adx(d),
    lambda d: ind.donchian_high(d, 55), lambda d: ind.volume_ratio(d),
])
def test_no_lookahead(fn):
    """Value at t is unchanged when later bars are appended/altered."""
    full = make_df(300)
    t = 200
    trunc = full.iloc[: t + 1]
    pd.testing.assert_series_equal(fn(full).iloc[: t + 1], fn(trunc), check_names=False)
