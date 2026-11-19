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
| low_vol | Low-volatility ranking: lowest trailing realised daily volatility (top 10, quarterly, buffer 5; grid fixed: window 126 or 252). | Investors overpay for volatile/lottery-like stocks and leverage-constrained investors tilt to high beta, so low-risk names earn higher risk-adjusted returns. | NSE low-risk anomaly study Jan 2001-Jun 2016 (abstract seen via search 2026-11-19); Agarwalla et al. 2014 BAB India (seen cited). Journal articles; effect size sample-dependent. |
| high_52w | Nearness to 52-week high: close / trailing 252-bar max (top 10, buffer 5; grid fixed: rebalance M or Q). | Anchoring: investors under-react to news near the 52-week high, so near-high stocks keep outperforming. | George and Hwang (2004), Journal of Finance 59(4) (US; abstract seen via search 2026-11-19; no India ranking study found). Published effect may have weakened. Journal article. |

## Done

| slug | date | verdict | note |
|---|---|---|---|
| regime_switch | 2026-11-19 | FAIL | beats_index_and_basket: 13.3% vs index 12.74% vs basket 16.1%; other gates passed (DSR 0.976, 1 trial). Not a cost effect. |

Fresh start 2026-11-18 (second reset, at the user's request): the trial registry (now counting from 0) and the journal were
emptied, and the Done table below was cleared. The earlier verdicts (frog_pan, int_mom, max_lottery, trend_ma, str_rev,
vol_mom: all FAIL at INR 5,000; see `git log -- research/backlog.md research/journal`) are no longer counted. Their candidate
modules are still in `src/trader/research/candidates/` and are not queued; add a row to Queue to re-evaluate one.

## Ideas that came out of results
- frog_pan_winners: ID rank applied only to PRET>0 stocks (smooth losers were rewarded in frog_pan). New trial.
