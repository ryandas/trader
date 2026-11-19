"""Chart the paper ledger from Postgres: the one shared account, per-sleeve values, holdings and queued orders.

Paper only. Reads `account_equity` (written by `trader daily`: cash + swing positions + momentum positions = account
value), `positions` / `orders` (swing) and `mom_positions` / `mom_orders` (momentum). The two sleeves draw on ONE cash
balance, so the equity panel is a stack: cash + swing + momentum = account value. No benchmark series is stored, so none
is plotted. Writes one PNG and prints its path.

Usage: uv run python scripts/paper_report_chart.py [--out PATH]
Default output: $TRADER_CHART_DIR/paper_report_<latest account date>.png (TRADER_CHART_DIR defaults to <repo>/charts).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from trader import db  # noqa: E402

ROW_IN = 0.30  # inches per table row: tall enough for 9pt text, so no table is clipped
COLORS = {"cash": "#9aa5b1", "swing": "#1f77b4", "mom": "#2ca02c", "paid": "#444444"}


def _table(sql: str) -> pd.DataFrame:
    try:
        return db.qdf(sql)
    except Exception:  # table missing on a fresh DB: chart what exists
        return pd.DataFrame()


def _draw_table(ax, title: str, header: list[str], rows: list[list[str]], empty: str,
                 col_widths: list[float] | None = None) -> None:
    """A table filling its whole axes. The axes height is set from the row count by the caller."""
    ax.axis("off")
    ax.set_title(title, loc="left", fontsize=10, weight="bold")
    if not rows:
        ax.text(0.5, 0.5, empty, ha="center", va="center", transform=ax.transAxes, color="#666666")
        return
    t = ax.table(cellText=rows, colLabels=header, loc="center", cellLoc="center", bbox=[0, 0, 1, 1],
                    colWidths=col_widths)
    t.auto_set_font_size(False)
    t.set_fontsize(9)


def _n(rows: int) -> int:
    return max(rows, 1) + 1  # header + rows (an empty table still shows one line of text)


def build(out: Path) -> Path:
    acct = _table("SELECT date, equity, value, cash, swing_value, mom_value, deposited FROM account_equity ORDER BY date")
    swing_pos = _table("SELECT sym, strat, qty, entry_price, last_close, stop FROM positions ORDER BY sym")
    swing_ord = _table("SELECT sym, strat, entry_type, max_entry, stop, qty, est_entry FROM orders ORDER BY sym")
    mom_pos = _table("SELECT symbol, qty, entry_price, entry_date, last_close FROM mom_positions ORDER BY symbol")
    mom_ord = _table("SELECT side, symbol, reason, target_value FROM mom_orders ORDER BY side, symbol")

    value = float(acct["value"].iloc[-1]) if not acct.empty else 0.0
    mom_rows = []
    for r in mom_pos.itertuples():
        mv, pnl = float(r.last_close) * int(r.qty), (float(r.last_close) - float(r.entry_price)) * int(r.qty)
        mom_rows.append([r.symbol, str(int(r.qty)), f"{float(r.entry_price):.2f}", f"{float(r.last_close):.2f}",
                         f"{pnl:+,.0f}", f"{mv:,.0f}", f"{100 * mv / value:.1f}%" if value else "-"])
    swing_rows = []
    for r in swing_pos.itertuples():
        mv, pnl = float(r.last_close) * int(r.qty), (float(r.last_close) - float(r.entry_price)) * int(r.qty)
        swing_rows.append([r.sym, r.strat, str(int(r.qty)), f"{float(r.entry_price):.2f}", f"{float(r.last_close):.2f}",
                           f"{pnl:+,.0f}", f"{mv:,.0f}", f"{float(r.stop):.2f}"])
    order_rows = [["Swing", "BUY", r.sym, f"{int(r.qty)} @ {r.entry_type} · est {float(r.est_entry):.2f}"
                   + (f" · max {float(r.max_entry):.2f}" if pd.notna(r.max_entry) else "") + f" · stop {float(r.stop):.2f}"]
                  for r in swing_ord.itertuples()]
    order_rows += [["Momentum", str(r.side).upper(), r.symbol,
                    (f"rebalance, target ₹{float(r.target_value):,.0f}" if pd.notna(r.target_value) else str(r.reason))]
                   for r in mom_ord.itertuples()]

    ratios = [7, 2.6, _n(len(mom_rows)) + 1.2, _n(len(swing_rows)) + 1.2, _n(len(order_rows)) + 1.2]
    fig = plt.figure(figsize=(11, sum(ratios) * ROW_IN + 1.0), constrained_layout=True)
    gs = fig.add_gridspec(len(ratios), 1, height_ratios=ratios)
    fig.suptitle("Paper ledger: one shared cash account (paper only, no real orders)", fontsize=14, weight="bold")

    # 1. Account value, stacked: cash + swing positions + momentum positions = account equity.
    ax = fig.add_subplot(gs[0])
    if acct.empty:
        ax.text(0.5, 0.5, "No account rows yet (run `trader daily`)", ha="center", va="center", transform=ax.transAxes)
        ax.axis("off")
    else:
        d = pd.to_datetime(acct["date"])
        ax.stackplot(d, acct["cash"], acct["swing_value"], acct["mom_value"], step="post", alpha=0.85,
                     colors=[COLORS["cash"], COLORS["swing"], COLORS["mom"]],
                     labels=["Cash", "Swing positions", "Momentum positions"])
        ax.step(d, acct["deposited"], where="post", color=COLORS["paid"], linestyle=":", label="Paid in")
        ax.plot(d, acct["value"], color="black", lw=1.2, marker="o", ms=3, label="Account equity")
        last = acct.iloc[-1]
        ax.annotate(f"₹{last['value']:,.0f}", (d.iloc[-1], last["value"]), xytext=(-6, 8), textcoords="offset points",
                    ha="right", weight="bold")
        ax.set_title(f"Account equity ₹{last['value']:,.0f} = cash ₹{last['cash']:,.0f} + swing ₹{last['swing_value']:,.0f}"
                     f" + momentum ₹{last['mom_value']:,.0f}   (paid in ₹{last['deposited']:,.0f})", loc="left", fontsize=10)
        ax.set_ylim(0, float(max(acct["value"].max(), acct["deposited"].max())) * 1.2)  # headroom for the legend
        ax.set_ylabel("INR")
        ax.ticklabel_format(axis="y", style="plain", useOffset=False)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        ax.grid(alpha=0.3)
        ax.legend(loc="upper left", ncol=5, fontsize=8)

    # 2. Latest composition and profit over money paid in.
    ax2 = fig.add_subplot(gs[1])
    if acct.empty:
        ax2.axis("off")
    else:
        last = acct.iloc[-1]
        left = 0.0
        for key, label in (("cash", "Cash"), ("swing_value", "Swing"), ("mom_value", "Momentum")):
            v = float(last[key])
            c = COLORS["cash" if key == "cash" else "swing" if key == "swing_value" else "mom"]
            ax2.barh([0], [v], left=left, color=c, label=label)
            if value and v / value > 0.06:
                ax2.text(left + v / 2, 0, f"{label}\n₹{v:,.0f} ({100 * v / value:.0f}%)", ha="center", va="center",
                         color="white", fontsize=8, weight="bold")
            left += v
        profit = float(last["value"] - last["deposited"])
        ax2.set_title(f"Where the account is now. Profit over paid in: ₹{profit:+,.0f} "
                      f"({100 * profit / float(last['deposited']):+.2f}%)", loc="left", fontsize=10)
        ax2.set_yticks([])
        ax2.set_xlim(0, max(value, 1))
        ax2.ticklabel_format(axis="x", style="plain", useOffset=False)

    # 3-5. Tables, each in an axes tall enough for its rows.
    _draw_table(fig.add_subplot(gs[2]), f"Momentum holdings ({len(mom_rows)})",
                ["Sym", "Qty", "Entry", "Last", "P/L ₹", "Value ₹", "% of account"], mom_rows, "No momentum holdings")
    _draw_table(fig.add_subplot(gs[3]), f"Swing open positions ({len(swing_rows)})",
                ["Sym", "Strat", "Qty", "Entry", "Last", "P/L ₹", "Value ₹", "Stop"], swing_rows, "No swing positions")
    _draw_table(fig.add_subplot(gs[4]), f"Queued for the next session ({len(order_rows)})",
                ["Sleeve", "Side", "Sym", "Detail"], order_rows, "No orders queued",
                col_widths=[0.12, 0.07, 0.15, 0.66])

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=130)
    plt.close(fig)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    if args.out is None:
        d = _table("SELECT max(date) AS d FROM account_equity")
        stamp = str(d["d"].iloc[0])[:10] if not d.empty and d["d"].iloc[0] is not None else "latest"
        chart_dir = Path(os.environ.get("TRADER_CHART_DIR", REPO / "charts"))
        args.out = chart_dir / f"paper_report_{stamp}.png"
    print(build(args.out))


if __name__ == "__main__":
    main()
