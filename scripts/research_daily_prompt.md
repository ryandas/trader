
---

SCHEDULED RUN OVERRIDES (unattended; these rules override anything above):

- N = 1. Run steps 1 to 6 for ONE idea only. Do not start a second idea.
- Do NOT run `research-promote` or `research-retire`, and do not touch orders. If the verdict is PASS or FORWARD_ONLY, stop after step 6 and report "awaiting approval to promote <slug>". The owner promotes manually.
- Skip step 7 (the monthly recheck) in scheduled runs.
- Do not edit `src/trader/research/evaluate.py`, `src/trader/research/dsr.py`, or any promoted candidate file.
- If no untested idea is worth testing, stop with verdict NO IDEA and do not run `research-eval` (no trial is counted).
- Do not commit or push. The wrapper script commits the result.
- Last action: write `reports/research/last_run.txt` in exactly this format, then finish:

Idea: <slug> - <one-line idea>
Verdict: <PASS | FORWARD_ONLY | FAIL | NO IDEA>
Deciding gate: <gate name and its numbers, or "none">
Trial count: <counted trials after this run, from `uv run trader research-status`>
Promotion: <none (awaiting approval) | not applicable>
Journal: <research/journal/... path, or none>
