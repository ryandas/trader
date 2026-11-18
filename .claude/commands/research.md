---
description: Research and test ONE new strategy idea (backlog -> candidate -> fixed gates -> paper sleeve if it passes)
---

Run the strategy research loop for N ideas, where N is the number in `$ARGUMENTS` (default 1, maximum 5; for
example `/research 3`). **Paper only: never place, modify or cancel an order and never call `trading_agent_tool`.**
Every idea tested is counted, and the pass mark (deflated Sharpe) gets stricter as the trial count grows, so N ideas
cost the same as N separate runs. Do steps 2 to 6 fully and in order for ONE idea before starting the next; never
write several candidates first and compare them. Step 1 and step 8 happen once per run, step 7 once per run.

Hard rules (do not break these, even if a result is disappointing):
- Never edit `src/trader/research/evaluate.py`, `dsr.py` or the gates in them, and never edit a promoted
  candidate's file (the paper ledger refuses a sleeve whose file changed).
- Decide the grid (at most 4 points) BEFORE running the evaluation. Never choose or change parameters from OOS results.
- If the evaluation fails, do not tweak the same idea and re-run it in this session. A variant is a new idea
  for a later run and counts as a new trial.
- Within one run, a result must never change how a later idea in the same run is specified (no "that one worked, so
  let me try a nearby setting"). Each idea's grid is fixed before its own evaluation.
- Stop early if N ideas are not available: say so rather than inventing weak ones.
- No data we do not have: no point-in-time fundamentals history, intraday, options, news.
- A PASS only earns a forward paper sleeve. It is not evidence of an edge; say so.

Steps:
1. Check the data. Run `uv run trader research-status`. If the last candle bar is older than the last completed
   session, run `uv run trader update` first. If the newest fundamentals snapshot is 7 or more days old (or missing),
   run `uv run trader fundamentals-snapshot --if-stale-days 7`. Read `research/backlog.md` and the newest file in
   `research/journal/` (if any).
2. Pick the idea: the first user-added row in the backlog Queue, otherwise the top row. Before testing it, do two
   quick checks and write the answers in the journal: (a) evidence outside the US: read `research/india_evidence.md`
   first, then a short WebSearch only if the idea is not covered there (and append what you find to that file);
   say "none found" if so, and note that the seed ideas were written from US-centred memory;
   (b) fit for a small account: expected turnover and number of holdings against INR 5,000 (each sale pays a flat
   INR 15.34 DP charge), and fix the engine knobs in the grid (`top_n`, `buffer`, `rebalance` with M/W/Q/S) with that in
   mind BEFORE evaluating. Neither check may use any backtest result.
   REFILL THE QUEUE when fewer than 3 untested price/volume (backtestable) ideas remain (fundamentals ideas do not
   count, they are forward-only): search until about 6 are queued, adding at most 5 new rows per run. Where to look
   (WebSearch, standard mode; extended only for a hard-to-find niche fact): SSRN and NBER working papers, Quantpedia
   strategy pages, AQR and Alpha Architect research notes, arXiv q-fin, NSE/BSE index methodology documents and NSE
   research papers, Indian academic journals (IIMA, IIMB, ISB, Vikalpa), and emerging-market factor studies.
   Rules for what gets added: it needs a stated mechanism and a source you actually opened or saw cited by a reliable
   source (record which); price/volume only or forward-only fundamentals; implementable at low turnover (slow cadence,
   about 10 names); not a near-duplicate of a tested idea. Do NOT take ideas from social media, YouTube, tip or
   "signal" sites, paid-course pages or backtest screenshots. Published effects often weaken after publication: note
   that in the row. Record the source type in the row's source column. Do not search for ideas that "work in the current
   market": ideas are never chosen from recent performance. If nothing worthwhile is found, say so and stop: "no idea
   worth testing today" is a valid outcome. Check the citation of the idea you pick.
3. Write `src/trader/research/candidates/<slug>.py` following the contract in `src/trader/research/registry.py`
   (`META` with slug, kind="rotation", hypothesis, source, grid; `score(prep, **params)`, higher = buy, using only
   data up to each row's date). Look at `low_vol.py` for the shape. Engine knobs in a grid point (`top_n`, `buffer`,
   `bear_exit`, `rebalance`) configure the rotation; every other key goes to `score`. Fundamentals ideas set
   `uses_fundamentals: True`, a single grid point, and read `prep.fund_panel("<field>")`.
   Add a unit test for the scoring logic in `tests/test_research.py` (or a new test file).
4. `uv run pytest -q`, then `uv run trader research-eval <slug>`. Read `reports/research/<slug>/summary.md`.
5. If the verdict is PASS or FORWARD_ONLY: `uv run trader research-promote <slug>` (adds a paper sleeve, max 5).
   If FAIL: do not promote. Work out whether it failed for an explainable reason (for example a cost or affordability
   effect at INR 5,000) and record that.
6. Run `uv run trader market-context` once per run and paste its output into each journal entry under "Market context"
   (informational only: it must never influence which idea is tested, its grid, or the verdict; it only records the
   conditions, for example that the index was just above its 200-day average). Write `research/journal/<YYYY-MM-DD>-<slug>.md`:
   hypothesis, source, grid, the gate table, the controls
   (index, equal-weight basket, random picks, default momentum), verdict and what you learned. Move the idea to "Done"
   in `research/backlog.md`; put any follow-up variant under "Ideas that came out of results".
7. Once a month (the first run on or after the 1st), run `uv run trader research-eval <slug> --recheck` for each active
   candidate sleeve as an informational check (it is not counted as a new trial) and note any that now fail the gates.
8. Reply with a short summary: for each idea its verdict and the gate that decided it, the trial count so far, and active sleeves. Restate
   that a backtest result is not evidence (universe = today's NIFTY 500, survivorship bias) and only forward paper
   results mean anything. Never present anything as a recommendation to trade real money.
