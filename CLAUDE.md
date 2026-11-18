# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) and Hermes when working in this repository. Keep it under 20,000 characters (Hermes truncates longer context files).

## What this is

A systematic NIFTY 500 trader (long-only, delivery equity). Python package `trader` (src layout, managed with `uv`). Git repo with local history only; nothing is pushed. **Paper trading only: no real orders are placed by the code.** All persistent data lives in **Postgres** (`POSTGRES_*` in `.env`, see `.env.example`; code in `db.py`): candles, instruments, membership, fundamentals, the paper ledger, the research trial log, generated reports/results (`outputs.py`) and script run logs. The old local files (`data/`, `reports/`) were imported on 2026-11-18 (`trader db migrate-local`) and are now only a backup; nothing reads them. The server has no TLS (plaintext connection) as of 2026-11-18.

Two strategy families, with different status (as of 2026-11-18):
- **Momentum rotation** (monthly, top-N by trailing return): the only sleeve in the paper ledger. Paper capital INR 5,000 (`config.yaml`), 10 holdings, forward-only from 2026-11-17. It holds cash until the first month-end signal (close 2026-11-30, fills 2026-12-01). Its backtest is flattered by survivorship bias (see findings).
- **Swing strategies** (`trend_pullback`, `breakout`, `mean_reversion` + regime/selector): built and tested but **removed from the paper ledger**. Walk-forward OOS did not beat buy-and-hold after costs (CAGR -4.4% vs +12.9%). At INR 5,000 they are unworkable: backtest 2021-2026 gives -34% CAGR, ending equity INR 434, charges 103% of starting capital, because the fixed INR 15.34 DP sell charge is ~6% of a ~INR 260 position. Re-add with `trader paper-init` if wanted.

Never present any signal as a recommendation to trade real money.

## Commands

```
uv sync                                  # install
uv run pytest -q                         # tests (126; DB tests run in a throwaway schema on the Postgres server, ~4 min)
uv run pytest tests/test_fills_risk_costs.py::test_gap_through_stop_exits_at_open   # one test
uv run trader init                       # build NIFTY 500 -> Dhan securityId list (instruments table)
uv run trader update [SYMBOLS...]        # backfill/refresh daily candles (10y); no args also refreshes the NIFTY500 benchmark
uv run trader backtest [--strategy NAME] [--from DATE] [--no-filters]   # --no-filters = unfiltered baseline
uv run trader walkforward                # 3y in-sample / 1y OOS folds; stores a walkforward run (folds, OOS trades/equity, params, selector_stats) via outputs.py
uv run trader membership-snapshot       # save today's official NIFTY 500 list as a dated snapshot (run about monthly)
uv run trader membership-fetch          # prices for past NIFTY 500 members missing from the candles table (unavailable -> membership_unavailable table)
uv run trader momentum [--from DATE] [--liquid-top N] [--pit] [--top-n N ...]   # momentum backtest (separate from the paper ledger)
uv run trader momentum-wf [--liquid-top N] [--pit]   # its walk-forward + robustness grid
uv run trader paper-momentum [--start DATE] [--liquid-top N] [--reset]   # start momentum sleeve (params from config.yaml, then frozen). Changing config.yaml later does NOT affect a running sleeve: reset it.
uv run trader paper-init [--start DATE] [--reset]   # (optional) add swing sleeve, freezing params + selector stats; --reset leaves momentum alone
uv run trader paper-drop-swing                      # remove swing sleeve; momentum kept
uv run trader daily [--asof DATE] [--no-update]     # update data, advance ledger sleeves, store the report as `daily/<date>` (read it: `trader show daily`; ~5 min with update, candle load over the network ~1 min)
uv run trader fundamentals-snapshot [--if-stale-days N]   # save today's fundamentals as a dated snapshot in the fundamentals table (a few minutes)
uv run trader research-eval SLUG [--recheck]        # fixed gates on a candidate in src/trader/research/candidates/; records a trial (--recheck = not counted)
uv run trader research-promote SLUG                 # freeze a PASS / FORWARD_ONLY candidate into the ledger as its own paper sleeve (max 5)
uv run trader research-retire SLUG                  # stop replaying a candidate sleeve
uv run trader market-context                        # market snapshot (regime, trend, returns, volatility, breadth); informational
uv run trader research-status                       # trial count, recent trials, candidate sleeves, data freshness, backlog head
```

`/daily` (`.claude/commands/daily.md`) runs the daily routine and summarises it. Read-only.
`/research` (`.claude/commands/research.md`) runs one iteration of the research loop (below). It writes candidate code, journal and backlog files and may promote a passing candidate to a paper sleeve; it never places orders.

## Architecture

Pipeline per day: **universe -> regime -> selector -> strategies -> risk -> fills**.

- `data/`: `sources.py` (`YFinanceSource` default, `DhanSource` needs paid plan; both behind the `CandleSource` protocol), `store.py` (`candles` table; `load`, bulk `load_many`, incremental `update_symbol`; update, backward extension, split detection by re-fetching a 5-day overlap), `instruments.py` (NSE list + Dhan scrip master), `dhan.py`.
- `indicators.py`, `strategies/` (`features()` builds the per-symbol frame; each strategy returns a vectorised `SignalSet`). Strategies: `trend_pullback` (buy-stop), `breakout` and `mean_reversion` (buy next open).
- `universe.py` (daily top-N relative-strength rank among liquid names), `regime.py` (market bull/neutral/bear from NIFTY 500; stock trending/ranging), `selector.py` (rule eligibility + in-sample expectancy per strategy x regime; switches off losers).
- `fills.py` (pure fill/exit rules), `costs.py` (STT, stamp, GST, DP, slippage), `risk.py` (sizing + portfolio caps): shared by backtest and paper.
- `backtest.py`: `prepare()` computes features/candidates once; `run()` is the daily event loop and takes `only=`, `selector=`, `emit_last=` (queue orders from the final close). `walkforward.py` fits params per strategy (grid in `GRIDS`, key `name#i`, `#0` = defaults) and the selector on each in-sample window.
- `momentum.py`: portfolio-level strategy. Monthly rebalance, top-N equal weight by trailing return skipping the last month, 200 SMA and market-regime filters, buffer to cut turnover, fills at next open with shared costs. Runs in the paper ledger as its own sleeve (separate capital, tables `mom_*`, frozen params, forward-only; see `paper.init_momentum` / `_sync_momentum`). `MomParams.random_seed` is a CONTROL: a persistent random pick with the same rules, separating ranking skill from universe effects. `prepare(liquid_top=N)` restricts each day to the N most liquid names.
- `paper.py`: each sleeve is a **deterministic replay of its backtest engine** (`backtest.run` for swing, `momentum.run` for momentum) from its start date, with params frozen at init, persisted to Postgres (`paper_meta` keys `momentum` and, if present, `params`/`selector`/`start`/`capital`; tables `mom_*` and `trades`/`equity`/`positions`/`orders`). Nothing incremental is stored, so nothing drifts. The swing sleeve is optional: `PaperState.result` is None for a momentum-only ledger, and `init`/`drop_swing` never touch momentum. `report.py` stores `daily/<date>` via `outputs.py` (items `report`, `momentum-orders`, and `orders` only when a swing sleeve exists); `trader show daily [date] [item]` prints them. `outputs.py` keeps every run of backtest/walkforward/momentum/momentum-wf/research-eval/daily (append-only `output_runs` + `output_items`). `trader db status|trial-count|log-run|migrate-local` are the DB utilities; ledger and research commands take Postgres advisory locks so only one writer runs at a time.

### Contributions and point-in-time universe (2026-11-18)

- **Monthly top-ups** (`monthly_contribution` in `config.yaml`, INR 5,000): `momentum.run(contribution=...)` adds cash at each month-end close (`prep.rebal`). The result's `equity` is a deposit-adjusted (time-weighted) curve, so deposits never count as returns; `value` is real money, `deposited` the running total. `paper-momentum` freezes the contribution into the sleeve (reset 2026-11-18, start 2026-11-17). Deposits must be made on the dates the replay assumes. Harness v3: each walk-forward window is a fresh start (INR 5,000 + deposits for one year); gate formulas unchanged; charges measured against average account value; money-weighted end values vs index/basket (same deposits) are informational.
- **Point-in-time universe** (`data/membership.py`, harness v5, `prepare(pit=True)`): membership on day t comes from (a) 15 dated snapshots of NSE's `ind_nifty500list.csv` (Internet Archive, 2018-10 to 2026-11, `membership_snapshots` table), each the truth on its date, and (b) NSE Indices press-release changes (`events.csv`, parsed from releases stored in `membership_releases`) applied on effective dates between snapshots. hand-checked fixes are `membership_events` rows with `manual = true` (`membership.save_events(df, manual=True)`; columns eff_date,symbol,action,note). Anything the events do not explain is reset at the next snapshot (late for joiners and leavers). A company's key is its latest symbol; symbols and ISINs that share a row are linked (splits change ISIN, renames change symbol). `membership.timeline()` gives a per-gap reconciliation: from 464/464 with snapshots only to about 120 unexplained after events; 2021-2026 nearly closed (gaps 2020-07 to 2022-05: 3; 2022-10 to 2023-04: 1; 2024-02 to 2025-06: 7). Still open: 2019-02 to 2020-07 (71, before the test window; NSE's `IndexInclExcl.xls` covers to 2020-09-14 but by name only). 62 past members have no Yahoo prices (`unavailable.csv`, mostly merged/delisted). Other residual bias: names that joined and left inside one gap never appear; delisted names are held at last close; history before 2018-10-04 is not point-in-time; historical names have no sector (`Unknown`). Paper ledger sleeves use the plain current universe (no lookahead going forward).
- Point-in-time check (2026-11-18, gap-filled, INR 100,000 lump sum, 2021 onward, top 10): full universe today's list 37.6%/yr vs point-in-time 30.3% (basket 24.2% vs 17.6%; random 13.3% vs 11.6%; index 12.9%). Liquid top 200: 22.1% vs 22.1%. Top 100: 18.6% vs 18.3%. Survivorship bias is about 7 points on the full universe and small on large caps; momentum still beats the basket, random picks and the index point-in-time.

### Research loop (2026-11-18)

Manual `/research [N]` (default 1, max 5 ideas per run, each fully specified and evaluated before the next). Ideas come from `research/backlog.md` (user-added rows first), then published price/volume anomalies found with WebSearch. Flow: idea -> candidate module -> `research-eval` (fixed gates) -> `research-promote` -> forward paper sleeve. Only the forward ledger is evidence.

- `research/candidates/<slug>.py` (under `src/trader/`): `META` (slug, kind="rotation", hypothesis, source, grid of at most 4 points) and `score(prep, **params)` returning a dates x symbols matrix (higher = buy). Plugs into `momentum.run` via `MomParams.ranker`/`ranker_params`; grid keys `top_n`, `buffer`, `bear_exit`, `rebalance` ("M", "W", "Q", "S") configure the engine, the rest go to `score`. Only `kind="rotation"` is supported by `research-eval`.
- `research/evaluate.py`: gates are fixed in code and must NOT be edited to make a candidate pass. Run at INR 5,000 with real costs on the liquid-top-100 universe (full universe reported only): lookahead guard (score recomputed on truncated history), walk-forward OOS, beat the index and equal-weight basket, beat the median of 20 random-pick controls, at least 2/3 of OOS years beating the index, every grid point beating the index, deflated Sharpe >= 0.95 (N = counted trials), charges < 3%/yr, daily-return correlation < 0.9 with default momentum and active candidates. Outputs stored as `research-eval/<slug>` (`trader show research-eval <slug> summary`). `research-eval` also reports INR 25,000 and 100,000 accounts (informational; only the 5,000 run decides).
- `research/registry.py`: append-only trial log (`trials` table, a trigger rejects UPDATE/DELETE; a failed attempt still counts toward N).
- `paper.py` candidate sleeves: meta key `candidates`, tables `cand_*` with a `sleeve` column, replayed from frozen params. The candidate file's sha256 is stored at promotion; if the file changes, `sync` refuses to replay it (reported under "NOT replayed"). The `momentum` meta and `mom_*` tables are never touched.
- `data/fundamentals.py`: free yfinance fundamentals have no publication dates and carry later revisions, so they are saved as dated snapshots and read only through `asof`/`panel` (newest snapshot on or before the decision day). A candidate with `uses_fundamentals: True` gets no backtest gates: verdict `FORWARD_ONLY` ("NO backtest evidence"). Real fundamentals backtests need about 3 years of our own snapshots (first one 2026-11-18).
- Research fresh start (2026-11-18, at the user's request, second reset): the `trials` table was truncated (count 0, ids restart at 1), stored research-eval outputs were deleted and `research/journal/` was emptied. The earlier journals and the trials' trail survive in git history (`git log -- research/journal`). Candidate modules in `src/trader/research/candidates/` and `research/backlog.md` were kept (not asked to clear); any candidate re-evaluated now counts as trial 1, 2, ... under harness `v4-pit-contrib-fresh-start` (`HARNESS_VERSION` in `research/evaluate.py`). Earlier results (frog_pan 10.7%, int_mom 12.66%, max_lottery 3.54%, and others) are no longer in the registry; the deflated-Sharpe bar starts from N=1 again.
- Pre-reset record (harness v5, OOS 2021-2026, index 12.9%; numbers kept only as a record, modules removed): `low_vol` -1.0%; `high_52w` 2.2% (charges 6.6%/yr); `resid_mom` 6.8% (0.87 correlated with default momentum); `sector_mom` 8.2% (drawdown -35%); `nse_style_mom` (charges 0.27%/yr, mostly cash). Trials 22-26 were all FAILED at INR 5,000 + 5,000/month.
- Indian-market evidence (`research/india_evidence.md`): NSE's Nifty200 Momentum 30 uses a volatility-adjusted 6+12-month score rebalanced semi-annually; low-vol evidence in India is mixed; no rigorous NSE test of the 52-week-high effect. Harness v2: every walk-forward window runs `momentum.run(..., warm_start=True)`. The paper ledger and CLI keep warm_start off.
- Idea search: `/research` refills the queue when fewer than 3 backtestable ideas remain, from SSRN/NBER, Quantpedia, AQR/Alpha Architect, arXiv, NSE/BSE methodology and research, and Indian/EM journals. Never social media, tips or paid-signal sites; never chosen by recent performance. Each journal entry carries a "Market context" block from `trader market-context` (informational only, never used in gates, grids or choice of idea). `/research` also checks Indian evidence and small-account fit (turnover, slots) before each test, without using backtest results.

Conventions that matter:
- No lookahead: a feature at row t uses only bars <= t (tested per indicator, strategy and regime). Signals are evaluated at the close; orders work the next session.
- If a bar can hit both stop and target, the stop is assumed first.
- Cash accounting, no leverage. Signals whose size would be cut below `min_size_fraction` (0.5) by lack of cash are skipped.
- Settings live in `config.yaml` (capital, risk per trade, caps, costs, regime policy).

Momentum findings (2026-11-18, universe = today's NIFTY 500): walk-forward OOS 2021-2026 CAGR 25.6% vs index 12.9%, 5 of 6 years positive, every grid point 27-32%. But survivorship bias is large: an equal-weight basket of today's liquid constituents returned 20.6%/yr vs 11.0% for the index with no momentum. Restricting to liquid names: top 200 15.3%, top 100 7.5%, top 50 6.8% vs index 11.0%. Momentum beats persistent-random picks in every universe (ranking carries some signal), but on large caps it does not beat the index. Do not trust the headline number; point-in-time membership (above) is what settles it.

Known quirks / limitations:
- Universe is today's NIFTY 500 constituents for the paper ledger and default backtests: survivorship bias (flattering).
- A breakout order can be queued with an estimated entry (signal close) above its own `max_entry` cap, so it only fills if the stock opens lower. It still reserves a slot and risk budget.
- yfinance close is split-adjusted but not dividend-adjusted; the latest bar is dropped before 16:00 IST.
- CAGR is only reported for windows of a year or more.

## Scheduling

The daily paper run is a Hermes cron job at 16:30 Asia/Kolkata, Mon-Fri (after the 16:00 cutoff: `last_complete_day()` only counts today's bar from 16:00, so the orders it queues are for the next session's open) (schedule as stated by the owner; the cron definition lives outside this repo and was not inspected). It runs `scripts/trader_daily.sh` (in this repo; resolves paths relative to itself), which exits silently on NSE equity holidays listed in `scripts/nse_holidays_<year>.txt`. Otherwise it runs `uv run trader daily` with a 1500 s timeout, logging to `$TRADER_LOG_DIR` (default `${TMPDIR:-/tmp}/trader-logs`). Its stdout is the Telegram message, formatted by `scripts/format_daily_message.py` from the lines `trader daily` echoes (regime, sleeve values, next-session order counts, warnings, report paths), or the last 40 log lines on failure. See `HANDOFF.md` for the Hermes handoff. `scripts/handoff_pack.sh` bundles the gitignored state; `scripts/handoff_check.sh` verifies a new host. Holiday lists are `scripts/nse_holidays_<year>.txt` (add 2027). `config.yaml` has `mode: paper` (`Config.mode`); live trading is deferred and no order-placing code exists in `src/`.

## Dhan MCP

- Configured as an HTTP MCP server at `https://mcp.dhan.co/mcp` (no keys in config). Auth is a browser consent flow via the `login` / `complete_login` tools. Tool schemas are deferred: load them with ToolSearch before calling.
- Tools wrap Dhan API v2: `portfolio`, `orderbook`, `tradebook`, `margin`, `alerts`, `market_data`, `historical_data`, `search`, `trading`. Each takes `action` plus a JSON-string `payload`.
- `search` resolves a symbol to a `securityId` (e.g. RELIANCE NSE_EQ = 2885). Index ids on `IDX_I`: NIFTY 13, BANKNIFTY 25, SENSEX 51.
- `trading_agent_tool` places real orders. Confirm with the user before any order.
- `.env` holds `DHAN_CLIENT_ID` / `DHAN_ACCESS_TOKEN` (gitignored). The token expires after ~24h and is only used by `--source dhan`.

## Free-tier limits (free "Trading APIs" plan)

Verified 2026-11-18:

| Works | Blocked (needs ₹499/mo Data APIs plan) |
|---|---|
| portfolio (positions, holdings, funds, trades), orderbook, search | `market_data`: ltp, ohlc, quote, optionchain, expirylist (return a bare `Unauthorized`) |
| MCP `historical_data` action `historical` (daily candles) | **REST `POST /v2/charts/historical`** (`DH-902: requires a Data APIs Plan`, even with a valid token) and `historical_data` action `intraday` |

- This is why candles come from yfinance: the REST historical endpoint is blocked on the free plan. yfinance daily bars matched the Dhan MCP exactly on a RELIANCE spot check.
- On the free tier, analysis is end-of-day only. No live prices, intraday, option chain or depth.
- The account had ₹0 balance, no holdings and no positions when last checked.
