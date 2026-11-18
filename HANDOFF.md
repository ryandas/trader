# Handoff: Hermes scheduled paper run

Paper trading only. Nothing in `src/` places orders, and `config.yaml` has `mode: paper` (the `Config.mode` default). Live trading is deferred until the forward paper results are good; it is not built.

## How the scheduled run works

- Hermes cron, 09:15 Asia/Kolkata, Mon-Fri (schedule as stated by the owner; the cron definition itself lives in Hermes, outside this repo, and was not inspected).
- It runs `scripts/trader_daily.sh`, which:
  1. resolves the repo and the holiday file relative to itself (override with `TRADER_HOLIDAYS_FILE`; logs go to `TRADER_LOG_DIR`, default `${TMPDIR:-/tmp}/trader-logs`);
  2. exits silently (empty stdout, nothing sent) if today's IST date is listed in `scripts/nse_holidays_2026.txt`;
  3. otherwise runs `uv run trader daily` with a 1500 s timeout.
- Delivered to Telegram (stdout of the script):
  - success: a header line, then the lines `trader daily` echoes (date and regime, momentum sleeve value / holdings / queued orders, any candidate sleeves, `report: reports/<date>.md` path, a stale-data WARNING if any), then `OK (exit 0). Log: <path>`;
  - failure: `FAILED ...` plus the last 40 lines of the log.
- The script uses nothing from Dhan MCP. Candles come from yfinance. Needs `uv` on PATH (`~/.local/bin` is added) and network access.

## Holiday list

`scripts/nse_holidays_2026.txt` has 2026 dates only, one `YYYY-MM-DD` per line, `#` comments allowed (matched with `grep -qx`, so no trailing spaces). **A 2027 list is needed before January 2027**: either append 2027 dates to this file or add `nse_holidays_2027.txt` and change `HOLIDAYS` in the script (it reads one file). Without it the run also happens on holidays (effect not verified; a stale-data WARNING may appear).

## Where things live

- Reports: `reports/<date>.md`, `reports/<date>-momentum-orders.csv` (gitignored).
- Ledgers: `data/paper.db` (paper sleeves), `data/research.db` (research trials). Also under `data/`: candles, membership, fundamentals. All of `data/` and `reports/` and `.env` are gitignored, so **they must be copied manually to a new host**. The paper ledger is a deterministic replay from frozen params, so `paper.db` plus `config.yaml` matter; do not reset it.
- Nothing has been pushed; the repo has local history only (an `origin` remote is configured but unused).

## Claude-only (not part of the Hermes run)

- The research loop (`/research`, `trader research-*`), which writes candidate code and may promote paper sleeves.
- `/daily` (`.claude/commands/daily.md`) summary routine, including its Dhan MCP account check (step 3). Dhan MCP is reachable only from Claude Code, not Hermes.
- `trader fundamentals-snapshot` (run from `/daily`, not from the script), `membership-snapshot` (about monthly, manual).

## Live trading

Deferred. `Config.mode` accepts "live" syntactically, but no code uses it and no order-placing code exists. If order placement is ever added it must refuse unless `mode == "live"` (`tests/test_config_mode.py` fails if order-placement strings appear in `src/`, as a reminder).
