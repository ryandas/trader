# 2026-11-18: nse_style_mom (trial #5) - FAIL (with a harness caveat)

- **Hypothesis**: volatility-adjusted momentum on a slow cadence keeps the momentum edge while avoiding the flat sale charge.
- **Source**: NSE Nifty200 Momentum 30 methodology (details secondary, see research/india_evidence.md); Barroso & Santa-Clara
  (2015); Jegadeesh & Titman (1993).
- **Indian-market evidence check**: found, see `research/india_evidence.md` (momentum supported in several NSE studies; NSE runs
  this index semi-annually).
- **Small-account fit check**: top 10, buffer 10, cadence S (Jun/Dec) or Q (quarterly); expected turnover low. Fixed before evaluating.
- **Grid** (fixed before any result): `{top_n 10, buffer 10, rebalance S}` and `{..., rebalance Q}`. Score: mean of the cross-sectionally
  z-scored (return / annualised volatility) over 126 and 252 sessions, no skip.
- **Setup**: liquid top-100, INR 5,000, real costs, walk-forward, OOS 2021-01-01 to 2026-11-17. Required adding "Q" and "S"
  rebalance cadences to `momentum.py` (live sleeve replay verified identical).

| gate | result |
|---|---|
| no_lookahead | pass |
| beats index and basket | FAIL: 2.7% vs 12.9% vs 16.3% |
| beats index in most years | FAIL: 2 of 6 |
| beats random picks | pass: 2.7% vs 1.8% |
| robust across grid | FAIL: S 2.7%, Q 6.3% |
| deflated Sharpe | FAIL: 0.43 after 5 counted trials |
| charges < 3% | pass: 0.27% a year (5 trades in 6 years) |
| not a duplicate | pass: 0.58 correlation with default momentum |

| account | candidate CAGR | index | basket | max DD | charges %/yr | years beating index |
|---|---|---|---|---|---|---|
| 5,000 | 2.7% | 12.9% | 16.3% | -14% | 0.27 | 2/6 |
| 25,000 | 10.1% | 12.9% | 16.3% | -25% | 0.5 | 3/6 |
| 100,000 | 11.9% | 12.9% | 16.3% | -29% | 0.28 | 3/6 |

## What happened
The cost fix worked (charges 0.27%), but exposure was 0-27% by year: the book was mostly cash.

## Harness caveat (bias against slow cadences) - NOT corrected in this run
Each walk-forward OOS year restarts from cash, and a strategy only buys at its own next signal. A semi-annual book therefore
sits idle for up to 6 months at the start of every test year (a quarterly one up to 3, a monthly one up to 1), which has
nothing to do with the idea. A continuously running sleeve would carry its holdings across year boundaries. So this result
understates slow strategies, and the earlier monthly results are understated less. It was discovered after seeing this
result, so it was not used to alter the evaluation inside this run; changing the harness would change the gates.

**Resolved:** the user approved the fix (harness v2) and all trials were re-run; see `2026-11-18-harness-v2.md` (nse_style_mom v2: 7.9% at INR 5,000, still FAIL).

Proposed fix (as it was then): force an initial rebalance on the first session of each OOS window (what a running
sleeve would already hold), apply it to every candidate, and re-run the five trials; the re-runs would count as new trials.

## Follow-up
None until the harness question is decided. Do not tune `nse_style_mom` around this result.
