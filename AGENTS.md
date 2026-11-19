# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) and Hermes when working in this repository. Keep it under 20,000 characters (Hermes truncates longer context files).

## What this is

A systematic NIFTY 500 trader (long-only, delivery equity). Python package `trader` (src layout, managed with `uv`). Git repo with local history only; nothing is pushed. **Paper trading only: no real orders are placed by the code.** All persistent data lives in **Postgres** (`POSTGRES_*` in `.env`, see `.env.example`; code in `db.py`): candles, instruments, membership, fundamentals, the paper ledger, the research trial log, generated reports/results (`outputs.py`) and script run logs. The old local `data/` and `reports/` folders were imported on 2026-11-18 (`trader db migrate-local`) and then deleted; the database is the only copy, so back it up (e.g. `pg_dump`) before risky changes. The server has no TLS (plaintext connection) as of 2026-11-18.

Two strategy families, with different status (as of 2026-11-18):
**The paper ledger is ONE shared cash account** (owner decision 2026-11-19): INR 25,000 (`config.yaml`) plus INR 5,000 once per month-end for the whole account, not per sleeve. The swing and momentum sleeves both draw on that cash and are valued against one account equity (cash + all positions). Details and the arbitration rule are under "Shared account" below. Promoted research candidates are folded into this account too, with no money of their own (PROVISIONAL, see "Shared account"). Backtests, walk-forward and the research harness are unchanged: they are single-sleeve, each with its own pot.

- **Momentum rotation** (monthly, top-N by trailing return): a sleeve of the shared account, 10 holdings, forward-only from 2026-11-17/18. It holds cash until the first month-end signal (close 2026-11-30, fills 2026-12-01). Its backtest is flattered by survivorship bias (see `docs/findings.md`).
- **Swing strategies** (`trend_pullback`, `breakout`, `mean_reversion` + regime/selector): built and tested. Walk-forward OOS did not beat buy-and-hold after costs (CAGR -4.4% vs +12.9%), and at INR 5,000 they were unworkable (backtest CAGR -34%, charges 103% of starting capital, because the fixed INR 15.34 DP sell charge is ~6% of a ~INR 260 position). On 2026-11-18 the swing sleeve was re-added to the paper ledger (`trader paper-init --start 2026-11-18`) when capital went to INR 25,000 (config.yaml), sharing one cash account with momentum. The first queued order is a breakout buy (SUNTV, max 703.17, qty 4) for the 2026-11-19 open; no fills or positions as of 2026-11-18. Do not treat the swing sleeve's walk-forward result as evidence that it works at 25k.

Never present any signal as a recommendation to trade real money.

## Commands

```
uv sync                                  # install
uv run pytest -q                         # tests (149; DB tests run in a throwaway schema on the Postgres server, ~4 min)
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
uv run python scripts/paper_report_chart.py [--out PATH]   # PNG of the shared account (stack of cash + swing + momentum = account equity), momentum holdings, swing positions, queued orders (from Postgres); default charts/paper_report_<date>.png (gitignored). `trader_daily.sh` runs it after each daily run.
uv run trader fundamentals-snapshot [--if-stale-days N]   # save today's fundamentals as a dated snapshot in the fundamentals table (a few minutes)
uv run trader research-eval SLUG [--recheck]        # fixed gates on a candidate in src/trader/research/candidates/; records a trial (--recheck = not counted)
uv run trader research-promote SLUG                 # freeze a PASS / FORWARD_ONLY candidate into the shared account as a sleeve: no capital or deposit of its own, funded from account cash (max 5)
uv run trader research-retire SLUG                  # stop replaying a candidate sleeve (it then vanishes from the replay, history included: see open questions)
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
- `backtest.py`: `prepare()` computes features/candidates once; `run()` is the daily event loop (single sleeve, own pot) and takes `only=`, `selector=`, `emit_last=` (queue orders from the final close). The loop body lives in `SwingBook` (`exits`/`fills`/`end_of_day`/`decide`) so the shared-account ledger drives the same code. `walkforward.py` fits params per strategy (grid in `GRIDS`, key `name#i`, `#0` = defaults) and the selector on each in-sample window.
- `momentum.py`: portfolio-level strategy. Monthly rebalance, top-N equal weight by trailing return skipping the last month, 200 SMA and market-regime filters, buffer to cut turnover, fills at next open with shared costs. `run()` is the single-sleeve engine (own pot); its loop body is `MomBook` (`sell_at_open`/`buy_at_open`/`invested`/`decide`), also driven by the shared-account ledger. Runs in the paper ledger as a sleeve of the shared account (tables `mom_*`, frozen params, forward-only; see `paper.init_momentum`). `MomParams.random_seed` is a CONTROL: a persistent random pick with the same rules, separating ranking skill from universe effects. `prepare(liquid_top=N)` restricts each day to the N most liquid names.
- `accounting.py` (`CashBox`, `Nav`) and `ledger.py` (`ledger.run`): the shared account, see "Shared account" below.
- `paper.py`: the ledger is a **deterministic replay** of both sleeves together (`ledger.run`, which drives `SwingBook` and `MomBook`) from the earliest sleeve start, with params frozen at init, persisted to Postgres (`paper_meta` keys `momentum` and, if present, `params`/`selector`/`start`/`capital`/`contribution`; tables `account_equity` (date, equity = time-weighted, invested, value, cash, swing_value, mom_value, cand_value, deposited), `mom_*` and `trades`/`equity`/`positions`/`orders`; in `equity`/`mom_equity` the column `value` is that sleeve's positions value). The account's start, opening cash and deposit are derived at sync time from the frozen sleeve records (`paper.account_spec`: the earliest-starting sleeve defines them), never stored separately. Nothing incremental is stored, so nothing drifts. Promoted research candidates (`cand_*` tables) are sleeves of the account (PROVISIONAL, see "Shared account"): no capital or deposit of their own, `account_equity.cand_value`; the `capital` in a candidate's `candidates` meta record is the research harness's and is ignored by the ledger. The swing sleeve is optional: `PaperState.result` is None for a momentum-only ledger, and `init`/`drop_swing` never touch momentum. `report.py` stores `daily/<date>` via `outputs.py` (items `report`, `momentum-orders`, and `orders` only when a swing sleeve exists); `trader show daily [date] [item]` prints them. `outputs.py` keeps every run of backtest/walkforward/momentum/momentum-wf/research-eval/daily (append-only `output_runs` + `output_items`). `trader db status|trial-count|log-run|migrate-local` are the DB utilities; ledger and research commands take Postgres advisory locks so only one writer runs at a time.

### Shared account (owner decision 2026-11-19; for the owner's review)

The paper ledger is one cash account, replayed from the earliest sleeve start by `ledger.run` (swing and momentum together, one `CashBox`). Rules:
- **Cash**: starts at `capital`, gets `monthly_contribution` once per month-end close for the whole account (not once per sleeve). Account equity = cash + swing positions + momentum positions. The report and chart show account equity, cash and each sleeve's positions value; they add up to the account.
- **Sizing on TOTAL account equity**: momentum targets are equity/top_n of account equity (so swing positions count in the denominator); swing risk per trade, `max_position_pct` and `max_heat` use account equity. Position counts (`max_positions`, `max_per_sector`) stay per sleeve. Orders are queued from the close without reserving cash against each other.
- **Arbitration at the open (the order cash is handed out)**: (1) all sells/exits first, swing then momentum, so freed cash is available to every buy; (2) then buys: momentum's rebalance buys BEFORE swing's entries, so the monthly rebalance is never starved by swing; (3) a buy is cut to the cash left and skipped if the cut is below `min_size_fraction` (0.5) of its intended quantity. Cash never goes negative. (Consequence to be aware of: momentum targets sum to ~100% of account equity, so swing is funded mainly by deposits, sells and idle cash.)
- **Replay**: both sleeves are replayed together, so a sleeve's numbers depend on the other's fills and the result does not depend on run order. `paper-init --reset` / `paper-momentum --reset` still work: each rewrites only its own sleeve record, and the account is re-derived on the next sync.
- **Unchanged**: `trader backtest`, `trader momentum`, `walkforward`, `momentum-wf`, `research-eval` and the research harness (and the trial registry) are single-sleeve, each with its own pot (`backtest.run`, `momentum.run`), and never touch the account. Research stays UNFOLDED.

#### Promoted research candidates in the account (PROVISIONAL, owner decision 2026-11-19, to be reviewed)

`trader research-promote SLUG` folds a candidate into the shared account (`ledger.CandSpec`, replayed by the same `ledger.run`):
- **No new money**: its opening positions are bought from account cash at its start date; it has no `capital` and adds no deposit (the account's single month-end deposit is the only one). The `capital` stored in its promotion record (e.g. quality_india's 5,000) is the research harness's and is ignored (test: `test_candidate_record_capital_does_not_change_account_equity_or_deposits`). Its value counts toward account equity: account = cash + swing + momentum + candidates (`account_equity.cand_value`). Targets are equity/top_n of TOTAL account equity.
- **Arbitration**: sells and exits of every sleeve first; then buys in the order momentum, swing, candidates (in promotion order, by the `promoted` stamp); each cut to the cash left and skipped below `min_size_fraction`.
- **Sleeve cap**: `account: {max_sleeve_share: 0.40}` in `config.yaml` (`AccountCfg`). A sleeve's positions (momentum, swing, each candidate) may not exceed that share of account equity at the open; a buy is cut so the sleeve stays within it (existing holdings count) and skipped below `min_size_fraction`. 1.0 disables it. **It binds momentum too** (10 holdings at 1/10 of equity is ~100%): with 0.40, momentum buys fill until it holds ~40% of the account and the rest is cut or skipped. Check this before the first month-end rebalance (fills 2026-12-01).
- A candidate not yet started, with a changed file (code freeze) or a missing file is not replayed and listed under "NOT replayed" in the report; this changes the account's history retroactively.

Open questions for the owner:
1. Should the cap differ per sleeve (e.g. higher for momentum, the core sleeve, lower for candidates), and should it bind momentum at all?
2. Should candidates get a reserved share of cash instead of arbitrating last (today they only get what momentum and swing leave, which is little: momentum targets ~100%)?
3. Should promotion take effect at the next session (as now: start = last bar, first orders fill at the next open) or at a later fixed date, e.g. the next month-end deposit?
4. `research-retire` drops the sleeve from the replay entirely, rewriting account history as if it had never held anything. It should liquidate at the retire date instead. Same for a code-freeze failure.

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
