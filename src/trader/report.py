from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import backtest as bt
from .config import ROOT, Config
from .metrics import summarize
from .paper import MomState, PaperState


def _evidence_line(cfg: Config) -> str:
    """One honest line on what the walk-forward showed, read from its saved output."""
    eq_p, tr_p = ROOT / "reports/walkforward/oos_equity.csv", ROOT / "reports/walkforward/oos_trades.csv"
    if not eq_p.exists():
        return "No walk-forward evidence on file. Treat these signals as unvalidated."
    eq = pd.read_csv(eq_p, index_col=0, parse_dates=True)
    m = summarize(eq, pd.read_csv(tr_p) if tr_p.exists() else pd.DataFrame(), bt.load_benchmark(cfg))
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


def _momentum_section(cfg: Config, m: MomState, day, csv_path: Path) -> str:
    r, prep = m.result, m.prep
    li = prep.dates.get_loc(m.last_date)
    eq = r.equity["equity"]
    pos = pd.DataFrame([{
        "symbol": prep.syms[si], "qty": q["qty"], "entry": round(q["px"], 2),
        "last": round(float(prep.c[li, si]), 2), "days": li - q["d"],
        "unrealised": round((float(prep.c[li, si]) - q["px"]) * q["qty"]),
        "weight_pct": round(100 * q["qty"] * float(prep.c[li, si]) / r.equity["value"].iloc[-1], 1),
    } for si, q in r.positions.items()])
    orders = pd.DataFrame(
        [{"side": "SELL", "symbol": prep.syms[si], "reason": why, "approx_qty": "-"} for si, why in r.pending_sells.items()]
        + [{"side": "BUY", "symbol": prep.syms[si], "reason": "rebalance",
            "approx_qty": int(tv // float(prep.c[li, si]))} for si, tv in r.pending_buys])
    orders.to_csv(csv_path, index=False)
    nxt = (m.last_date + pd.offsets.BMonthEnd(0)).date()
    nxt_txt = ("orders above fill at the next open" if prep.rebal[li]
               else f"next rebalance signal: close of {nxt} (orders fill the following open)")
    reg = {0: "BEAR (cash)", 1: "neutral", 2: "bull"}[int(prep.mkt[li])]
    ret = 100 * (eq.iloc[-1] / m.capital - 1)  # time-weighted: deposits are not profit
    val, paid = float(r.equity["value"].iloc[-1]), float(r.equity["deposited"].iloc[-1])
    if len(r.equity) > 1:
        mt = summarize(r.equity, r.trades, bt.load_benchmark(cfg))
        perf = "\n".join(f"- {k}: {v}" for k, v in mt.items())
    else:
        perf = "_sleeve just started: no performance yet_"
    wf_p = ROOT / "reports/momentum-wf/oos_equity.csv"
    ev = ""
    if wf_p.exists():
        w = summarize(pd.read_csv(wf_p, index_col=0, parse_dates=True), pd.DataFrame(), bt.load_benchmark(cfg))
        ev = (f"Backtest walk-forward OOS ({w['start']} to {w['end']}): CAGR {w['cagr_pct']}% vs NIFTY 500 "
              f"{w.get('benchmark_cagr_pct', 'n/a')}%. ")
    return f"""
---

# Momentum rotation sleeve (paper)

> **Paper only.** {ev}{MOM_CAVEAT}

- Params (frozen): `{m.params.label()}`{f", liquid top {m.liquid_top}" if m.liquid_top else ""}
- Sleeve started {m.start.date()} | Value ₹{val:,.0f} on ₹{paid:,.0f} paid in (₹{m.capital:,.0f} start + ₹{m.contribution:,.0f} each month-end) | Time-weighted return {ret:+.2f}% | Invested {100 * r.equity["invested"].iloc[-1]:.0f}%
- Market regime: **{reg}** | Holdings: {len(r.positions)}/{m.params.top_n} | {nxt_txt}

## Momentum orders for next session
{_md_table(orders)}
## Momentum holdings
{_md_table(pos)}
## Momentum performance since sleeve start
{perf}
"""


CAND_CAVEAT = (
    "Research candidates trade on paper only, from their start date. A backtest PASS merely earned the right to be "
    "paper traded; only these forward numbers count, and months of them are needed before they mean anything."
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
    return f"\n---\n\n# Research candidate sleeves (paper)\n\n> **Paper only.** {CAND_CAVEAT}\n\n" + "\n".join(blocks)


def _momentum_only_report(cfg: Config, st: PaperState) -> tuple[Path, Path]:
    day = st.last_date.date()
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    csv_path = out / f"{day}-momentum-orders.csv"
    warn = ("\n> **DATA MAY BE STALE** — latest bar is older than the last completed session. "
            "Run `trader update`.\n" if st.stale else "")
    section = _momentum_section(cfg, st.mom, day, csv_path).replace("\n---\n\n", "\n", 1)
    md_path = out / f"{day}.md"
    md_path.write_text(f"# Paper trading report: {day}\n{warn}{section}{_candidates_section(cfg, st)}")
    return md_path, csv_path


def write_report(cfg: Config, st: PaperState) -> tuple[Path, Path]:
    if st.result is None:  # swing sleeve not in the ledger
        return _momentum_only_report(cfg, st)
    res, day = st.result, st.last_date.date()
    eq = res.equity["equity"]
    ret = 100 * (eq.iloc[-1] / st.capital - 1)

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

    recent = res.trades.tail(10)[["symbol", "strategy", "entry_date", "exit_date", "qty",
                                  "entry_price", "exit_price", "reason", "net_pnl"]].copy() if len(res.trades) else pd.DataFrame()
    for c in ("entry_date", "exit_date"):
        if c in recent:
            recent[c] = pd.to_datetime(recent[c]).dt.date

    if len(res.equity) > 1:
        m = summarize(res.equity, res.trades, bt.load_benchmark(cfg))
        perf = "\n".join(f"- {k}: {v}" for k, v in m.items())
    else:
        perf = "_ledger just started: no performance yet_"

    warn = "\n> **DATA MAY BE STALE** — latest bar is older than the last completed session. Run `trader update`.\n" if st.stale else ""
    mom_md = _momentum_section(cfg, st.mom, day, ROOT / "reports" / f"{day}-momentum-orders.csv") if st.mom else ""
    md = f"""# Paper trading report: {day}

> **Paper only. Do not place real orders from this list.** {_evidence_line(cfg)}
{warn}
- Market regime (NIFTY 500): **{st.regime}**
- Ledger start: {st.start.date()} | Equity: ₹{eq.iloc[-1]:,.0f} ({ret:+.2f}% vs ₹{st.capital:,.0f})
- Open positions: {len(res.positions)} | Orders for next session: {len(res.pending)}

## Orders for next session
{_md_table(orders)}
## Open positions
{_md_table(pos)}
## Recent closed trades
{_md_table(recent)}
## Performance since paper start
{perf}

_Universe is today's NIFTY 500 (survivorship bias in backtests; the paper ledger itself is forward-only from its start date)._
{mom_md}{_candidates_section(cfg, st)}"""
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    md_path, csv_path = out / f"{day}.md", out / f"{day}-orders.csv"
    md_path.write_text(md)
    orders.to_csv(csv_path, index=False)
    return md_path, csv_path
