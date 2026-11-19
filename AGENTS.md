# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) and Hermes when working in this repository. Keep it under 20,000 characters (Hermes truncates longer context files).

## What this is

A systematic NIFTY 500 trader (long-only, delivery equity). Python package `trader` (src layout, managed with `uv`). Git repo with local history only; nothing is pushed. **Paper trading only: no real orders are placed by the code.** All persistent data lives in **Postgres** (`POSTGRES_*` in `.env`, see `.env.example`; code in `db.py`): candles, instruments, membership, fundamentals, the paper ledger, the research trial log, generated reports/results (`outputs.py`) and script run logs. The old local `data/` and `reports/` folders were imported on 2026-11-18 (`trader db migrate-local`) and then deleted; the database is the only copy, so back it up (e.g. `pg_dump`) before risky changes. The server has no TLS (plaintext connection) as of 2026-11-18.

Two strategy families, with different status (as of 2026-11-18):
- **Momentum rotation** (monthly, top-N by trailing return): the only sleeve in the paper ledger. Paper capital INR 25,000 (`config.yaml`) plus INR 5,000 per month-end, 10 holdings, forward-only from 2026-11-18. It holds cash until the first month-end signal (close 2026-11-30, fills 2026-12-01). Its backtest is flattered by survivorship bias (see `docs/findings.md`).
- **Swing strategies** (`trend_pullback`, `breakout`, `mean_reversion` + regime/selector): built and tested. Walk-forward OOS did not beat buy-and-hold after costs (CAGR -4.4% vs +12.9%), and at INR 5,000 they were unworkable (backtest CAGR -34%, charges 103% of starting capital, because the fixed INR 15.34 DP sell charge is ~6% of a ~INR 260 position). On 2026-11-18 the swing sleeve was re-added to the paper ledger (`trader paper-init --start 2026-11-18`) when capital went to INR 25,000 (config.yaml), sharing capital with momentum. The first queued order is a breakout buy (SUNTV, max 703.17, qty 4) for the 2026-11-19 open; no fills or positions as of 2026-11-18. Do not treat the swing sleeve's walk-forward result as evidence that it works at 25k.

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
uv run python scripts/paper_report_chart.py [--out PATH]   # PNG of ledger equity per sleeve, open positions, queued orders (from Postgres); default charts/paper_report_<date>.png (gitignored). `trader_daily.sh` runs it after each daily run.
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

### Detailed findings and research loop (moved 2026-11-18)

The contribution mechanics, point-in-time universe, research loop, pre-reset record, momentum findings and known quirks are in `docs/findings.md`. Read it before changing the ledger, the universe, the research gates or any headline number.

Conventions that matter:
- No lookahead: a feature at row t uses only bars <= t (tested per indicator, strategy and regime). Signals are evaluated at the close; orders work the next session.
- If a bar can hit both stop and target, the stop is assumed first.
- Cash accounting, no leverage. Signals whose size would be cut below `min_size_fraction` (0.5) by lack of cash are skipped.
- Settings live in `config.yaml` (capital, risk per trade, caps, costs, regime policy).

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
