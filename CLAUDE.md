# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A systematic NIFTY 500 trader (long-only, delivery equity). Python package `trader` (src layout, managed with `uv`). It is not a git repo. **Paper trading only: no real orders are placed by the code.**

Two strategy families exist, with different status (as of 2026-11-18):
- **Momentum rotation** (monthly, top-N by trailing return): the only sleeve in the paper ledger. Paper capital is INR 5,000 (`config.yaml`), 10 holdings, started forward-only on 2026-11-17; it holds cash until the first month-end signal (close of 2026-11-30, fills 2026-12-01). Its backtest is flattered by survivorship bias (see findings below).
- **Swing strategies** (`trend_pullback`, `breakout`, `mean_reversion` + regime/selector): built and tested but **removed from the paper ledger**. Walk-forward OOS showed they did not beat buy-and-hold after costs (CAGR -4.4% vs +12.9%), and at INR 5,000 they are unworkable (backtest 2021-2026: -34% CAGR, ending equity INR 434, charges 103% of starting capital, because the fixed INR 15.34 DP sell charge is ~6% of a ~INR 260 position). Re-add with `trader paper-init` if wanted.

Never present any signal as a recommendation to trade real money.

## Commands

```
uv sync                                  # install
uv run pytest -q                         # tests (94)
uv run pytest tests/test_fills_risk_costs.py::test_gap_through_stop_exits_at_open   # one test
uv run trader init                       # build NIFTY 500 -> Dhan securityId list (data/instruments.csv)
uv run trader update [SYMBOLS...]        # backfill/refresh daily candles (10y history); no args also refreshes the NIFTY500 benchmark
uv run trader backtest [--strategy NAME] [--from DATE] [--no-filters]   # --no-filters = unfiltered baseline
uv run trader walkforward                # 3y in-sample / 1y OOS folds; writes reports/walkforward/, data/params.json, data/selector_stats.json
uv run trader membership-snapshot       # save today's official NIFTY 500 list as a dated snapshot (run about monthly)
uv run trader membership-fetch          # prices for past NIFTY 500 members missing from data/candles (unavailable ones -> data/membership/unavailable.csv)
uv run trader momentum [--from DATE] [--liquid-top N] [--pit] [--top-n N ...]   # momentum rotation backtest (separate from the paper ledger)
uv run trader momentum-wf [--liquid-top N] [--pit]   # its walk-forward + robustness grid
uv run trader paper-momentum [--start DATE] [--liquid-top N] [--reset]   # start the momentum sleeve (params from config.yaml, then frozen). Changing config.yaml later does NOT affect a running sleeve: reset it.
uv run trader paper-init [--start DATE] [--reset]   # (optional) add the swing sleeve, freezing params + selector stats; --reset leaves momentum alone
uv run trader paper-drop-swing                      # remove the swing sleeve; momentum is kept
uv run trader daily [--asof DATE] [--no-update]     # update data, advance the ledger sleeves, write reports/<date>.md (~3 min with update)
uv run trader fundamentals-snapshot [--if-stale-days N]   # save today's fundamentals to data/fundamentals/<date>.parquet (a few minutes)
uv run trader research-eval SLUG [--recheck]        # fixed gates on a candidate in src/trader/research/candidates/; records a trial (--recheck = not counted)
uv run trader research-promote SLUG                 # freeze a PASS / FORWARD_ONLY candidate into the ledger as its own paper sleeve (max 5)
uv run trader research-retire SLUG                  # stop replaying a candidate sleeve
uv run trader market-context                        # market snapshot (regime, trend, returns, volatility, breadth); informational, pasted into research journals
uv run trader research-status                       # trial count, recent trials, candidate sleeves, data freshness, backlog head
```

`/daily` (`.claude/commands/daily.md`) runs the daily routine and summarises it. It is read-only.
`/research` (`.claude/commands/research.md`) runs one iteration of the research loop (see below). It writes candidate code, journal and backlog files and may promote a passing candidate to a paper sleeve; it never places orders.

## Architecture

Pipeline per day: **universe -> regime -> selector -> strategies -> risk -> fills**.

- `data/`: `sources.py` (`YFinanceSource` default, `DhanSource` needs paid plan; both behind the `CandleSource` protocol), `store.py` (parquet per symbol in `data/candles/`, incremental update, backward extension, split detection by re-fetching a 5-day overlap), `instruments.py` (NSE list + Dhan scrip master), `dhan.py`.
- `indicators.py`, `strategies/` (`features()` builds the per-symbol frame; each strategy returns a vectorised `SignalSet`). Strategies: `trend_pullback` (buy-stop), `breakout` and `mean_reversion` (buy next open).
- `universe.py` (daily top-N relative-strength rank among liquid names), `regime.py` (market bull/neutral/bear from the NIFTY 500; stock trending/ranging), `selector.py` (rule eligibility + in-sample expectancy per strategy x regime; switches off losers).
- `fills.py` (pure fill/exit rules), `costs.py` (STT, stamp, GST, DP, slippage), `risk.py` (sizing + portfolio caps): shared by backtest and paper.
- `backtest.py`: `prepare()` computes features/candidates once; `run()` is the daily event loop and takes `only=` (restrict strategy keys), `selector=`, `emit_last=` (queue orders from the final close). `walkforward.py` fits params per strategy (grid in `GRIDS`, key `name#i`, `#0` = defaults) and the selector on each in-sample window.
- `momentum.py`: separate portfolio-level strategy (monthly rebalance, top-N equal weight by trailing return skipping the last month, 200 SMA and market-regime filters, buffer to cut turnover, fills at next open with the shared costs). Runs in the paper ledger as its own sleeve (separate capital, tables `mom_*`, frozen params, forward-only start; see `paper.init_momentum` / `_sync_momentum`). `MomParams.random_seed` is a CONTROL: a persistent random pick with the same rules, used to separate ranking skill from universe effects. `prepare(liquid_top=N)` restricts each day to the N most liquid names.
- `paper.py`: each sleeve in the ledger is a **deterministic replay of its backtest engine** (`backtest.run` for swing, `momentum.run` for momentum) from its start date, with params frozen at init, persisted to `data/paper.db` (meta keys `momentum` and, if present, `params`/`selector`/`start`/`capital`; tables `mom_*` and `trades`/`equity`/`positions`/`orders`). Nothing incremental is stored, so there is nothing to drift. The swing sleeve is optional: `PaperState.result` is None for a momentum-only ledger, and `init`/`drop_swing` never touch momentum. `report.py` writes `reports/<date>.md` plus `<date>-momentum-orders.csv` (and `<date>-orders.csv` only when a swing sleeve exists).

### Contributions and point-in-time universe (added 2026-11-18)

- **Monthly top-ups** (`monthly_contribution` in `config.yaml`, INR 5,000): `momentum.run(contribution=...)` adds cash at each month-end close (`prep.rebal`). The result's `equity` is a deposit-adjusted (time-weighted) curve so deposits never count as returns; `value` is real money, `deposited` the running total. `paper-momentum` freezes the contribution into the sleeve (reset 2026-11-18, start 2026-11-17). You must deposit on the dates the replay assumes. Harness v3: each walk-forward window is a fresh start (INR 5,000 + deposits for one year); gate formulas unchanged, charges are measured against average account value, money-weighted end values vs index/basket (same deposits) are informational.
- **Point-in-time universe** (`data/membership.py`, harness v5, `prepare(pit=True)`): membership on day t comes from (a) 15 dated snapshots of NSE's `ind_nifty500list.csv` (Internet Archive, 2018-10 to 2026-11, `data/membership/snapshots/`), each the truth on its date, and (b) NSE Indices press-release changes (`events.csv`, parsed from 650+ releases found by probing `niftyindices.com/Press_Release/ind_prsDDMMYYYY[_0|_1].pdf`; the relevant PDFs are in `data/membership/releases/`) applied on their effective dates between snapshots; `manual_events.csv` (optional: eff_date,symbol,action,note) holds hand-checked fixes. Anything the events do not explain is reset at the next snapshot (late for joiners and leavers). A company's key is its latest symbol; symbols and ISINs that ever share a row are linked, because splits change the ISIN and renames change the symbol. `membership.timeline()` returns a per-gap reconciliation (unexplained joins/exits): from 464/464 total with snapshots only to about 120 after events, and 2021 to 2026 is nearly closed (gaps 2020-07 to 2022-05: 3, 2022-10 to 2023-04: 1, 2024-02 to 2025-06: 7). Still open: 2019-02 to 2020-07 (71, before the test window; NSE's `IndexInclExcl.xls` covers to 2020-09-14 but by name only). 62 past members have no Yahoo prices (`unavailable.csv`, mostly merged/delisted). Other residual bias: stocks that joined and left inside one gap never appear, delisted names held at their last close, history before 2018-10-04 is not point-in-time, historical names have no sector (`Unknown`). The paper ledger sleeves still use the plain current universe (no lookahead going forward).
- Point-in-time check (2026-11-18, gap-filled, 100,000 lump sum, warm start, 2021 onward, default momentum top 10): full universe, today's list 37.6%/yr vs point-in-time 30.3% (equal-weight basket 24.2% vs 17.6%, random picks 13.3% vs 11.6%, index 12.9%); liquid top 200: 22.1% vs 22.1% (basket 19.0% vs 17.6%); top 100: 18.6% vs 18.3% (basket 16.3% vs 16.3%, random 12.5% vs 9.2%). So the survivorship bias is about 7 points on the full universe and small on large caps, and momentum still beats the basket, random picks and the index point-in-time. Trials 22-26 (harness v5, 25 counted trials) all FAIL at INR 5,000 + 5,000/month: `high_52w` 11.8% (charges 3.2%), `sector_mom` 11.9% (every grid point beats the index; 20.6% and 6/6 years at 100,000; only 2/6 years at 5,000; DSR 0.60; drawdown -33%), `resid_mom` 6.6%, `nse_style_mom` 6.9%, `low_vol` 0.5%; index 12.9%, basket 16.3%.

### Research loop (added 2026-11-18)

Manual `/research [N]` (default 1, max 5 ideas per run, each fully specified and evaluated before the next), ideas from `research/backlog.md` (user-added rows first, then published price/volume anomalies found with WebSearch). Flow: idea -> candidate module -> `research-eval` (fixed gates) -> `research-promote` -> forward paper sleeve. Only the forward ledger is evidence.

- `research/candidates/<slug>.py` (under `src/trader/`): `META` (slug, kind="rotation", hypothesis, source, grid of at most 4 points) and `score(prep, **params)` returning a dates x symbols matrix (higher = buy). It plugs into `momentum.run` through `MomParams.ranker`/`ranker_params`; grid keys `top_n`, `buffer`, `bear_exit`, `rebalance` ("M" or "W") configure the engine, the rest go to `score`. Only `kind="rotation"` is supported by `research-eval` (a swing-style candidate would need its own harness).
- `research/evaluate.py`: gates are fixed in code and must not be edited to make a candidate pass. Run at INR 5,000 with the real costs on the liquid-top-100 universe (the full universe is reported only): lookahead guard (score recomputed on truncated history), walk-forward OOS, then beat the index and the equal-weight basket, beat the median of 20 random-pick controls, at least 2/3 of OOS years beating the index, every grid point beating the index, deflated Sharpe >= 0.95 (N = counted trials), charges < 3%/yr, daily-return correlation < 0.9 with default momentum and active candidates. Outputs to `reports/research/<slug>/`.
- `research/registry.py`: append-only trial log in `data/research.db` (a failed attempt still counts toward N), plus candidate loading and sha256.
- `paper.py` candidate sleeves: meta key `candidates`, tables `cand_*` with a `sleeve` column, replayed like the momentum sleeve from the frozen params. The candidate file's sha256 is stored at promotion; if the file later changes, `sync` refuses to replay it (reported under "NOT replayed"). The existing `momentum` meta and `mom_*` tables are never touched.
- `data/fundamentals.py`: free yfinance fundamentals have no publication dates and carry later revisions, so they are saved as dated snapshots and read only through `asof`/`panel` (newest snapshot dated on or before the decision day). A candidate with `uses_fundamentals: True` gets no backtest gates: the verdict is `FORWARD_ONLY` (tier `forward_only`, shown in the report as "NO backtest evidence"). Real backtests on fundamentals need about 3 years of our own snapshots (first one 2026-11-18).
- `research-eval` also reports each candidate at account sizes INR 25,000 (about where INR 5,000 monthly top-ups reach in five months) and 100,000 (does the idea have merit once fixed costs stop dominating). Informational: only the INR 5,000 run decides the verdict, but a FAIL with "merit at 100,000: yes" points to a cost/affordability limit worth a variant.
- Findings so far: `low_vol` FAILED (2026-11-18) at every account size (INR 5,000: -1.0%/yr, 100,000: 3.9% vs index 12.9%). At INR 5,000 it was also mostly cash, because INR 500 slots cannot buy expensive stocks.
- Indian-market evidence round (2026-11-18, `research/india_evidence.md`): NSE's own Nifty200 Momentum 30 uses a volatility-adjusted 6+12-month score rebalanced semi-annually; low-vol evidence in India is mixed; no rigorous NSE test of the 52-week-high effect. `rebalance` now supports "M", "W", "Q" (quarterly) and "S" (Jun/Dec). `nse_style_mom` was tested (FAIL, trial 5): charges fixed (0.27%/yr) but the book was mostly cash. Harness v2 (2026-11-18, user approved): the harness runs every walk-forward window with `momentum.run(..., warm_start=True)` (an initial rebalance on the window's first session) because each window used to restart from cash, which penalised slow cadences. The paper ledger and old CLI commands keep warm_start off. All five trials were re-run as new counted trials (10 so far); none passed. Trials record `"harness": "v2-warm-start"`; older rows lack it.
- Idea search (widened 2026-11-18): `/research` refills the queue when fewer than 3 backtestable ideas remain, from SSRN/NBER, Quantpedia, AQR/Alpha Architect, arXiv, NSE/BSE methodologies and research, and Indian/EM journals; never social media, tips or paid-signal sites; never chosen by recent performance. Each journal entry carries a "Market context" block from `trader market-context` (informational only, never used in gates, grids or choice of idea).
- Idea sourcing: the seed backlog was written from memory of US-centred factor research (citations of tested ideas checked by search). `/research` step 2 now also checks Indian-market evidence and small-account fit (turnover, slots) before each test, without using backtest results; user-added ideas go first.
- Trials 2026-11-18 (all FAIL at the INR 5,000 gate; OOS 2021-2026 vs index 12.9%): `low_vol` -1.0% (3.9% at 100,000, merit no); `high_52w` 2.2% (charges 6.6%/yr; 16.5% at 100,000); `resid_mom` 6.8% (0.87 correlated with default momentum); `sector_mom` 8.2% (17.1% at 100,000 but drawdown -35%). The only ideas that beat the index at all do so at INR 100,000 by thin margins over the survivorship-flattered basket. Full detail in `research/journal/`.

Conventions that matter:
- No lookahead: a feature at row t uses only bars <= t (tested per indicator, strategy and regime). Signals are evaluated at the close and orders work the next session.
- If a bar can hit both stop and target, the stop is assumed first.
- Cash accounting, no leverage. Signals whose size would be cut below `min_size_fraction` (0.5) by lack of cash are skipped.
- Settings live in `config.yaml` (capital, risk per trade, caps, costs, regime policy).

Momentum findings (2026-11-18, universe = today's NIFTY 500): walk-forward OOS 2021-2026 CAGR 25.6% vs index 12.9%, 5 of 6 years positive, every grid point 27-32%. But the survivorship bias is large: an equal-weight basket of today's liquid constituents returned 20.6%/yr vs 11.0% for the index with no momentum at all. Restricting to the most liquid names (less affected by "added because it rose"): top 200 15.3%, top 100 7.5%, top 50 6.8% vs index 11.0%. Momentum beats persistent-random picks in every universe (ranking carries some signal) but on large caps it does not beat the index. Do not trust the headline number; true point-in-time index membership is needed to settle it.

Known quirks / limitations:
- Universe is today's NIFTY 500 constituents: backtests have survivorship bias (flattering).
- A breakout order can be queued with an estimated entry (signal close) above its own `max_entry` cap, so it only fills if the stock opens lower. It still reserves a slot and risk budget.
- yfinance close is split-adjusted but not dividend-adjusted; the latest bar is dropped before 16:00 IST.
- CAGR is only reported for windows of a year or more.

## Dhan MCP

- Configured as an HTTP MCP server at `https://mcp.dhan.co/mcp` (no keys in config). Auth is a browser consent flow via the `login` / `complete_login` tools. Tool schemas are deferred: load them with ToolSearch before calling.
- Tools are wrappers over Dhan API v2: `portfolio`, `orderbook`, `tradebook`, `margin`, `alerts`, `market_data`, `historical_data`, `search`, `trading`. Each takes `action` plus a JSON-string `payload`.
- `search` resolves a symbol to a `securityId` (e.g. RELIANCE NSE_EQ = 2885). Index ids on `IDX_I`: NIFTY 13, BANKNIFTY 25, SENSEX 51.
- `trading_agent_tool` places real orders. Confirm with the user before any order.
- `.env` holds `DHAN_CLIENT_ID` / `DHAN_ACCESS_TOKEN` (gitignored). The token expires after ~24h and is only used by `--source dhan`.

## Free-tier limits (the account is on the free "Trading APIs" plan)

Verified on 2026-11-18:

| Works | Blocked (needs ₹499/mo Data APIs plan) |
|---|---|
| portfolio (positions, holdings, funds, trades), orderbook, search | `market_data`: ltp, ohlc, quote, optionchain, expirylist (return a bare `Unauthorized`) |
| MCP `historical_data` action `historical` (daily candles) | **REST `POST /v2/charts/historical`** (`DH-902: requires a Data APIs Plan`, even with a valid token) and `historical_data` action `intraday` |

- This is why candles come from yfinance: the REST historical endpoint is blocked on the free plan. yfinance daily bars matched the Dhan MCP exactly on a RELIANCE spot check.
- On the free tier, analysis is end-of-day only. No live prices, intraday, option chain or depth.
- The account had ₹0 balance, no holdings and no positions when last checked.
