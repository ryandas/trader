# Research backlog

One idea per `/research` run, top to bottom. **Add your own ideas anywhere under "Queue" (one line is enough):
user ideas are tested before everything else.** Move an idea to "Done" with its verdict after it is tested.

Data available: daily OHLCV, sector, dated fundamentals snapshots (from 2026-11-18 on: forward-only, no backtest).
Not available: point-in-time fundamentals history, intraday, options, news.
Citations below were written from memory when the backlog was seeded: confirm each one with a quick search before
relying on it, and fix this file if one is wrong.

## How these ideas were chosen
The seed list (2026-11-18) was written by Claude from memory of well-known academic factor research, not found by search
and not taken from Indian-market studies: price/volume only, slow rotation (fixed INR 15.34 sale charge), a published
mechanism, roughly most famous first. Citations of tested ideas were verified by search; the rest still need checking.
Known weaknesses: US-centred evidence, grid values inherited from the default momentum setup, and no design for the
INR 5,000 account. `/research` now checks Indian-market evidence and small-account fit before each test (step 2).
Add your own ideas to the Queue; they are tested first.

## Queue
Queue refill rule: when fewer than 3 untested price/volume ideas remain, `/research` searches (SSRN/NBER, Quantpedia, AQR, arXiv, NSE/BSE methodologies and research, Indian journals), at most 5 new rows per run, each with a stated mechanism and an opened source. Never social media or tip sites; never by recent performance. Currently 2 price ideas are queued, so the next run should refill.
Indian-market evidence for these ideas is in `research/india_evidence.md` (search round 2026-11-18). Order below reflects it: `nse_style_mom` first.

| slug | idea | mechanism | source |
|---|---|---|---|
| winners_pullback | among the top momentum quintile, prefer those with the weakest last month | short-term reversal inside winners buys strength on a dip | Jegadeesh (1990), "Evidence of Predictable Behavior of Security Returns", J. Finance |
| mom_weekly | the default momentum rule rebalanced weekly | faster cadence; probably costs too much at INR 5,000 and will fail the duplicate gate | Jegadeesh & Titman (1993) holding-period results |
| quality_momentum (fundamentals, forward-only) | momentum restricted to stocks with ROE > 15% and debt/equity < 100 (yfinance reports it in percent) | high-quality firms' momentum is more persistent; screens out leveraged lottery winners | Asness, Frazzini & Pedersen (2019), "Quality Minus Junk", Rev. Accounting Studies; NSE Nifty200 Quality 30 methodology |
| quality_rank (fundamentals, forward-only) | composite rank of ROE, operating margin and low leverage | profitable, safe companies earn higher risk-adjusted returns | same as above |

Fundamentals ideas set `META["uses_fundamentals"] = True` and a single grid point (nothing to choose with); they can only
be forward paper tested, and their snapshots must exist (`uv run trader fundamentals-snapshot`).

## Done

| slug | date | verdict | note |
|---|---|---|---|
| low_vol | 2026-11-18 | FAIL (v2 re-run also FAIL) | OOS CAGR -1.0% vs index 12.9%; exposure was only 0.3-14%: at INR 500 per slot the calm, expensive stocks cannot be bought one whole share at a time. At 25,000 it earned 2.3% and at 100,000 3.9%, still far below the index, so it also fails with enough capital (merit: no) |
| high_52w | 2026-11-18 | FAIL | charges 6.6%/yr at INR 5,000 (119 trades); 100,000 run 16.5% vs index 12.9% but only 0.2 above the survivorship-flattered basket, 4/6 years: a lead, not evidence |
| resid_mom | 2026-11-18 | FAIL | 6.8% vs index 12.9% at INR 5,000; 0.87 correlated with default momentum; merit at 100,000: no |
| sector_mom (was sector_rel_mom) | 2026-11-18 | FAIL | 8.2% vs index 12.9% at INR 5,000; at 100,000 17.1% (4/6 years) but max drawdown -35%; merit yes, thin margin over basket |
| nse_style_mom | 2026-11-18 | FAIL | v1 2.7% (harness bias), v2 7.9% vs index 12.9% at INR 5,000; charges 1.6%/yr; 1 of 6 years beating the index |

## Ideas that came out of results (variants count as new trials)

- DONE 2026-11-18: harness v2 (warm start) fixed the restart-from-cash bias; all five trials re-run as new counted trials, all still FAIL (see research/journal/2026-11-18-harness-v2.md).
- (low priority: no Indian-market support found) high_52w_slow: the same rule with fewer slots / wider buffer / quarterly rebalance to cut turnover (new trial; decide its grid before running).
