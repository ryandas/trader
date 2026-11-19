# regime_switch (2026-11-19) — FAIL

## Hypothesis and source
Momentum and 1-month reversal are regime-dependent complements: use 12-1 momentum when the index is calm, minus the 1-month return when index volatility is extreme. Source: Regime-Dependent Price Formation in Indian Equities, SSRN abstract 7044244 (working paper, abstract only, full text not read). Deviation: crash state = NIFTY 500 20-day volatility above its trailing 1-year percentile (HMM not used). The seed ideas were written from US-centred memory; this one is India-specific but unreplicated.

## Checks (made before any backtest)
- (a) Outside-US evidence: only the SSRN abstract; no independent replication found. Indian 1-month reversal evidence is mixed and concentrated in losers (see research/india_evidence.md).
- (b) Small-account fit: top_n 10, buffer 5, monthly. Reversal in crash states adds turnover; each sale pays INR 15.34, so the cost is real at INR 5,000 but charges were expected to stay modest with 10 names and a buffer.

## Grid (fixed before evaluation)
pct in {0.8, 0.9}, top_n 10, buffer 5, rebalance M, bear_exit on.

## Gates
| gate | result | detail |
|---|---|---|
| no_lookahead | pass | identical on 5 truncations |
| beats_index_and_basket | **FAIL** | candidate 13.3% vs index 12.74% vs equal-weight basket 16.1% |
| beats_index_most_years | pass | 4 of 6 years |
| beats_random_picks | pass | 13.3% vs 6.0% random median |
| robust_across_grid | pass | both points beat the index (13.72, 13.91) |
| deflated_sharpe | pass | DSR 0.976 after 1 trial |
| charges_under_3pct | pass | 1.91%/yr |
| not_a_duplicate | pass | correlation with default momentum 0.84 |

Controls: index 12.74%, equal-weight basket 16.13%, random picks 6.02%, default momentum 11.28%, full universe 15.8%. Max drawdown -22.9%, 183 trades.

## Verdict
FAIL, decided by `beats_index_and_basket`: it lost to the equal-weight basket (16.1%), i.e. no better than holding the universe. Not a cost effect (charges 1.9%/yr). At INR 25,000 CAGR was 15.6% and at 100,000 16.7%, still below or near the basket. A backtest is not evidence; the universe is today's NIFTY 500 with survivorship bias only partly reduced by point-in-time membership.

## What I learned
Switching to reversal in high-volatility periods did not beat simply holding the basket. Beating the index in 4 of 6 years with 0.84 correlation to default momentum suggests the switch added little. No variant is re-run this session.

## Market context
as_of 2026-11-18, regime bull, NIFTY 500 close 23630.2, 3.71% above 200 SMA, 50 SMA rising; returns 1m 6.11%, 3m 0.28%, 6m 5.21%, 12m 0.46%; 1.95% below 52-week high; 20d vol 14.1% ann, 1y vol 14.7%; liquid stocks 446, 50.0% above 200 SMA, 16.4% within 5% of 52-week high.
