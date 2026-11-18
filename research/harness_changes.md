# Research harness changes

## 2026-11-18: storage moved to Postgres; trial registry reset to 0

- Change: the trial registry (`trials`), research-eval outputs, ledger, candles, fundamentals and membership moved from local
  SQLite/parquet/CSV to Postgres (`src/trader/db.py`, `outputs.py`). `trials` is append-only via a database trigger. Gate formulas,
  grids and `HARNESS_VERSION` are unchanged (`src/trader/research/evaluate.py` only changed where it reads and writes stored outputs).
- Trial count: reset to 0 at the user's request (second reset). The six trials since the first reset were not in the migrated
  database anyway (it held 26 older pre-reset rows), so they are not carried over; their journals were removed from the working
  tree (kept in git history). The deflated-Sharpe bar restarts from N=1: results before and after this date are not comparable
  on that gate.

## 2026-11-18: `walkforward._chain` keeps each fold's first-day return (REVIEW L3)

- Change: `_chain` used to rescale each fold so its first row equalled the carried level
  (`equity / equity.iloc[0] * level`), which forced the first-day return of every fold to 0%. It now scales by the
  fold's starting capital (`equity / capital * level`), so day-1's return is kept. Files: `src/trader/walkforward.py`,
  test in `tests/test_walkforward.py`. `src/trader/research/evaluate.py` (gate file) was not edited; it calls
  `wf._chain`, so the change reaches the gates through that call.
- All trials before this date were measured with the old chaining and are not directly comparable with later ones.
  The effect is expected to be small (with `warm_start` the first day is mostly cash).
- The trial count continues (no reset). `HARNESS_VERSION` and frozen parameters are unchanged.
