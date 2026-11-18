---
description: Run the daily paper-trading routine and summarise it (read-only, places no orders)
---

Run the daily routine for the systematic swing trader. This is read-only: **never place, modify
or cancel an order**, and do not call `trading_agent_tool`.

1. Run `uv run trader daily` from the project root (refreshes candles, advances the paper ledger,
   writes `reports/<date>.md` and `reports/<date>-orders.csv`). If it fails with a data or
   network error, report it instead of retrying in a loop. If it prints a stale-data warning,
   say so prominently.
   Also run `uv run trader fundamentals-snapshot --if-stale-days 7` (saves dated fundamentals for the research
   loop; it skips itself unless the newest copy is a week old; takes a few minutes when it does run).
2. Read the report it wrote.
3. **Claude-only; skipped under Hermes (Dhan MCP is not reachable there).** Load the Dhan MCP tool schema with ToolSearch (`select:mcp__dhan__portfolio_agent_tool`) and
   check the real account: funds, positions and holdings. Do not send any details beyond what the
   tool needs.
4. Reply with a short summary:
   - date and market regime
   - the momentum rotation sleeve: equity vs start, holdings, any BUY/SELL orders queued, and the
     date of the next monthly rebalance signal. Most days it will have no orders: it only trades
     around month end or when the market turns bearish
   - research candidate sleeves (the report has a "Research candidate sleeves" section when any are active):
     per sleeve its tier, days since start, forward return vs the index over the same days, holdings and queued
     orders, plus any sleeve listed under "NOT replayed" (a changed candidate file). Say plainly that forward
     results over a few weeks mean nothing yet, and flag a sleeve that has trailed the index for 6+ months
   - if the ledger still has a swing sleeve (the report then has swing sections too), summarise
     its queued orders, positions and recent trades as well
   - positions and any closed trades since the last report
   - anything anomalous: stale data, a regime change, an unusually large number of signals,
     paper positions that disagree with the real account (they are independent, so expect them to
     differ; just note whether the real account has any exposure at all)
5. Always restate the caveat printed at the top of the momentum section: its backtest is flattered
   by survivorship bias, so only the forward paper results mean anything. If a swing sleeve is
   present, also restate its evidence line (walk-forward vs buy-and-hold). Never present an order
   list as a recommendation to trade real money unless the report itself says the strategy beat
   buy-and-hold after costs in forward results.
