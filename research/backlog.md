# Research backlog

One idea per `/research` run, top to bottom. Add your own ideas under "Queue" (one line is enough): user ideas are tested first.
Move an idea to "Done" with its verdict after it is tested.

Data available: daily OHLCV, sector, dated fundamentals snapshots (from 2026-11-18 on: forward-only, no backtest).
Not available: point-in-time fundamentals history, intraday, options, news.

Research history was cleared on 2026-11-18 at the user's request. The previous journal, trial registry and candidates are in
the scratch archive /opt/data/cache/scratch/research_archive_20261118T011039 and in git history.

## Queue

Queue refill rule: when fewer than 3 untested price/volume ideas remain, `/research` searches for sources (SSRN/NBER, Quantpedia,
AQR, arXiv q-fin, NSE/BSE methodologies, Indian journals), at most 5 new rows per run, each with a stated mechanism and an opened source.

| slug | idea | mechanism | source |
|---|---|---|---|
| vol_mom | Volatility-managed momentum, ranking version: score = 12-1 month momentum divided by trailing realised daily volatility (window 63 or 126 sessions). Grid (fixed now): top_n 5 buffer 2 or top_n 10 buffer 5, each with window 63 and 126, rebalance M, bear_exit on. NOTE: the rotation contract ranks names; it cannot scale exposure, so the tested idea is the risk-adjusted ranking, not position scaling. | Momentum crashes are concentrated in high-volatility periods, so dividing by volatility should cut crash losses and keep the average return. | Barroso & Santa-Clara (2015), 'Momentum has its moments', JFE 116(1) (cited in the Moskowitz-style volatility-scaling literature; abstract seen via search 2026-11-18, full text not opened). India: none found. |
| regime_switch | Regime-switched momentum and reversal: when the index is in a calm state use 12-1 momentum, in a crash state use 1-month reversal. Proxy (deviation from paper): crash state = index 20-day volatility above its trailing 1-year 80th (or 90th) percentile. The paper uses a Hidden Markov Model; this proxy avoids a new dependency and is a separate idea. Grid (fixed now): calm/crash percentile 0.8 or 0.9, top_n 10, buffer 5, rebalance M, bear_exit on. | Momentum and reversal are regime-dependent complements; momentum's information coefficient drops in crashes while reversal's rises (paper abstract). | Regime-Dependent Price Formation in Indian Equities (SSRN abstract 7044244, posted 2 Jul 2026, working paper; abstract opened 2026-11-18, full text not read). |

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
