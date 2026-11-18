# Handoff: Hermes scheduled paper run

Paper trading only. Nothing in `src/` places orders, and `config.yaml` has `mode: paper` (the `Config.mode` default). Live trading is deferred until the forward paper results are good; it is not built.

## How the scheduled run works

- Hermes cron, 16:30 Asia/Kolkata, Mon-Fri (schedule as stated by the owner; the cron definition itself lives in Hermes, outside this repo, and was not inspected).
- It runs `scripts/trader_daily.sh`, which:
  1. resolves the repo and the holiday file relative to itself (override with `TRADER_HOLIDAYS_FILE`; logs go to `TRADER_LOG_DIR`, default `${TMPDIR:-/tmp}/trader-logs`);
  2. exits silently (empty stdout, nothing sent) if today's IST date is listed in `scripts/nse_holidays_2026.txt`;
  3. otherwise runs `uv run trader daily` with a 1500 s timeout, then stores the Telegram message and the full log in the `job_runs` table (a failure to log appends a warning but never changes the run's outcome).
- Delivered to Telegram (stdout of the script):
  - success: a header line, then the lines `trader daily` echoes (date and regime, momentum sleeve value / holdings / queued orders, any candidate sleeves, `report: trader show daily <date>` reference, a stale-data WARNING if any), then `OK (exit 0). Log: <path>`;
  - failure: `FAILED ...` plus the last 40 lines of the log.
- The script uses nothing from Dhan MCP. Candles come from yfinance. Needs `uv` on PATH (`~/.local/bin` is added) and network access.

## Daily idea testing (Hermes cron)

- Hermes cron job `trader-research-daily`, Mon-Fri 18:30 Asia/Kolkata (after the 16:30 paper run). Skips NSE holidays (same list as the paper run). It runs `scripts/research_daily.sh` (a wrapper copy may exist on the old host; the repo script is the source of truth), which runs Claude Code in print mode for ONE idea of the `/research` loop.
- Prompt: `.claude/commands/research.md` (frontmatter stripped, `$ARGUMENTS` = 1) plus `scripts/research_daily_prompt.md` (unattended overrides).
- Guardrails: `research-promote` and `research-retire` are blocked in the tool allowlist, so any PASS or FORWARD_ONLY waits for the owner's approval. `evaluate.py` and `dsr.py` are checksummed before and after the run and restored from git if changed. The script refuses to start on a dirty repo.
- Output: `reports/research/last_run.txt` (idea, verdict, deciding gate, trial count, promotion status, journal path) goes to Telegram. Changes are committed locally on success. Nothing is pushed.
- Each run counts one trial in the `trials` table in Postgres (shared by every host that uses the same database; the count was reset to 0 on 2026-11-18). Every trial, pass or fail, raises the deflated-Sharpe bar for later ideas.
- Dry check without running Claude: `DRY_RUN=1 scripts/research_daily.sh`.

## Holiday lists

Both scripts read every `scripts/nse_holidays_<year>.txt` (one `YYYY-MM-DD` per line, `#` comments allowed, no trailing spaces; `TRADER_HOLIDAYS_FILE` overrides with a single file). **Add `nse_holidays_2027.txt` before January 2027.** If the current year has no file, the daily message starts with a warning and the run also happens on holidays (a stale-data WARNING may appear). `handoff_check.sh` fails when the current year's list is missing.

## Moving to a new Hermes host

1. All state is in Postgres, so a new host needs no data copy. Old host: `scripts/handoff_pack.sh [OUT_DIR]` writes `trader-state-<stamp>.tar.gz` containing only `config.yaml` and the git HEAD (no `.env`).
2. New host: clone the repo (`git log` has the research history), `tar -xzf <pack> -C <repo>`, create `.env` with the same `POSTGRES_HOST/PORT/USER/PASSWORD/DB` (see `.env.example`; copy it by hand, it is never packed), install `uv` (and the `claude` CLI for the research job), then `scripts/handoff_check.sh` (add `--quick` to skip tests). It checks the database is reachable and holds the paper ledger, then prints `READY` or lists failures.
3. Create the two Hermes cron jobs (timezone Asia/Kolkata, Mon-Fri): `16:30` runs `scripts/trader_daily.sh`; `18:30` runs `scripts/research_daily.sh`. Stdout of each is the Telegram message; empty stdout sends nothing.
4. Do not run `paper-momentum --reset` or `research-promote` on the new host: the ledger is a replay from frozen params in `paper_meta`. Ledger and research commands hold Postgres advisory locks, so two hosts cannot write at once, but only one host should run the scheduled jobs.
5. `trader_daily.sh` now also runs `fundamentals-snapshot --if-stale-days 7` after the daily run, so Hermes keeps building the dated fundamentals history (previously only `/daily` under Claude did).

## Where things live

- Everything is in Postgres (`POSTGRES_*` in the gitignored `.env`, which must be created by hand on a new host): candles, instruments, membership, fundamentals, the paper ledger (`paper_meta` + sleeve tables), research trials, generated outputs and `job_runs`. Read reports with `uv run trader show daily [date]`; `uv run trader db status` shows row counts. The paper ledger is a deterministic replay from frozen params, so `paper_meta` plus `config.yaml` matter; do not reset it.
- The server has no TLS (plaintext connection as of 2026-11-18): credentials and data cross the network unencrypted. Prefer an SSH tunnel or `POSTGRES_SSLMODE=require` once the server supports TLS.
- The pre-migration local files (`data/`, `reports/`) were deleted on 2026-11-18 after the verified import, so Postgres holds the only copy: take periodic `pg_dump` backups.
- Nothing has been pushed; the repo has local history only (an `origin` remote is configured but unused).

## Claude-only (not part of the Hermes run)

- Manual research runs (`/research N`, `trader research-*` by hand). The scheduled daily run is described above.
- `/daily` (`.claude/commands/daily.md`) summary routine, including its Dhan MCP account check (step 3). Dhan MCP is reachable only from Claude Code, not Hermes.
- `membership-snapshot` (about monthly, manual). `fundamentals-snapshot` now also runs from `trader_daily.sh`.

## Live trading

Deferred. `Config.mode` accepts "live" syntactically, but no code uses it and no order-placing code exists. If order placement is ever added it must refuse unless `mode == "live"` (`tests/test_config_mode.py` fails if order-placement strings appear in `src/`, as a reminder).
