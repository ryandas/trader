# Research backlog

One idea per `/research` run, top to bottom. Add your own ideas under "Queue" (one line is enough): user ideas are tested first.
Move an idea to "Done" with its verdict after it is tested.

Data available: daily OHLCV, sector, dated fundamentals snapshots (from 2026-11-18 on: forward-only, no backtest).
Not available: point-in-time fundamentals history, intraday, options, news.

Research history was cleared twice on 2026-11-18 at the user's request (first: journal, registry and candidates; second: registry
and journal again, candidates kept). Earlier material is in git history and the scratch archive
/opt/data/cache/scratch/research_archive_20261118T011039. Trials and results now live in Postgres (`trader research-status`,
`trader show research-eval <slug> summary`).

## Queue

Queue refill rule: when fewer than 3 untested price/volume ideas remain, `/research` searches for sources (SSRN/NBER, Quantpedia,
AQR, arXiv q-fin, NSE/BSE methodologies, Indian journals), at most 5 new rows per run, each with a stated mechanism and an opened source.

| slug | idea | mechanism | source |
|---|---|---|---|
| int_mom | Interaction momentum: rank by corr(return, volume) over lookback, long corr>0. | High volume accompanies rises; sustains due to info. | SSRN, prior trial at 5k. |
| max_lottery | Max daily return in lookback: long top-N by highest 1-day return in past month. | Lottery demand drives extremes. | SSRN, prior trial at 5k. |
| trend_ma | Trend MA: buy if close > 200 SMA and momentum > 0, hold, exit at stop. | Simple trend-following. | Backtest-only, prior trial at 5k. |
| str_rev | Short-term reversal: rank by prior 1-week return (reverse), 1-month hold. | Microstructure reversal within week. | Blitz & Liu, prior trial at 5k. |
| vol_mom | Volatility-managed momentum: rank by return / realized volatility, long top-N, 1-month hold. | Sharpe-like scoring; volatility drag penalizes high-vol winners. | Academic factor, prior trial at 5k. |
| frog_pan_winners | Frog-in-the-pan applied only to PRET>0 (profitable) stocks: ID rank among winners, avoid losers. | Reversion is smoother in profitable companies. | Derivative of frog_pan trial result. |

## Done

| slug | date | verdict | note |
|---|---|---|---|
| regime_switch | 2026-11-19 | FAIL | beats_index_and_basket: 13.3% vs index 12.74% vs basket 16.1%; other gates passed (DSR 0.976, 1 trial). Not a cost effect. |
| low_vol | 2026-11-19 | FAIL | beats_index_and_basket: 1.52% vs index 12.74% vs basket 16.1%; DSR 0.642 (2 trials). Not a cost effect (charges 0.35%/yr); exposure only 25-35% (bear exit / regime filter). |
| high_52w | 2026-11-19 | FAIL | beats_index_and_basket: 11.21% vs index 12.74% vs basket 16.1%; DSR 0.884 (3 trials). Partly cost: 2.22%/yr charges at 5,000; 14.6% at 25,000. Correlation with momentum 0.72. |
| sector_mom | 2026-11-19 | FAIL | beats_index_and_basket: 9.71% vs index 12.74% vs basket 16.1%; DSR 0.808 (4 trials). Not a cost effect (charges 0.55%/yr); exposure only 19-47%. |
| ew_winners_top20 | 2026-11-19 | FAIL | beats_index_and_basket: 9.62% vs index 12.74% vs basket 16.1%; DSR 0.818 (5 trials). Partly cost: 2.12%/yr charges at 5,000; 12.8% at 25,000, 16.6% at 100,000 (but fails most-years gate). Correlation with momentum 0.85. |

| nse_norm_mom | 2026-11-19 | FAIL | beats_index_and_basket: 6.9% vs index 12.74% vs basket 16.1%; DSR 0.784 (6 trials). Not a cost effect (charges 0.62%/yr; no better at 100,000). Exposure low (bear exit / regime filter). Correlation with momentum 0.85. |
| quality_india | 2026-11-19 | FORWARD_ONLY | Fundamentals, no backtest. Gates: no_lookahead, snapshots (1), not_a_duplicate (corr 0.03) all pass. Trial 7. Awaiting approval to promote. |
| frog_pan | 2026-11-20 | FAIL | beats_index_and_basket: 10.73% vs index 13.09% vs basket 16.5%; also most-years (3/6), grid robustness, DSR 0.947 (8 trials). Charges 1.02%/yr, not a cost effect. 25k: 15.0%, 100k: 16.6% (informational). |

Fresh start 2026-11-18 (second reset, at the user's request): the trial registry (now counting from 0) and the journal were
emptied, and the Done table below was cleared. The earlier verdicts (frog_pan, int_mom, max_lottery, trend_ma, str_rev,
vol_mom: all FAIL at INR 5,000; see `git log -- research/backlog.md research/journal`) are no longer counted. Their candidate
modules are still in `src/trader/research/candidates/` and are not queued; add a row to Queue to re-evaluate one.

## Ideas that came out of results
- frog_pan_winners: ID rank applied only to PRET>0 stocks (smooth losers were rewarded in frog_pan). New trial.
