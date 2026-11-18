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
| regime_switch | Regime-switched momentum and reversal: when the index is in a calm state use 12-1 momentum, in a crash state use 1-month reversal. Proxy (deviation from paper): crash state = index 20-day volatility above its trailing 1-year 80th (or 90th) percentile. The paper uses a Hidden Markov Model; this proxy avoids a new dependency and is a separate idea. Grid (fixed now): calm/crash percentile 0.8 or 0.9, top_n 10, buffer 5, rebalance M, bear_exit on. | Momentum and reversal are regime-dependent complements; momentum's information coefficient drops in crashes while reversal's rises (paper abstract). | Regime-Dependent Price Formation in Indian Equities (SSRN abstract 7044244, posted 2 Jul 2026, working paper; abstract opened 2026-11-18, full text not read). |

## Done

| slug | date | verdict | note |
|---|---|---|---|

Fresh start 2026-11-18 (second reset, at the user's request): the trial registry (now counting from 0) and the journal were
emptied, and the Done table below was cleared. The earlier verdicts (frog_pan, int_mom, max_lottery, trend_ma, str_rev,
vol_mom: all FAIL at INR 5,000; see `git log -- research/backlog.md research/journal`) are no longer counted. Their candidate
modules are still in `src/trader/research/candidates/` and are not queued; add a row to Queue to re-evaluate one.

## Ideas that came out of results
- frog_pan_winners: ID rank applied only to PRET>0 stocks (smooth losers were rewarded in frog_pan). New trial.
