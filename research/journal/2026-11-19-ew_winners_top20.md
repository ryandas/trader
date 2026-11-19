# ew_winners_top20 (2026-11-19) — FAIL

## Hypothesis
Equal-weighted, monthly-rebalanced long-only winners (12-1 momentum) of 20-30 names keep factor alpha after costs in India.

## Source and checks
- Raju and Teli, SSRN 4000418 (Jan 2022; abstract and intro opened 2026-11-19). Practitioner-authored working paper, full text not read. Indian evidence, so not US-only. Plyakha et al. 2014 seen cited.
- Small account: 20-30 names against INR 5,000 means ~INR 170-250 per position, so the flat INR 15.34 DP charge per sale is ~6-9% of a position. Expected to be cost-heavy; the grid was still fixed per the backlog row (top_n 20 or 30, buffer 10, monthly, 12-1 score = lookback 252, skip 21) before evaluating. Note the live momentum sleeve scores 6-1; this idea uses 12-1 as written in the row.

## Gates
| gate | result | detail |
|---|---|---|
| no_lookahead | pass | 5 truncations |
| beats_index_and_basket | FAIL | 9.62% vs index 12.74% vs basket 16.1% |
| beats_index_most_years | FAIL | 3 of 6 |
| beats_random_picks | pass | 9.62% vs 5.4% |
| robust_across_grid | FAIL | top20 10.9%, top30 8.6% |
| deflated_sharpe | FAIL | 0.818 (need 0.95), 5 trials |
| charges_under_3pct | pass | 2.12%/yr |
| not_a_duplicate | pass | corr with default momentum 0.85 |

## Controls
Index 12.74%, basket 16.13%, random median 5.43%, default momentum 11.28%, full universe 14.9%.
By account size: 5,000 -> 9.62%; 25,000 -> 12.76% (5/6 years beat index, still below basket 16.13%); 100,000 -> 16.59% (3/6 years, fails most-years gate).

## Market context (informational only)
as_of 2026-11-18, regime bull, close 23630.2 (+3.71% vs 200 SMA), 1m +6.11%, 3m +0.28%, 6m +5.21%, 12m +0.46%, drawdown -1.95%, 20d vol 14.1%, 446 liquid stocks, 50.0% above 200 SMA, 16.4% within 5% of 52w high.

## Verdict and learning
FAIL on beats_index_and_basket. Partly a cost/affordability effect: charges 2.12%/yr and 246 trades at INR 5,000, and the result improves with account size (16.6% at 100,000). But at 100,000 it still fails the most-years gate, and correlation with default momentum is 0.85, so it is largely the same bet. Not evidence of an edge.
