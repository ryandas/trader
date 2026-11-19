#!/usr/bin/env python3
"""Turn the `trader daily` log into the Telegram message for the scheduled paper run.

Usage: format_daily_message.py LOG_PATH
Reads the summary lines that `trader daily` echoes and prints a short, labelled message.
If a line is missing or unparseable, the raw line is shown instead, so nothing is hidden.
Paper only: this only reports the ledger, it never places orders.
"""
import re
import sys
from pathlib import Path


def money(s: str) -> str:
    return "₹" + s.strip()


def esc(s: str) -> str:
    """Escape Telegram (legacy) Markdown specials in dynamic text so the message is not rejected."""
    return re.sub(r"([_*`\[])", r"\\\1", s)


def main(argv: list[str] | None = None) -> int:
    from trader.config import load_config

    top_n = load_config().momentum.top_n
    argv = sys.argv if argv is None else argv
    log = Path(argv[1]).read_text(encoding="utf-8", errors="replace").splitlines()
    date_line = regime = momentum = report = orders_csv = account = None
    candidates, warnings, swing = [], [], None
    for line in log:
        if m := re.match(r"^(\d{4}-\d{2}-\d{2}) \| regime (\w+)$", line):
            date_line, regime = m.group(1), m.group(2)
        elif line.startswith("account |"):
            account = line
        elif line.startswith("momentum sleeve |"):
            momentum = line
        elif line.startswith("swing sleeve |"):
            swing = line
        elif line.startswith("candidate "):
            candidates.append(line)
        elif line.startswith("report: "):
            report = line.split(": ", 1)[1].strip()
        elif line.startswith("orders: "):
            orders_csv = line.split(": ", 1)[1].strip()
        elif line.startswith("WARNING"):
            warnings.append(line)

    out = [f"📈 *Trader paper run*" + (f" — data to {date_line}" if date_line else "")]
    out.append("🧭 Regime: " + (regime or "unknown"))

    if account:
        a = re.match(r"account \| equity ([\d,.-]+) \| cash ([\d,.-]+) \| paid in ([\d,.-]+)$", account)
        out.append("")
        out.append("🏦 *Account* (one shared cash account, paper)")
        if a:
            equity, cash, paid = a.groups()
            out.append(f"• Equity {money(equity)} · cash {money(cash)} · paid in {money(paid)}")
            try:
                gain = float(equity.replace(",", "")) - float(paid.replace(",", ""))
                out.append(f"• P&L so far {'+' if gain >= 0 else '−'}{money(f'{abs(gain):,.0f}')}")
            except ValueError:
                pass
        else:
            out.append(f"• {esc(account)}")

    if momentum:
        m = re.match(
            r"momentum sleeve \| positions ([\d,.-]+) \| (\d+) holdings \| "
            r"(\d+) sells, (\d+) buys queued",
            momentum,
        )
        out.append("")
        out.append("💼 *Momentum sleeve* (paper)")
        if m:
            value, holdings, sells, buys = m.groups()
            out.append(f"• Positions {money(value)}")
            out.append(f"• Holdings {holdings}/{top_n}")
            if int(sells) or int(buys):
                out.append(f"• Next session: 🔴 {sells} sells · 🟢 {buys} buys queued")
            else:
                out.append("• Next session: no orders (holding cash or no change)")
        else:
            out.append(f"• {esc(momentum)}")

    if swing:
        out.append("")
        out.append("🔁 *Swing sleeve*: " + esc(swing.split("|", 1)[1].strip()))

    if candidates:
        out.append("")
        out.append("🧪 *Candidate sleeves*")
        for c in candidates:
            out.append("• " + esc(c.replace("candidate ", "", 1)))

    if warnings:
        out.append("")
        out.extend("⚠️ " + esc(w.replace("WARNING: ", "", 1)) for w in warnings)

    out.append("")
    if report:
        out.append(f"📄 Report: {esc(report)}")
    if orders_csv:
        out.append(f"🧾 Orders file: {esc(orders_csv)}")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
