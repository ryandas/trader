"""Low-volatility rotation: hold the calmest stocks (lowest trailing daily-return volatility)."""
META = {
    "slug": "low_vol",
    "kind": "rotation",
    "hypothesis": "Stocks with low trailing volatility earn equal or better risk-adjusted returns than volatile ones "
                  "(lottery preference and leverage constraints push investors to overpay for high-vol stocks).",
    "source": "Baker, Bradley & Wurgler (2011) 'Benchmarks as Limits to Arbitrage'; Ang et al. (2006) 'The Cross-Section of "
              "Volatility and Expected Returns'; NSE Nifty100 Low Volatility 30 index methodology.",
    "grid": [{"window": 252}, {"window": 126}],  # fixed before looking at any result
}


def score(prep, window: int = 252):
    ret = prep.close_df.pct_change()
    vol = ret.rolling(window, min_periods=window).std()
    return (-vol).to_numpy()
