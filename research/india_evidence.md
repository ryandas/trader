# Indian-market evidence (search round 2026-11-18)

Standard-mode web searches, snippets only. Some sources are blog or student-project level and are marked. The NSE methodology
PDFs themselves were not opened, so details from secondary sources are marked (secondary). Append new findings here; do not
treat anything here as a backtest result.

## Momentum (supported, with caveats)
- **NSE Nifty200 Momentum 30** (launched 2020-08-25): the score is the 6-month and 12-month price return **adjusted for
  volatility**, z-scored across eligible stocks (z-score detail: secondary, Freefincal); top 30 of the Nifty 200 with at least a
  year of history; weights = free-float market cap x score; **rebalanced semi-annually (June, December)**. Sources:
  [NSE factsheet](https://www.niftyindices.com/Factsheet/Factsheet_Nifty200_Momentum30.pdf),
  [Freefincal write-up](https://freefincal.com/nifty200-momentum-30-index-a-new-strategy-index-from-the-nse/).
- Academic: Maheshwari & Dhankar (2017) find momentum profits on NSE data, driven by the winner side, not explained by size,
  value or illiquidity; Garg & Varshney (2015) find it robust 2000-2013; Joshipura finds 6- and 12-month momentum 1995-2008.
  Profits weakest in January. An ISB analysis finds overreaction (reversal) only in mid-caps; momentum is generally weaker in
  emerging than developed markets. Sources via [ISB blog](https://blogs.isb.edu/blog/2012/04/17/momentum-and-overreaction-in-indian-capital-markets/),
  [IIMB Review](https://iimb.ac.in/imr/previous-issues/momentum-march-2020.php),
  [NSE research paper](https://nsearchives.nseindia.com/content/research/res_paperfinal223.pdf).

## Low volatility (mixed)
- **NSE Nifty100 Low Volatility 30**: lowest 1-year standard deviation of daily log returns, top 30 of the Nifty 100, quarterly review.
  [Methodology PDF](https://cdn.freefincal.com/wp-content/uploads/2018/07/Nifty100_LowVolatility30.pdf).
- For: Peswani & Joshipura (NSE, 1997-2018) find high risk-adjusted returns, not confined to small or illiquid stocks.
  Against: Pandey & Samanta (S&P CNX 100, 2001-2014) find no anomaly, high-volatility quintiles earned more.
  Our `low_vol` trial (2021-2026) failing is consistent with mixed evidence, not a contradiction.

## 52-week high (thin)
- No rigorous NSE test of George & Hwang found. One small MBA project (25 stocks per side, 2006-2010) found no short-term
  effect and a medium/long-term effect. Treat as no evidence either way.

## Factor data (a possible tool, not a strategy)
- IIM Ahmedabad data library (Agarwalla, Jacob & Varma): free Indian Fama-French size/value/momentum factor returns from CMIE
  Prowess, 1993 onward, with survivorship-adjusted values. Useful for checking whether the momentum premium existed in a
  given period, not for choosing stocks. [Library](https://faculty.iima.ac.in/~iffm/Indian-Fama-French-Momentum/).

## What this means for the backlog
1. The one idea with an Indian index behind it and the best fit for our cost problem is **NSE-style momentum**: volatility-adjusted
   blend of 6- and 12-month returns on a **slow (semi-annual or quarterly) cadence**. Slow cadence directly attacks the flat
   INR 15.34 sale charge. The engine only supports monthly and weekly rebalancing today; "Q" and "S" cadences need a small
   addition to `momentum.py` before this can be tested.
2. `vol_scaled_mom` and `mom_12_1` are subsumed by it and are merged.
3. `high_52w` and its slower variant: no Indian support, lowest priority.
4. `low_vol`: mixed evidence and already failed here; do not retry unless a new angle appears.
