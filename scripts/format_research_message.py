#!/usr/bin/env python3
"""Turn reports/research/last_run.txt into the Telegram message for the scheduled research run.

Usage: format_research_message.py SUMMARY_PATH
Reads the 6-line summary written by the scheduled research run and prints a labelled message.
Unknown or missing lines are shown raw, so nothing is hidden. Research only: never trades.
"""
import re
import sys
from pathlib import Path

VERDICT_ICON = {"PASS": "✅", "FORWARD_ONLY": "🟡", "FAIL": "❌", "NO IDEA": "⚪"}


def esc(s: str) -> str:
    """Escape Telegram (legacy) Markdown specials in dynamic text."""
    return re.sub(r"([_*`\[])", r"\\\1", s)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    lines = Path(argv[1]).read_text(encoding="utf-8", errors="replace").splitlines()
    fields: dict[str, str] = {}
    for line in lines:
        if ": " in line:
            k, v = line.split(": ", 1)
            fields[k.strip()] = v.strip()
    if not {"Idea", "Verdict"} <= fields.keys():
        print("🔬 *Research run*")
        print("\n".join(esc(l) for l in lines if l.strip()))
        return 0

    verdict = fields["Verdict"]
    icon = VERDICT_ICON.get(verdict, "🔬")
    out = ["🔬 *Research run*", "", f"{icon} *{esc(verdict)}* · `{esc(fields['Idea'].split(' - ')[0])}`"]
    idea_text = fields["Idea"].split(" - ", 1)[1] if " - " in fields["Idea"] else ""
    if idea_text:
        out.append("_" + esc(idea_text) + "_")
    out.append("")
    if "Deciding gate" in fields:
        out.append("🚧 *Deciding gate*")
        for part in re.split(r";\s*", fields["Deciding gate"]):
            if part.strip():
                out.append("• " + esc(part.strip()))
        out.append("")
    if "Trial count" in fields:
        out.append(f"🧮 Trials counted: {esc(fields['Trial count'])}")
    if "Promotion" in fields:
        out.append(f"🚦 Promotion: {esc(fields['Promotion'])}")
    if "Journal" in fields:
        out.append(f"📓 Journal: {esc(fields['Journal'])}")
    known = {"Idea", "Verdict", "Deciding gate", "Trial count", "Promotion", "Journal"}
    extra = [l for l in lines if l.strip() and l.split(": ", 1)[0].strip() not in known]
    if extra:
        out.append("")
        out.extend(esc(l) for l in extra)
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
