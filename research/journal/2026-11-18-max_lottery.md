# max_lottery (2026-11-18) — FAIL (trial 3)

**Hypothesis.** Lottery-like stocks (large recent max daily returns) are overpriced; hold the lowest-MAX stocks.
**Source.** Bali, Cakici, Whitelaw, JFE 99(2) 2011 (NBER w14804, seen via search; abstract only). India evidence indirect/mixed (research/india_evidence.md). Seed idea US-centred.
**Small-account fit (before testing).** top_n 10, buffer 5, monthly; flagged risk: low-MAX picks are calm, often high-priced stocks, INR 500 slots may leave cash idle.
**Grid (fixed before eval).** mean of 5 largest daily returns over 21 and 63 sessions.

## Gates (INR 5,000 + 5,000/month, liquid top 100, OOS 2021-2026)
| gate | result |
|---|---|
| no_lookahead | pass |
| beats_index_and_basket | FAIL: 3.54% vs 12.9% / 16.3% |
| beats_index_most_years | FAIL: 1/6 |
| beats_random_picks | FAIL: vs random median 5.1% |
| robust_across_grid | FAIL: 4.8% and 4.5% |
| deflated_sharpe | FAIL 0.593 (3 trials) |
| charges_under_3pct | pass 2.38%/yr (high, 209 trades) |
| not_a_duplicate | pass, corr 0.54 |

Controls: index 12.9%, basket 16.3%, random median 5.05%, default momentum 11.2%, full universe 4.6%. 25,000: 4.5% (0/6); 100,000: 7.2% (0/6); merit no.

## Learned
- Fails at every account size and below random picks, so it is not an affordability artefact: avoiding lottery stocks did not earn a premium in this NIFTY 500 sample (consistent with the mixed Indian evidence). Charges are 2.4%/yr, near the 3% limit, from the monthly churn of a noisy 1-month signal. No variant proposed.

## Market context (informational only)
as_of 2026-11-17, regime neutral, NIFTY 500 close 23822.3 (+4.57% vs 200-SMA, SMA50 not rising), returns 1m 7.4% / 3m 0.96% / 6m 5.73% / 12m 1.31%, drawdown from 52w high -1.15%, vol 20d 14.3% / 1y 14.7% ann, liquid stocks 442, 52.3% above 200-SMA, 17.2% within 5% of 52w high.
