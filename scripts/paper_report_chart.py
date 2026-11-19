"""Chart the paper ledger from Postgres: equity per sleeve, open positions, queued orders.

Paper only. Reads the `equity`, `mom_equity`, `positions`, `orders`, `mom_orders` tables
(no benchmark series is stored, so none is plotted). Writes one PNG and prints its path.

Usage: uv run python scripts/paper_report_chart.py [--out PATH]
Default output: $TRADER_CHART_DIR/paper_report_<latest equity date>.png (TRADER_CHART_DIR defaults to <repo>/charts).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from trader import db  # noqa: E402


def _table(sql: str) -> pd.DataFrame:
    try:
        return db.qdf(sql)
    except Exception:  # table missing on a fresh DB: chart what exists
        return pd.DataFrame()


def build(out: Path) -> Path:
    swing = _table("SELECT date, equity, invested FROM equity ORDER BY date")
    mom = _table("SELECT date, value, deposited, equity FROM mom_equity ORDER BY date")
    pos = _table("SELECT sym, strat, qty, entry_price, entry_date, last_close, init_stop, stop FROM positions ORDER BY sym")
    orders = _table("SELECT sym, strat, entry_type, max_entry, stop, qty, est_entry FROM orders ORDER BY sym")
    mom_orders = _table("SELECT side, symbol, reason, target_value FROM mom_orders ORDER BY symbol")

    fig = plt.figure(figsize=(11, 10), constrained_layout=True)
    gs = fig.add_gridspec(3, 2, height_ratios=[1.3, 1, 1.1])
    fig.suptitle("Paper ledger report (paper only, no real orders)", fontsize=14, weight="bold")

    # Equity per sleeve, as INR and as % vs capital paid in.
    ax = fig.add_subplot(gs[0, :])
    if not swing.empty:
        ax.plot(pd.to_datetime(swing["date"]), swing["equity"], marker="o", label="Swing sleeve equity (₹)")
    if not mom.empty:
        ax.plot(pd.to_datetime(mom["date"]), mom["value"], marker="s", label="Momentum sleeve value (₹)")
        ax.plot(pd.to_datetime(mom["date"]), mom["deposited"], linestyle=":", color="grey", label="Momentum paid in (₹)")
    ax.set_title("Equity by sleeve")
    ax.set_ylabel("INR")
    ax.ticklabel_format(axis="y", style="plain", useOffset=False)
    ax.xaxis.set_major_locator(matplotlib.dates.DayLocator())
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%Y-%m-%d"))
    ax.grid(alpha=0.3)
    ax.legend(loc="best")
    if swing.empty and mom.empty:
        ax.text(0.5, 0.5, "No equity rows yet", ha="center", va="center", transform=ax.transAxes)

    # Return since start per sleeve (%), from the first row of each sleeve.
    ax2 = fig.add_subplot(gs[1, 0])
    labels, vals = [], []
    if not swing.empty:
        s0 = float(swing["equity"].iloc[0])
        labels.append("Swing")
        vals.append((float(swing["equity"].iloc[-1]) / s0 - 1) * 100 if s0 else 0.0)
    if not mom.empty:
        paid = float(mom["deposited"].iloc[-1])
        labels.append("Momentum")
        vals.append((float(mom["value"].iloc[-1]) / paid - 1) * 100 if paid else 0.0)
    if labels:
        bars = ax2.bar(labels, vals, color=["#1f77b4", "#2ca02c"][: len(labels)])
        ax2.axhline(0, color="black", lw=0.8)
        for b, v in zip(bars, vals):
            ax2.annotate(f"{v:+.2f}%", (b.get_x() + b.get_width() / 2, v), ha="center",
                         xytext=(0, 4 if v >= 0 else -12), textcoords="offset points")
        lim = max(1.0, max(abs(v) for v in vals) * 1.5)
        ax2.set_ylim(-lim, lim)
    ax2.set_title("Return since sleeve start (%)")
    ax2.grid(axis="y", alpha=0.3)

    # Open positions.
    ax3 = fig.add_subplot(gs[1, 1])
    ax3.axis("off")
    ax3.set_title("Open positions (swing)")
    if pos.empty:
        ax3.text(0.5, 0.5, "No open positions", ha="center", va="center", transform=ax3.transAxes)
    else:
        rows = []
        for r in pos.itertuples():
            pnl = (float(r.last_close) - float(r.entry_price)) * int(r.qty)
            rows.append([r.sym, r.strat, str(int(r.qty)), f"{float(r.entry_price):.2f}",
                         f"{float(r.last_close):.2f}", f"{pnl:+.0f}", f"{float(r.stop):.2f}"])
        t = ax3.table(cellText=rows, colLabels=["Sym", "Strat", "Qty", "Entry", "Last", "P/L ₹", "Stop"],
                      loc="center", cellLoc="center")
        t.auto_set_font_size(False)
        t.set_fontsize(9)
        t.scale(1, 1.4)

    # Orders queued for the next session + momentum orders.
    ax4 = fig.add_subplot(gs[2, :])
    ax4.axis("off")
    ax4.set_title("Queued for next session")
    if orders.empty and mom_orders.empty:
        ax4.text(0.5, 0.5, "No orders queued", ha="center", va="center", transform=ax4.transAxes)
    else:
        rows = [[r.sym, r.strat, r.entry_type, f"{float(r.max_entry):.2f}" if pd.notna(r.max_entry) else "-",
                 f"{float(r.stop):.2f}" if pd.notna(r.stop) else "-", str(int(r.qty)),
                 f"{float(r.est_entry):.2f}" if pd.notna(r.est_entry) else "-"] for r in orders.itertuples()]
        if rows:
            t = ax4.table(cellText=rows, colLabels=["Sym", "Strat", "Type", "Max", "Stop", "Qty", "Est."],
                          loc="upper center", cellLoc="center")
            t.auto_set_font_size(False)
            t.set_fontsize(9)
            t.scale(1, 1.4)
        if not mom_orders.empty:
            txt = "Momentum orders: " + ", ".join(f"{r.side} {r.symbol}" for r in mom_orders.itertuples())
            ax4.text(0.0, 0.0, txt, transform=ax4.transAxes, fontsize=9)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    if args.out is None:
        d = _table("SELECT max(date) AS d FROM equity")
        stamp = str(d["d"].iloc[0])[:10] if not d.empty and d["d"].iloc[0] is not None else "latest"
        chart_dir = Path(os.environ.get("TRADER_CHART_DIR", REPO / "charts"))
        args.out = chart_dir / f"paper_report_{stamp}.png"
    print(build(args.out))


if __name__ == "__main__":
    main()
