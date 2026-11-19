# nse_norm_mom (2026-11-19) — FAIL

## Hypothesis
Volatility-adjusted momentum over two horizons (6-1 and 12-1 months, mean of cross-sectional z-scores of return / daily vol) ranks smooth winners above jumpy ones and should lower momentum-crash risk versus raw 6-1 ranking.

## Source and checks
- NSE Indices Nifty500 Momentum 50 (launched 2024-06-04): normalized momentum score from 6- and 12-month volatility-adjusted returns, 50/50 z-score average, semi-annual rebalance. Seen in search results 2026-11-19 (niftyindices factsheet, press release and secondary pages; official methodology PDF not opened). Index provider document, not a performance claim. The index itself is cap/score weighted with 50 names; this candidate is an equal-weight 10-name approximation, so it is not a replication.
- Evidence outside the US: the source is Indian by construction, but no independent Indian performance test of the normalized score was found. Seed ideas were written from US-centred memory.
- Small account: 10 names at INR 5,000 is ~INR 500 per name (DP charge ~3% per sale). Grid fixed before evaluating: w1 126, w2 252, skip 21, top 10, buffer 5, rebalance S (semi-annual) or Q (quarterly).

## Gates
| gate | result | detail |
|---|---|---|
| no_lookahead | pass | 5 truncations |
| beats_index_and_basket | FAIL | 6.9% vs index 12.74% vs basket 16.1% |
| beats_index_most_years | FAIL | 2 of 6 |
| beats_random_picks | pass | 6.9% vs 2.0% |
| robust_across_grid | FAIL | S 4.7%, Q 6.9% (both below index) |
| deflated_sharpe | FAIL | 0.784 (need 0.95), 6 trials |
| charges_under_3pct | pass | 0.62%/yr |
| not_a_duplicate | pass | corr with default momentum 0.85 |

## Controls
Index 12.74%, basket 16.13%, random median 2.04%, default momentum 11.28%, full universe 3.98%.
By account size: 5,000 -> 6.9%; 25,000 -> 8.21%; 100,000 -> 6.11%. No merit at any size.

## Market context (informational only)
as_of 2026-11-18, regime bull, close 23630.2 (+3.71% vs 200 SMA), 1m +6.11%, 3m +0.28%, 6m +5.21%, 12m +0.46%, drawdown -1.95%, 20d vol 14.1%, 1y vol 14.7%, 446 liquid stocks, 50.0% above 200 SMA, 16.4% within 5% of 52w high.

## Verdict and learning
FAIL on beats_index_and_basket. Not a cost effect: charges only 0.62%/yr and the result does not improve with account size (6.1% at 100,000). Exposure was low in several years (1-50%) because of the engine's bear exit / regime filter, which probably drives much of the shortfall, as with low_vol and sector_mom. Correlation 0.85 with default momentum, so mostly the same bet. Not evidence of an edge either way.

## Queue refill
Searched; no new backtestable (price/volume) idea with an opened source found. Only a forward-only quality idea was noted (see backlog).
