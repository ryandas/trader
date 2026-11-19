# quality_india (2026-11-19)

## Hypothesis
Profitable, low-leverage firms are mispriced relative to their quality. Long-only top-10 by mean percentile rank of ROE,
operating margin and inverted debt/equity, rebalanced quarterly (buffer 5). Forward-only: fundamentals exist only as dated
snapshots (first 2026-11-18), so there is no backtest.

## Source
SSRN 4284686 (quality factor in India). Only the abstract was seen via search (QMJ four-factor alpha 0.92%/month, long-only
0.69%/month); full text not opened. Working paper; effects often weaken after publication. The seed idea was written from
US-centred memory.

## Checks before testing (no backtest results used)
- (a) Evidence outside the US: see `research/india_evidence.md` (SSRN 4284686 is an Indian study; abstract only).
  The refill searches in this run found nothing new that qualified (see below).
- (b) Small account fit: 10 names quarterly. Turnover is low, but each sale pays INR 15.34, which the gate reports as
  estimated charges of 3.81% / 9.52% / 19.03% a year at 10% / 25% / 50% monthly turnover at INR 5,000. Quarterly cadence
  and a buffer of 5 were fixed before evaluation. Known weakness: yfinance ROE / margin / D/E are today's trailing figures
  with no publication dates and an unclear lag.

## Queue refill
The price/volume queue was empty. Two searches (Quantpedia / emerging-market factors; Indian NSE anomaly studies) found
only ideas that were already tested (low vol, momentum), near-duplicates (short-term momentum in liquid stocks, Atilgan et
al. EM momentum) or not implementable on the current prep (Amihud illiquidity, NMIMS study: `MomPrep` has no volume
matrix). No new rows were added. Next run should consider adding a volume matrix to the prep before queueing liquidity ideas.

## Grid (fixed before evaluation)
`[{"top_n": 10, "buffer": 5, "rebalance": "Q"}]`

## Market context (informational only)
as_of 2026-11-19, regime bull, close 23897.2, 4.86% above 200 SMA, SMA50 rising, 1m +8.42%, 3m +1.81%, 6m +6.11%,
12m +1.27%, drawdown from 52w high -0.84%, 20d vol 13.5%, 1y vol 14.8%, liquid stocks 449, 52.8% above 200 SMA,
18.3% within 5% of 52w high.

## Gates
| gate | result | detail |
|---|---|---|
| no_lookahead | pass | identical on 5 truncations |
| has_fundamentals_snapshots | pass | 1 snapshot on file |
| not_a_duplicate | pass | rank correlation with momentum score 0.03 |

Controls (index, basket, random, default momentum) are not computed: no backtest exists for a fundamentals candidate.

## Verdict
FORWARD_ONLY. Not promoted: awaiting approval to promote quality_india (scheduled run; owner promotes manually).
This is permission to paper trade, not evidence of an edge. Trial count after this run: 7.

## Learned
The passing gates only mean the code is lookahead-free, snapshots exist and the ranking is not a momentum copy. Nothing
about performance is known until forward paper data accumulates. Fundamentals fields are today's yfinance values, so
quality ranks may be noisy or stale.
