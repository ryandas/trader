import numpy as np
import pandas as pd

from trader.regime import BEAR, BULL, NEUTRAL, market_regime
from trader.selector import Selector, eligible
from trader.universe import membership, rank_matrix


def test_market_regime_bull_and_bear():
    idx = pd.bdate_range("2020-01-01", periods=600)
    up = pd.Series(np.linspace(100, 300, 600), index=idx)
    down = pd.Series(np.linspace(300, 100, 600), index=idx)
    assert market_regime(up).iloc[-1] == BULL
    assert market_regime(down).iloc[-1] == BEAR
    assert market_regime(up).iloc[50] == NEUTRAL  # < 200 bars of history


def test_market_regime_no_lookahead():
    rng = np.random.default_rng(0)
    c = pd.Series(100 + np.cumsum(rng.normal(0, 1, 600)), index=pd.bdate_range("2020-01-01", periods=600))
    pd.testing.assert_series_equal(market_regime(c).iloc[:400], market_regime(c.iloc[:400]))


def test_rank_matrix_ranks_only_liquid():
    rs = np.array([[0.1, 0.5, 0.3, 0.9]])
    liq = np.array([[True, True, True, False]])
    r = rank_matrix(rs, liq)
    assert r[0, :3].tolist() == [3, 1, 2] and np.isnan(r[0, 3])
    assert membership(r, 2).tolist() == [[False, True, True, False]]


def test_eligibility_rules():
    mkt = np.array([BULL, BEAR])
    trending = np.array([True, True])
    above = np.array([True, True])
    assert eligible("breakout", mkt, trending, above, "mean_reversion_only").tolist() == [True, False]
    assert eligible("mean_reversion", mkt, ~trending, above, "mean_reversion_only").tolist() == [True, True]
    assert eligible("mean_reversion", mkt, ~trending, above, "none").tolist() == [True, False]
    assert not eligible("mean_reversion", mkt, trending, above, "none").any()  # trending: not MR


def test_selector_switches_off_losers_and_ranks():
    rows = (
        [{"strategy": "breakout", "mkt": BULL, "net_pnl": 100.0, "risk": 100.0}] * 25
        + [{"strategy": "trend_pullback", "mkt": BULL, "net_pnl": -50.0, "risk": 100.0}] * 25
        + [{"strategy": "breakout", "mkt": NEUTRAL, "net_pnl": -50.0, "risk": 100.0}] * 5  # too few
    )
    sel = Selector.from_trades(pd.DataFrame(rows), min_trades=20)
    assert sel.allowed("breakout", BULL) and not sel.allowed("trend_pullback", BULL)
    assert sel.allowed("breakout", NEUTRAL)  # not enough evidence to switch off
    assert sel.weight("breakout", BULL) > sel.weight("mean_reversion", BULL)


def test_selector_roundtrip(tmp_path):
    sel = Selector({("breakout", BULL): 0.4, ("mean_reversion", BEAR): -0.1})
    sel.save(tmp_path / "s.json")
    assert Selector.load(tmp_path / "s.json").stats == sel.stats
