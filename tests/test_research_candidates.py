import numpy as np
import pandas as pd

from trader.research.candidates import high_52w


def fake_prep(closes):
    return type("P", (), {"close_df": pd.DataFrame(closes, index=pd.bdate_range("2024-01-01", periods=len(next(iter(closes.values())))))})()


def test_high_52w_is_one_at_a_high_and_ratio_below_it():
    up = np.linspace(100, 200, 300)
    drop = np.concatenate([np.linspace(100, 200, 250), np.full(50, 150.0)])
    s = high_52w.score(fake_prep({"UP": up, "DROP": drop}), window=252)
    assert np.isnan(s[:251]).all()  # needs a full window
    assert np.isclose(s[-1, 0], 1.0)  # rising series sits at its high
    assert np.isclose(s[-1, 1], 150 / 200)
    assert s[-1, 0] > s[-1, 1]  # closer to the high ranks higher


def test_resid_mom_rewards_market_neutral_drift_not_market_exposure():
    from trader.research.candidates import resid_mom

    n = 700
    rng = np.random.default_rng(3)
    rm = rng.normal(0.0005, 0.01, n)
    idx = pd.bdate_range("2023-01-02", periods=n)
    bench = 100 * np.cumprod(1 + rm)
    beta2 = 2.0 * rm + rng.normal(0, 0.002, n)  # pure market exposure, no own drift
    alpha = rm + 0.002 + rng.normal(0, 0.002, n)  # market plus steady own drift
    close = pd.DataFrame({"BETA2": 100 * np.cumprod(1 + beta2), "ALPHA": 100 * np.cumprod(1 + alpha)}, index=idx)
    prep = type("P", (), {"close_df": close, "bench_close": bench})()
    s = resid_mom.score(prep, lookback=252, skip=21)
    assert np.isnan(s[:300]).all()  # needs the beta window plus the lookback
    assert s[-1, 1] > s[-1, 0] + 1  # own drift ranks well above plain market exposure


def test_sector_mom_ranks_by_sector_and_breaks_ties_by_own_return():
    from trader.research.candidates import sector_mom

    idx = pd.bdate_range("2024-01-01", periods=300)
    t = np.arange(300)
    close = pd.DataFrame({
        "A1": 100 * 1.004 ** t, "A2": 100 * 1.003 ** t,  # hot sector A
        "B1": 100 * 1.0005 ** t, "B2": 100 * 1.0004 ** t,  # slow sector B
    }, index=idx)
    prep = type("P", (), {"close_df": close, "sectors": ["A", "A", "B", "B"]})()
    s = sector_mom.score(prep, lookback=126, skip=21)[-1]
    assert min(s[0], s[1]) > max(s[2], s[3])  # every stock in the hot sector outranks the slow sector
    assert s[0] > s[1] and s[2] > s[3]  # inside a sector the own return breaks the tie


def test_nse_style_mom_prefers_smooth_riser_over_wild_one_with_same_return():
    from trader.research.candidates import nse_style_mom

    n = 400
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2023-01-02", periods=n)
    steady = 100 * np.exp(np.cumsum(np.full(n, 0.0010) + rng.normal(0, 0.002, n)))
    wild = 100 * np.exp(np.cumsum(np.full(n, 0.0010) + rng.normal(0, 0.03, n)))
    flat = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    close = pd.DataFrame({"STEADY": steady, "WILD": wild, "FLAT": flat, "OTHER": flat * 1.1}, index=idx)
    s = nse_style_mom.score(type("P", (), {"close_df": close})())
    assert np.isnan(s[:251]).all()  # 12-month window needed
    assert s[-1, 0] > s[-1, 1]  # same drift, lower volatility ranks higher


def test_market_context_reports_regime_and_trend():
    from trader.research import context

    n = 400
    idx = pd.bdate_range("2023-01-02", periods=n)
    up = pd.Series(100 * 1.001 ** np.arange(n), index=idx)
    ctx = context.market_context(up)
    assert ctx["regime"] == "bull" and ctx["vs_200sma_pct"] > 0 and ctx["return_12m_pct"] > 0
    assert ctx["drawdown_from_52w_high_pct"] == 0
    down = pd.Series(100 * 0.999 ** np.arange(n), index=idx)
    assert context.market_context(down)["regime"] == "bear"
    assert "regime" in context.render(ctx)
