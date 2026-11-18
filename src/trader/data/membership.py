"""Point-in-time NIFTY 500 membership, to remove the "today's constituents" survivorship bias.

Source: dated copies of NSE's own `ind_nifty500list.csv` kept by the Internet Archive (Wayback Machine), saved under
`data/membership/snapshots/<YYYYMMDD>.csv`. A stock is identified by ISIN (it survives renames); its key in the candle store is the
most recent symbol seen for that ISIN. Membership on day t is the NEWEST snapshot dated on or before t: only what was
publicly known by then, never a later list, so the universe cannot contain a stock "because it rose". Before the first snapshot
the first snapshot is used (that part is NOT point-in-time, so evaluations must start after it).

Known limits (they are reported, not hidden): snapshots are months apart, so a stock that joined and left inside one gap never
appears, and a stock that left shortly after a snapshot stays a member until the next one (the safe direction: it keeps losers
in). Stocks that were delisted or merged away mostly have no Yahoo price history, so they cannot be traded in a backtest.
`unavailable.csv` lists every past member whose prices could not be fetched.
"""
from __future__ import annotations

from pathlib import Path

import re

import numpy as np
import pandas as pd
from sqlalchemy import text

from .. import db
from . import store


SNAP_COLS = ["Company Name", "Industry", "Symbol", "Series", "ISIN Code"]


def load_snapshots() -> dict[pd.Timestamp, pd.DataFrame]:
    """Dated NIFTY 500 lists (each the truth on its date), columns as in NSE's ind_nifty500list.csv."""
    df = db.qdf("SELECT snap_date, company_name, industry, symbol, series, isin FROM membership_snapshots "
                "ORDER BY snap_date, symbol")
    if df.empty:
        raise SystemExit("No membership snapshots in the database.")
    out = {}
    for d, g in df.groupby("snap_date", sort=True):
        out[pd.Timestamp(d)] = g.drop(columns="snap_date").set_axis(SNAP_COLS, axis=1).reset_index(drop=True)
    return out


def save_snapshot(day, d: pd.DataFrame) -> int:
    """Store one dated list (columns as NSE's CSV), replacing any earlier copy of the same day."""
    d = d.rename(columns=lambda c: c.strip())
    d = d.astype(object).where(d.notna(), None)
    day = pd.Timestamp(day).date()
    recs = [{"d": day, "n": r[SNAP_COLS[0]], "i": r[SNAP_COLS[1]], "s": r[SNAP_COLS[2]], "e": r[SNAP_COLS[3]],
             "n2": r[SNAP_COLS[4]]} for _, r in d.iterrows()]
    with db.engine().begin() as c:
        c.execute(text("DELETE FROM membership_snapshots WHERE snap_date = :d"), {"d": day})
        c.execute(text("INSERT INTO membership_snapshots (snap_date, company_name, industry, symbol, series, isin) "
                       "VALUES (:d, :n, :i, :s, :e, :n2)"), recs)
    return len(recs)


def companies(snaps: dict[pd.Timestamp, pd.DataFrame]) -> tuple[dict[str, str], pd.DataFrame]:
    """Company identity across the snapshots. A split, bonus or consolidation gives a company a NEW ISIN, a rename gives it a NEW
    symbol, so neither alone identifies it: symbols and ISINs that ever appear on the same row are linked (union-find), and the
    company's key is its most recent symbol (which is also its key in the candle store).
    Returns ({any symbol or ISIN seen: key}, table with key/name/first_seen/last_seen, one row per company)."""
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    last: dict[str, tuple] = {}
    for t, d in snaps.items():  # ascending
        for r in d.itertuples(index=False):
            name, sym, isin = r[0], r[2], r[4]
            parent[find(sym)] = find(isin)
            last[sym] = (t, name)
    rows: dict[str, dict] = {}
    for t, d in snaps.items():
        for r in d.itertuples(index=False):
            root = find(r[2])
            e = rows.setdefault(root, {"first_seen": t})
            e.update(symbol=r[2], name=r[0], last_seen=t)
    keyof = {x: rows[find(x)]["symbol"] for x in list(parent) if find(x) in rows}
    return keyof, pd.DataFrame(rows.values())


def isin_symbols(snaps: dict[pd.Timestamp, pd.DataFrame]) -> pd.DataFrame:
    """One row per company ever in the index: `symbol` (its key / latest symbol), name, first_seen, last_seen."""
    return companies(snaps)[1]


def load_events() -> pd.DataFrame:
    """Dated NIFTY 500 inclusions (+1) and exclusions (-1) from press releases and manual fixes, effective on `eff_date`."""
    d = db.qdf("SELECT eff_date, symbol, action FROM membership_events ORDER BY eff_date, symbol")
    if d.empty:
        return pd.DataFrame(columns=["eff_date", "symbol", "action"])
    d["eff_date"] = pd.to_datetime(d["eff_date"])
    return d.drop_duplicates().reset_index(drop=True)


def save_events(df: pd.DataFrame, manual: bool = False) -> int:
    """Replace the parsed (or, with manual=True, the hand-checked) events. Columns: eff_date, symbol, action[, release, note]."""
    recs = [{"d": pd.Timestamp(r.eff_date).date(), "s": r.symbol, "a": int(r.action),
             "r": getattr(r, "release", None) if not manual else None,
             "n": getattr(r, "note", None) if manual else None, "m": manual} for r in df.itertuples()]
    with db.engine().begin() as c:
        c.execute(text("DELETE FROM membership_events WHERE manual = :m"), {"m": manual})
        if recs:
            c.execute(text("INSERT INTO membership_events (eff_date, symbol, action, release, note, manual) "
                           "VALUES (:d, :s, :a, :r, :n, :m)"), recs)
    return len(recs)


def timeline(use_events: bool = True) -> tuple[list[tuple[pd.Timestamp, frozenset]], list[dict]]:
    """Membership change points [(date, set of keys)] and a per-gap report.

    Each snapshot is the truth on its date. Between two snapshots the announced press-release changes (effective date strictly
    after the earlier snapshot and before the later one) are applied on their effective dates. Whatever the events do not
    explain is reset at the later snapshot (late for joiners, late for leavers: the safe direction). A key is the ISIN, or
    `sym:SYMBOL` for a company that joined and left between snapshots and never appears in one."""
    snaps = load_snapshots()
    keyof, _ = companies(snaps)
    keyed = lambda sym: keyof.get(sym, sym)  # noqa: E731  (an event symbol never seen in a snapshot is its own company)
    truth = [(t, frozenset(keyof[x] for x in d.iloc[:, 2])) for t, d in snaps.items()]
    ev = load_events() if use_events else pd.DataFrame(columns=["eff_date", "symbol", "action"])
    points, report = [], []
    for k, (a, S) in enumerate(truth):
        points.append((a, S))
        if k + 1 == len(truth):
            break
        b, T = truth[k + 1]
        state, applied = set(S), 0
        win = ev[(ev["eff_date"] > a) & (ev["eff_date"] < b)].sort_values("eff_date", kind="stable")
        for eff, grp in win.groupby("eff_date"):
            for r in grp.itertuples():
                (state.add if r.action > 0 else state.discard)(keyed(r.symbol))
                applied += 1
            points.append((eff, frozenset(state)))
        report.append({"from": a.date(), "to": b.date(), "events": applied, "unexplained_in": len(T - state),
                       "unexplained_out": len(state - T), "months": round((b - a).days / 30.4, 1)})
    return points, report


def all_symbols() -> list[str]:
    """Candle-store keys for every company that was ever a member: latest symbol per ISIN, plus event-only symbols."""
    snaps = load_snapshots()
    keyof, table = companies(snaps)
    ev = load_events()
    return list(table["symbol"]) + sorted({s for s in ev["symbol"] if s not in keyof})


def member_panel(dates: pd.DatetimeIndex, syms: list[str]) -> np.ndarray:
    """(dates x syms) True where the symbol was a NIFTY 500 member on that day (see `timeline`). Before the first snapshot the
    first snapshot is used (not point-in-time)."""
    col = {s: i for i, s in enumerate(syms)}
    points, _ = timeline()
    masks = []
    for _, st in points:
        m = np.zeros(len(syms), dtype=bool)
        for k in st:
            i = col.get(k)
            if i is not None:
                m[i] = True
        masks.append(m)
    pd_dates = np.asarray([t for t, _ in points], dtype="datetime64[ns]")
    which = np.clip(np.searchsorted(pd_dates, dates.to_numpy(), side="right") - 1, 0, None)
    return np.vstack(masks)[which]


def first_snapshot() -> pd.Timestamp:
    return next(iter(load_snapshots()))


def fetch_missing(cfg, source=None, years: int | None = None) -> pd.DataFrame:
    """Download daily candles for every past member that is not in the candle store. Writes unavailable.csv."""
    from .sources import YFinanceSource

    source = source or YFinanceSource()
    snaps = load_snapshots()
    info = isin_symbols(snaps)
    log = []
    todo = [(r.symbol, r.name, r.last_seen.date()) for r in info.itertuples()]
    todo += [(sym, "", None) for sym in all_symbols() if sym not in set(info["symbol"])]
    for sym, name, seen in todo:
        if store.load(sym) is not None or sym.startswith("DUMMY"):
            continue
        try:
            n = store.update_symbol(source, sym, 0, years or cfg.history_years)
            log.append({"symbol": sym, "name": name, "rows": n, "last_seen": seen})
        except Exception as e:  # a bad ticker must not stop the run
            log.append({"symbol": sym, "name": name, "rows": 0, "last_seen": seen, "error": str(e)[:80]})
        r = type("R", (), {"symbol": sym})
        print(f"{r.symbol}: {log[-1]['rows']}", flush=True)
    out = pd.DataFrame(log)
    if len(out):
        save_unavailable(out[out["rows"] == 0])
    return out


def save_unavailable(df: pd.DataFrame) -> None:
    """Past members with no price history at the source (replaces the list)."""
    recs = [{"s": r.symbol, "n": r.name, "r": int(r.rows), "l": None if r.last_seen is None else str(r.last_seen)}
            for r in df.itertuples()]
    with db.engine().begin() as c:
        c.execute(text("DELETE FROM membership_unavailable"))
        if recs:
            c.execute(text("INSERT INTO membership_unavailable (symbol, name, rows, last_seen) VALUES (:s, :n, :r, :l) "
                           "ON CONFLICT (symbol) DO NOTHING"), recs)


SNAPSHOT_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"


def save_current_snapshot(day: pd.Timestamp | None = None) -> int:
    """Save today's official NIFTY 500 list as a dated snapshot (run it monthly so future tests stay point-in-time)."""
    import io

    import requests

    r = requests.get(SNAPSHOT_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    d = pd.read_csv(io.StringIO(r.text))
    if len(d) < 400 or "ISIN Code" not in [c.strip() for c in d.columns]:
        raise SystemExit("Unexpected NIFTY 500 list format; snapshot not saved.")
    day = day or pd.Timestamp.today().normalize()
    return save_snapshot(day, d)


# ---------------------------------------------------------------- NSE press releases
_MONTHS = {m: i for i, m in enumerate("January February March April May June July August September October November December".split(), 1)}
_EFF = re.compile(r"effective\s+from\s+([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", re.I)
_HDR = re.compile(r"^\s*(?:\d+\)|[a-zA-Z]\))\s+(.*\S)\s*$")
_ROW = re.compile(r"^\s*\d+\s+.+?\s{2,}([A-Z0-9&\-\.]+)\s*$")


def parse_release(text: str) -> tuple[pd.Timestamp | None, list[tuple[str, int]]]:
    """Effective date and the NIFTY 500 section's (symbol, +1 included / -1 excluded) rows of one NSE Indices press release.
    Only a section headed exactly "NIFTY 500" counts (not Multicap, Midcap, strategy indices...). Releases whose NIFTY 500 change
    has another layout (spin-offs, revisions, "revoked" tables) yield nothing and are handled in manual_events.csv."""
    m = _EFF.search(text)
    eff = pd.Timestamp(int(m.group(3)), _MONTHS[m.group(1).title()], int(m.group(2))) if m and m.group(1).title() in _MONTHS else None
    out, mode, insec = [], None, False
    for ln in text.splitlines():
        h = _HDR.match(ln)
        if h and not _ROW.match(ln):
            insec, mode = re.fullmatch(r"nifty\s*500\*{0,3}", h.group(1).strip(), re.I) is not None, None
            continue
        if not insec:
            continue
        if re.search(r"being excluded", ln, re.I):
            mode = -1
        elif re.search(r"being included", ln, re.I):
            mode = 1
        elif mode is not None and (r := _ROW.match(ln)):
            out.append((r.group(1), mode))
    return eff, out


def build_events(text_dir: Path) -> pd.DataFrame:
    """Parse every `<YYYYMMDD>.txt` (pdftotext -layout output of a press release dated that day) in `text_dir`."""
    rows = []
    for f in sorted(text_dir.glob("*.txt")):
        eff, ev = parse_release(f.read_text(errors="ignore"))
        rows += [{"eff_date": eff, "symbol": sym, "action": a, "release": f.stem} for sym, a in ev if eff is not None]
    return pd.DataFrame(rows, columns=["eff_date", "symbol", "action", "release"])
