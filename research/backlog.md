# Research backlog

One idea per `/research` run, top to bottom. Add your own ideas under "Queue" (one line is enough): user ideas are tested first.
Move an idea to "Done" with its verdict after it is tested.

Data available: daily OHLCV, sector, dated fundamentals snapshots (from 2026-11-18 on: forward-only, no backtest).
Not available: point-in-time fundamentals history, intraday, options, news.

Research history was cleared on 2026-11-18 at the user's request. The previous journal, trial registry and candidates are in
the scratch archive /opt/data/cache/scratch/research_archive_20261118T011039 and in git history.

## Queue
(empty: refill on the next run)

Queue refill rule: when fewer than 3 untested price/volume ideas remain, `/research` searches for sources (SSRN/NBER, Quantpedia,
AQR, arXiv q-fin, NSE/BSE methodologies, Indian journals), at most 5 new rows per run, each with a stated mechanism and an opened source.

| slug | idea | mechanism | source |
|---|---|---|---|

## Done

| slug | date | verdict | note |
|---|---|---|---|
| frog_pan | 2026-11-18 | FAIL (trial 1) | 10.7% vs index 12.9%; 3/6 years; grid below index. Journal 2026-11-18-frog_pan. |
| int_mom | 2026-11-18 | FAIL (trial 2) | 12.66% vs index 12.9%; Q grid point 8.9%; DSR 0.938. Journal 2026-11-18-int_mom. |
| max_lottery | 2026-11-18 | FAIL (trial 3) | 3.54% vs index 12.9%, below random picks at every account size. Journal 2026-11-18-max_lottery. |
| trend_ma | 2026-11-18 | FAIL (trial 4) | 13.68% vs index 12.9%; DSR 0.820 (need 0.95); quarterly grid point 7.7%. Summary reports/research/trend_ma/summary.md. |
| str_rev | 2026-11-18 | FAIL (trial 5) | -6.31% CAGR vs index 12.74%; charges 4.41%/yr; DSR 0.019. Journal 2026-11-18-str_rev. |

## Ideas that came out of results
- frog_pan_winners: ID rank applied only to PRET>0 stocks (smooth losers were rewarded in frog_pan). New trial.
