from __future__ import annotations

import pandas as pd

from . import backtest as bt
from . import outputs
from .config import Config
from .metrics import summarize
from .paper import MomState, PaperState


def _evidence_line(cfg: Config) -> str:
    """One honest line on what the walk-forward showed, read from its saved output."""
    wf = outputs.get("walkforward")
    if not wf or "oos_equity" not in wf:
        return "No walk-forward evidence on file. Treat these signals as unvalidated."
    tr = wf.get("oos_trades")
    m = summarize(wf["oos_equity"], tr if tr is not None else pd.DataFrame(), bt.load_benchmark(cfg))
    verdict = "did NOT beat" if m["cagr_pct"] < m.get("benchmark_cagr_pct", -1e9) else "beat"
    return (
        f"Walk-forward out-of-sample ({m['start']} to {m['end']}): CAGR {m['cagr_pct']}% vs "
        f"NIFTY 500 {m.get('benchmark_cagr_pct', 'n/a')}%, max drawdown {m['max_drawdown_pct']}%. "
        f"The strategies {verdict} buy-and-hold after costs."
    )


def _md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_none_\n"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines) + "\n"


MOM_CAVEAT = (
    "Backtests use today's NIFTY 500 constituents (survivorship bias): on the most liquid names the "
    "edge shrank below the index. Only this forward ledger is unbiased."
)

ARBITRATION = (
    "Both sleeves draw on this one cash balance. On a shared session all sells/exits run first, then momentum's "
    "rebalance buys, then swing's entries; a buy is cut to the cash left and skipped if that is under half its "
    "intended size. Momentum targets and swing risk are measured against total account equity."
)


def _account_section(st: PaperState) -> str:
    """The account: cash + each sleeve's positions = account equity, so the sections add up by construction."""
    a, spec = st.account, st.account_spec
    e = a.equity
    last = e.iloc[-1]
    paid = float(last["deposited"])
    twr = 100 * (float(last["equity"]) / spec.capital - 1)  # time-weighted: deposits are not profit
    rows = [{"component": "Cash", "inr": f"{last['cash']:,.0f}"}]
    if a.swing is not None:
        rows.append({"component": f"Swing sleeve positions ({len(a.swing.positions)} open)", "inr": f"{last['swing_value']:,.0f}"})
    if a.mom is not None:
        rows.append({"component": f"Momentum sleeve positions ({len(a.mom.positions)} holdings)", "inr": f"{last['mom_value']:,.0f}"})
    rows.append({"component": "**Account equity**", "inr": f"**{last['value']:,.0f}**"})
    return f"""## Account (one shared cash account)
- Ledger start {spec.start.date()} | Paid in ₹{paid:,.0f} (₹{spec.capital:,.0f} start + ₹{spec.contribution:,.0f} once per month-end) | Account equity ₹{last['value']:,.0f} | Profit ₹{last['value'] - paid:+,.0f} | Time-weighted return {twr:+.2f}%
- {ARBITRATION}

{_md_table(pd.DataFrame(rows))}"""


def _account_performance(st: PaperState, cfg: Config) -> str:
    a = st.account
    if len(a.equity) <= 1:
        return "_ledger just started: no performance yet_"
    parts = [t for t in (a.swing.trades if a.swing is not None else None, a.mom.trades if a.mom is not None else None)
             if t is not None and len(t)]
    cols = ["net_pnl", "bars_held", "costs"]
    trades = pd.concat([t[cols] for t in parts], ignore_index=True) if parts else pd.DataFrame(columns=cols)
    m = summarize(a.equity, trades, bt.load_benchmark(cfg))
    return "\n".join(f"- {k}: {v}" for k, v in m.items())


def _sleeve_pnl(trades: pd.DataFrame) -> str:
    if not len(trades):
        return "no closed trades yet"
    return f"{len(trades)} closed trades, net P&L ₹{trades['net_pnl'].sum():+,.0f}, charges ₹{trades['costs'].sum():,.0f}"


def _momentum_section(cfg: Config, st: PaperState, orders_out: dict) -> str:
    m: MomState = st.mom
    r, prep = m.result, m.prep
    value = float(st.account.equity["value"].iloc[-1])
    li = prep.dates.get_loc(m.last_date)
    pos = pd.DataFrame([{
        "symbol": prep.syms[si], "qty": q["qty"], "entry": round(q["px"], 2),
        "last": round(float(prep.c[li, si]), 2), "days": li - q["d"],
        "unrealised": round((float(prep.c[li, si]) - q["px"]) * q["qty"]),
        "pct_of_account": round(100 * q["qty"] * float(prep.c[li, si]) / value, 1),
    } for si, q in r.positions.items()])
    orders = pd.DataFrame(
        [{"side": "SELL", "symbol": prep.syms[si], "reason": why, "approx_qty": "-"} for si, why in r.pending_sells.items()]
        + [{"side": "BUY", "symbol": prep.syms[si], "reason": "rebalance",
            "approx_qty": int(tv // float(prep.c[li, si]))} for si, tv in r.pending_buys])
    orders_out["momentum-orders"] = orders
    nxt = (m.last_date + pd.offsets.BMonthEnd(0)).date()
    nxt_txt = ("orders above fill at the next open" if prep.rebal[li]
               else f"next rebalance signal: close of {nxt} (orders fill the following open)")
    reg = {0: "BEAR (cash)", 1: "neutral", 2: "bull"}[int(prep.mkt[li])]
    mwf = outputs.get("momentum-wf", "", "oos_equity")
    ev = ""
    if mwf is not None:
        w = summarize(mwf, pd.DataFrame(), bt.load_benchmark(cfg))
        ev = (f"Backtest walk-forward OOS ({w['start']} to {w['end']}): CAGR {w['cagr_pct']}% vs NIFTY 500 "
              f"{w.get('benchmark_cagr_pct', 'n/a')}%. ")
    return f"""
---

# Momentum rotation sleeve (paper)

> **Paper only.** {ev}{MOM_CAVEAT}

- Params (frozen): `{m.params.label()}`{f", liquid top {m.liquid_top}" if m.liquid_top else ""}
- Sleeve started {m.start.date()} | Positions ₹{r.equity['value'].iloc[-1]:,.0f} ({100 * r.equity['value'].iloc[-1] / value:.0f}% of account) | {_sleeve_pnl(r.trades)}
- Market regime: **{reg}** | Holdings: {len(r.positions)}/{m.params.top_n} (each new buy targets 1/{m.params.top_n} of account equity) | {nxt_txt}

## Momentum orders for next session
{_md_table(orders)}
## Momentum holdings
{_md_table(pos)}"""


CAND_CAVEAT = (
    "Research candidates trade on paper only, from their start date. A backtest PASS merely earned the right to be "
    "paper traded; only these forward numbers count, and months of them are needed before they mean anything. "
    "They are NOT part of the account above: each is an isolated replay with its own capital."
)


def _candidates_section(cfg: Config, st: PaperState) -> str:
    if not st.cands and not st.cand_errors:
        return ""
    bench = bt.load_benchmark(cfg)
    blocks = []
    for tier, title in (("backtest_pass", "Research candidates (forward paper)"),
                        ("forward_only", "Research candidates: NO backtest evidence, forward results only")):
        rows = []
        for slug, c in st.cands.items():
            if c.tier != tier:
                continue
            r, prep = c.result, c.prep
            eq = r.equity["equity"]
            b = bench.reindex(eq.index).ffill() if bench is not None else None
            idx_ret = f"{100 * (b.iloc[-1] / b.iloc[0] - 1):+.2f}%" if b is not None and len(b) > 1 else "n/a"
            li = prep.dates.get_loc(c.last_date)
            reb = prep.rebal_mask(c.params.rebalance)
            step = {"W": pd.offsets.Week(weekday=4), "M": pd.offsets.BMonthEnd(0),
                    "Q": pd.offsets.BQuarterEnd(0, startingMonth=3), "S": pd.offsets.BMonthEnd(0)}[c.params.rebalance]
            nxt_d = c.last_date + step
            if c.params.rebalance == "S":  # next Jun / Dec month end
                while nxt_d.month not in (6, 12):
                    nxt_d = nxt_d + pd.offsets.BMonthEnd(1)
            nxt = "orders fill at the next open" if reb[li] else f"next signal: close of {nxt_d.date()}"
            rows.append({
                "sleeve": slug, "start": c.start.date(), "days": len(eq),
                "value": f"{r.equity['value'].iloc[-1]:,.0f}", "paid_in": f"{r.equity['deposited'].iloc[-1]:,.0f}",
                "return": f"{100 * (eq.iloc[-1] / c.capital - 1):+.2f}%",
                "index_same_period": idx_ret, "holdings": len(r.positions),
                "orders": f"{len(r.pending_sells)} sell / {len(r.pending_buys)} buy", "next": nxt,
            })
        if rows:
            blocks.append(f"## {title}\n{_md_table(pd.DataFrame(rows))}")
    if st.cand_errors:
        blocks.append("## Candidate sleeves NOT replayed\n" + "\n".join(f"- `{k}`: {v}" for k, v in st.cand_errors.items()) + "\n")
    return f"\n---\n\n# Research candidate sleeves (paper, outside the account)\n\n> **Paper only.** {CAND_CAVEAT}\n\n" + "\n".join(blocks)


def _ref(day, item: str = "") -> str:
    return f"trader show daily {day}" + (f" {item}" if item else "")


def _swing_section(cfg: Config, st: PaperState, items: dict) -> str:
    res = st.result
    value = float(st.account.equity["value"].iloc[-1])
    pos = pd.DataFrame([{
        "symbol": p.sym, "strategy": p.strat, "qty": p.qty, "entry": round(p.entry_price, 2),
        "last": round(p.last_close, 2), "stop": round(p.stop, 2),
        "target": round(p.target, 2) if p.target else "-",
        "unrealised": round((p.last_close - p.entry_price) * p.qty),
        "days": p.bars_held, "exit_flag": p.exit_pending or "-",
    } for p in res.positions])

    orders = pd.DataFrame([{
        "symbol": o.sym, "strategy": o.strat, "type": "buy-stop" if o.entry_type == "stop" else "buy at open",
        "trigger": round(o.trigger, 2) if o.trigger else "-",
        "max_price": round(o.max_entry, 2) if o.max_entry else "-",
        "stop": round(o.stop, 2), "target": round(o.target, 2) if o.target else "-",
        "qty": o.qty, "est_entry": round(o.est_entry, 2), "risk_inr": round(o.qty * (o.est_entry - o.stop)),
    } for o in res.pending])
    items["orders"] = orders

    recent = res.trades.tail(10)[["symbol", "strategy", "entry_date", "exit_date", "qty",
                                  "entry_price", "exit_price", "reason", "net_pnl"]].copy() if len(res.trades) else pd.DataFrame()
    for c in ("entry_date", "exit_date"):
        if c in recent:
            recent[c] = pd.to_datetime(recent[c]).dt.date
    sv = float(res.equity["value"].iloc[-1])
    return f"""
---

# Swing sleeve (paper)

- Sleeve started {st.start.date()} | Positions ₹{sv:,.0f} ({100 * sv / value:.0f}% of account) | {_sleeve_pnl(res.trades)}
- Open positions: {len(res.positions)} | Orders for next session: {len(res.pending)} (sized on total account equity; filled from the shared cash after momentum's buys)

## Swing orders for next session
{_md_table(orders)}
## Swing open positions
{_md_table(pos)}
## Swing recent closed trades
{_md_table(recent)}"""


def write_report(cfg: Config, st: PaperState) -> tuple[str, str]:
    """Store the day's report (and order tables) in the database; returns `trader show` references."""
    day = st.last_date.date()
    items: dict = {}
    warn = ("\n> **DATA MAY BE STALE** — latest bar is older than the last completed session. "
            "Run `trader update`.\n" if st.stale else "")
    evidence = _evidence_line(cfg) if st.result is not None else ""
    swing_md = _swing_section(cfg, st, items) if st.result is not None else ""
    mom_md = _momentum_section(cfg, st, items) if st.mom is not None else ""
    md = f"""# Paper trading report: {day}

> **Paper only. Do not place real orders from this list.** {evidence}
{warn}
- Market regime (NIFTY 500): **{st.regime}**

{_account_section(st)}
## Account performance since ledger start
{_account_performance(st, cfg)}

_Universe is today's NIFTY 500 (survivorship bias in backtests; the paper ledger itself is forward-only from its start date)._
{swing_md}{mom_md}{_candidates_section(cfg, st)}"""
    items["report"] = md
    outputs.save("daily", str(day), items, {"stale": st.stale})
    return _ref(day), _ref(day, "orders" if st.result is not None else "momentum-orders")
