# sector_mom (2026-11-19) — FAIL

## Hypothesis
Industry momentum: stocks in sectors with strong trailing 6-1 month return (sector median) keep outperforming; ties within a sector broken by own 12-1 return.

## Source and checks
- Moskowitz and Grinblatt (1999, JF 54(4)), seen cited, not opened. India: Garg and Varshney (2015, Global Business Review), abstract seen; CFA digest on 50 NSE stocks. See `research/india_evidence.md`. The seed idea came from US-centred memory; Indian evidence is abstracts only.
- Small account: top 10, buffer 5, quarterly or semi-annual cadence, so few sales (flat INR 15.34 DP per sale). Fixed before evaluating.
- Sector column: present in prep (`instruments.sector`); unknown-sector stocks are never bought; sector median needs >= 3 members.

## Grid (fixed before evaluation)
`top_n 10, buffer 5`, rebalance Q or S.

## Gates
| gate | result | detail |
|---|---|---|
| no_lookahead | pass | 5 truncations |
| beats_index_and_basket | FAIL | 9.71% vs index 12.74% vs basket 16.1% |
| beats_index_most_years | FAIL | 2 of 6 |
| beats_random_picks | pass | 9.71% vs 4.0% |
| robust_across_grid | FAIL | Q 9.7%, S 8.4%, both below index |
| deflated_sharpe | FAIL | 0.808 (need 0.95), 4 trials |
| charges_under_3pct | pass | 0.55%/yr |
| not_a_duplicate | pass | corr with default momentum 0.78 |

## Controls
Index 12.74%, equal-weight basket 16.13%, random-pick median 4.03%, default momentum 11.28%, full universe 8.06%.
At INR 25,000: 11.5% CAGR (3/6 years); at 100,000: 11.48% (2/6).

## Market context (informational only)
as_of 2026-11-18, regime bull, NIFTY 500 close 23630.2 (+3.71% vs 200 SMA, sma50 rising), 1m +6.11%, 3m +0.28%, 6m +5.21%, 12m +0.46%, drawdown from 52w high -1.95%, 20d vol 14.1%, 1y vol 14.7%, 446 liquid stocks, 50.0% above 200 SMA, 16.4% within 5% of 52w high.

## Verdict and learning
FAIL on beating index and basket. Not a cost effect (charges 0.55%/yr). Exposure was low in most OOS years (19-47%) because of the bear-exit and regime filters, which caps returns in a mostly rising index. Beat random picks but not the index. A backtest result is not evidence of an edge (survivorship bias remains).
