"""Portfolio-level daily event loop.

Per day d: (1) discretionary exits at the open, (2) stop/target exits, (3) fill orders queued
at the previous close, (4) end-of-day trail/rule/time checks and mark-to-market, (5) generate
signals on today's close, size them under portfolio constraints and queue orders for d+1.
Long-only, cash (delivery) accounting, no leverage.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .accounting import CashBox
from .config import Config
from .costs import apply_slippage, trade_costs
from .data import store
from .data.sources import BENCHMARK
from .fills import check_exit, fill_entry
from .regime import BEAR, NEUTRAL, market_regime, stock_trending
from .risk import can_open, position_size
from .selector import Selector, eligible
from .strategies import Strategy, features
from .universe import membership, rank_matrix


@dataclass
class SymData:
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    sector: str
    sig: dict = field(default_factory=dict)  # strategy key -> dict of arrays


@dataclass
class Position:
    sym: str
    strat: str  # strategy name
    key: str  # strategy name + parameter set
    mkt: int  # market regime at signal time
    sector: str
    qty: int
    entry_price: float
    entry_date: pd.Timestamp
    entry_cost: float
    init_stop: float
    stop: float
    target: float | None
    max_hold: int | None
    last_close: float
    bars_held: int = 0
    exit_pending: str | None = None


@dataclass
class Order:
    sym: str
    strat: str
    key: str
    mkt: int
    entry_type: str
    trigger: float | None
    max_entry: float | None
    stop: float
    target: float | None
    qty: int
    est_entry: float
    max_hold: int | None


@dataclass
class Prepared:
    dates: pd.DatetimeIndex
    data: dict[str, SymData]
    cands: dict[int, list]  # day index -> [(strategy name, key, symbol, score)]
    mkt: np.ndarray  # market regime code per day


@dataclass
class Result:
    trades: pd.DataFrame
    equity: pd.DataFrame
    positions: list = field(default_factory=list)  # open positions after the last day
    pending: list = field(default_factory=list)  # orders queued at the last close for next session


def prepare(
    cfg: Config,
    instruments: pd.DataFrame,
    strategies: list[Strategy],
    filters: bool = True,
) -> Prepared:
    """Compute features and candidate signals once. `filters` enables the top-N relative-strength
    universe and the regime/selector eligibility rules (False = the step-3 baseline)."""
    frames: dict[str, pd.DataFrame] = {}
    for sym, df in store.load_many(list(instruments["symbol"])).items():
        if len(df) >= cfg.universe.min_bars:
            frames[sym] = df
    if not frames:
        raise SystemExit("No candle data found. Run `trader update` first.")
    bench = store.load(BENCHMARK)
    if bench is None:
        raise SystemExit("Benchmark missing. Run `trader update` (without symbols) first.")
    dates = pd.DatetimeIndex(sorted(set().union(*[f.index for f in frames.values()])))
    mkt = (
        market_regime(bench["close"]).reindex(dates).ffill().fillna(NEUTRAL).astype(int).to_numpy()
    )
    sectors = dict(zip(instruments["symbol"], instruments["sector"]))
    syms = list(frames)
    data: dict[str, SymData] = {}
    extra: dict[str, dict] = {}
    for sym in syms:
        f = features(frames[sym], cfg.universe.min_price, cfg.universe.min_median_value_cr)
        f["trending"] = stock_trending(f)
        f["above200"] = (f["close"] > f["sma200"]).fillna(False)
        f = f.reindex(dates)
        sd = SymData(
            f["open"].to_numpy(), f["high"].to_numpy(), f["low"].to_numpy(),
            f["close"].to_numpy(), sectors.get(sym, "?"),
        )
        extra[sym] = {
            "liquid": f["liquid"].fillna(False).to_numpy(dtype=bool),
            "rs": f["rs"].to_numpy(),
            "trending": f["trending"].fillna(False).to_numpy(dtype=bool),
            "above200": f["above200"].fillna(False).to_numpy(dtype=bool),
        }
        for st in strategies:
            s = st.signals(f)  # NaN rows (missing bars) evaluate to False signals
            sd.sig[_key(st)] = {
                "signal": s.signal.to_numpy(dtype=bool), "score": s.score.to_numpy(),
                "trigger": s.trigger.to_numpy(), "max_entry": s.max_entry.to_numpy(),
                "stop": s.stop.to_numpy(), "target": s.target.to_numpy(),
                "trail": s.trail.to_numpy(), "exit_now": s.exit_now.to_numpy(dtype=bool),
            }
        data[sym] = sd

    rank = rank_matrix(
        np.vstack([extra[s]["rs"] for s in syms]).T,
        np.vstack([extra[s]["liquid"] for s in syms]).T,
    )
    top = membership(rank, cfg.universe.top_n)
    loose = membership(rank, cfg.universe.loose_top_n)
    cands: dict[int, list] = {}
    for si, sym in enumerate(syms):
        e = extra[sym]
        for st in strategies:
            a = data[sym].sig[_key(st)]
            ok = a["signal"] & e["liquid"] & np.isfinite(a["score"])
            if filters:
                ok &= (loose if st.loose_universe else top)[:, si]
                ok &= eligible(st.name, mkt, e["trending"], e["above200"], cfg.regime.bear_policy)
            for d in np.nonzero(ok)[0]:
                cands.setdefault(int(d), []).append((st.name, _key(st), sym, float(a["score"][d])))
    return Prepared(dates, data, cands, mkt)


def _key(st: Strategy) -> str:
    return getattr(st, "key", None) or st.name


def run(
    cfg: Config,
    prep: Prepared,
    strategies: dict[str, Strategy],
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    selector: Selector | None = None,
    only: set[str] | None = None,
    emit_last: bool = False,
) -> Result:
    """`strategies` maps key -> instance. `only` restricts trading to those keys.
    `emit_last` also queues orders from the final day's close (for paper/live trading)."""
    dates = prep.dates
    n = len(dates)
    i0 = int(dates.searchsorted(start)) if start is not None else 0
    i1 = int(dates.searchsorted(end, side="right")) if end is not None else n
    cash = CashBox(cfg.capital)
    book = SwingBook(cfg, prep, strategies, cash, selector, only)
    eq_rows: list[tuple] = []

    for d in range(i0, i1):
        book.exits(d)  # 1 + 2
        book.fills(d)  # 3
        invested = book.end_of_day(d)  # 4
        equity = cash.value + invested
        eq_rows.append((dates[d], equity, invested / equity if equity > 0 else 0.0))
        if d == i1 - 1 and not emit_last:
            continue
        book.decide(d, equity)  # 5

    equity_df = pd.DataFrame(eq_rows, columns=["date", "equity", "invested"]).set_index("date")
    return Result(pd.DataFrame(book.trades), equity_df, list(book.positions.values()), book.pending)


class SwingBook:
    """The swing sleeve's positions and queued orders, stepped a session at a time.

    It draws on a `CashBox`: alone (`run`) it owns the box, in the paper ledger it shares the box with the momentum
    sleeve (`ledger.py`). Per session: `exits` (open), `fills` (open), `end_of_day` (returns the positions' value), then
    `decide` with the equity that risk and position caps are measured against (own equity alone, whole account shared)."""

    def __init__(self, cfg: Config, prep: Prepared, strategies: dict[str, Strategy], cash: CashBox,
                 selector: Selector | None = None, only: set[str] | None = None):
        self.cfg, self.prep, self.strategies, self.cash = cfg, prep, strategies, cash
        self.selector = selector or Selector()
        self.only = only
        self.positions: dict[str, Position] = {}
        self.pending: list[Order] = []
        self.trades: list[dict] = []

    def close_pos(self, pos: Position, px: float, d: int, reason: str) -> None:
        cc = self.cfg.costs
        fp = apply_slippage(px, "sell", cc.slippage_bps)
        value = fp * pos.qty
        cost = trade_costs("sell", value, cc)
        self.cash.value += value - cost
        gross = (fp - pos.entry_price) * pos.qty
        costs = pos.entry_cost + cost
        net = gross - costs
        risk = pos.qty * (pos.entry_price - pos.init_stop)
        self.trades.append({
            "symbol": pos.sym, "strategy": pos.strat, "params": pos.key, "mkt": pos.mkt,
            "entry_date": pos.entry_date,
            "exit_date": self.prep.dates[d], "qty": pos.qty, "entry_price": round(pos.entry_price, 2),
            "exit_price": round(fp, 2), "reason": reason, "bars_held": pos.bars_held,
            "risk": round(risk, 2), "gross_pnl": round(gross, 2), "costs": round(costs, 2), "net_pnl": round(net, 2),
            "r_multiple": round(net / risk, 3) if risk > 0 else 0.0,
        })
        del self.positions[pos.sym]

    def exits(self, d: int) -> None:
        """Discretionary exits and stop/target exits at the open."""
        data = self.prep.data
        for sym, pos in list(self.positions.items()):
            sd = data[sym]
            o, h, l = sd.o[d], sd.h[d], sd.l[d]
            if math.isnan(o):
                continue
            if pos.exit_pending:
                self.close_pos(pos, o, d, pos.exit_pending)
                continue
            r = check_exit(pos.stop, pos.target, o, h, l)
            if r:
                self.close_pos(pos, r[0], d, r[1])

    def value_at_open(self, d: int) -> float:
        """Positions valued at today's open (last close when there is no bar): no lookahead."""
        tot = 0.0
        for sym, pos in self.positions.items():
            o = self.prep.data[sym].o[d]
            tot += pos.qty * (pos.last_close if math.isnan(o) else o)
        return tot

    def fills(self, d: int, min_fraction: float = 0.0, room: float = math.inf) -> None:
        """Fill the orders queued at the previous close. A buy is cut to the cash available and to `room` (the shared
        account's sleeve cap); if the cut is below `min_fraction` of the ordered quantity it is skipped (shared account
        only: a lone sleeve passes 0 and is never limited)."""
        data, cc = self.prep.data, self.cfg.costs
        for od in self.pending:
            sd = data[od.sym]
            o, h, l = sd.o[d], sd.h[d], sd.l[d]
            if math.isnan(o) or od.sym in self.positions:
                continue
            p = fill_entry(od.entry_type, od.trigger, od.max_entry, o, h, l)
            if p is None or p <= od.stop:
                continue
            fp = apply_slippage(p, "buy", cc.slippage_bps)
            qty = min(od.qty, math.floor(self.cash.value / (fp * 1.01)))
            if room < math.inf:
                qty = min(qty, math.floor(room / fp))
            if qty < 1 or (min_fraction and qty < min_fraction * od.qty):
                continue
            value = fp * qty
            cost = trade_costs("buy", value, cc)
            self.cash.value -= value + cost
            room -= value
            pos = Position(
                od.sym, od.strat, od.key, od.mkt, sd.sector, qty, fp, self.prep.dates[d], cost, od.stop, od.stop,
                od.target, od.max_hold, last_close=p,
            )
            self.positions[od.sym] = pos
            r = check_exit(pos.stop, pos.target, p, h, l)  # same-session stop/target
            if r:
                self.close_pos(pos, r[0], d, r[1])
        self.pending = []

    def end_of_day(self, d: int) -> float:
        """Trail/rule/time checks and mark to market; returns the positions' value at the close."""
        data = self.prep.data
        invested = 0.0
        for sym, pos in self.positions.items():
            sd = data[sym]
            c = sd.c[d]
            if not math.isnan(c):
                pos.last_close = c
                pos.bars_held += 1
                a = sd.sig[pos.key]
                tr = a["trail"][d]
                if not math.isnan(tr):
                    pos.stop = max(pos.stop, tr)
                if a["exit_now"][d]:
                    pos.exit_pending = "rule"
                elif pos.max_hold and pos.bars_held >= pos.max_hold:
                    pos.exit_pending = "time"
            invested += pos.qty * pos.last_close
        return invested

    def decide(self, d: int, equity: float) -> None:
        """Queue orders for the next session from today's close. `equity` sizes risk and position caps."""
        cfg, data, mkt = self.cfg, self.prep.data, self.prep.mkt
        positions, pending, selector = self.positions, self.pending, self.selector
        cash = self.cash.value
        heat = sum(max(p.last_close - p.stop, 0) * p.qty for p in positions.values())
        sector_n: dict[str, int] = {}
        for p in positions.values():
            sector_n[p.sector] = sector_n.get(p.sector, 0) + 1
        committed, seen = 0.0, set(positions)
        regime = int(mkt[d])
        risk_pct = cfg.risk_per_trade * (cfg.regime.bear_size_mult if regime == BEAR else 1.0)
        day = [
            c for c in self.prep.cands.get(d, [])
            if (self.only is None or c[1] in self.only) and selector.allowed(c[0], regime)
        ]
        day.sort(key=lambda c: (-selector.weight(c[0], regime), -c[3], c[2]))
        for sname, key, sym, _ in day:
            if sym in seen:
                continue
            if len(positions) + len(pending) >= cfg.risk.max_positions:
                break
            st, sd = self.strategies[key], data[sym]
            a = sd.sig[key]
            stop = a["stop"][d]
            est = a["trigger"][d] if st.entry_type == "stop" else sd.c[d]
            if math.isnan(stop) or math.isnan(est):
                continue
            full = position_size(
                equity, risk_pct, est, stop, cfg.risk.max_position_pct, math.inf
            )
            qty = position_size(
                equity, risk_pct, est, stop, cfg.risk.max_position_pct, cash - committed
            )
            if qty < 1 or qty < cfg.min_size_fraction * full:
                continue  # cash-starved: skip rather than take a token-sized position
            if not can_open(
                len(positions) + len(pending), sector_n.get(sd.sector, 0), heat,
                qty * (est - stop), equity, cfg.risk,
            ):
                continue
            tgt, mx = a["target"][d], a["max_entry"][d]
            pending.append(Order(
                sym, sname, key, regime, st.entry_type,
                None if math.isnan(a["trigger"][d]) else float(a["trigger"][d]),
                None if math.isnan(mx) else float(mx), float(stop),
                None if math.isnan(tgt) else float(tgt), qty, float(est), st.max_hold,
            ))
            seen.add(sym)
            sector_n[sd.sector] = sector_n.get(sd.sector, 0) + 1
            heat += qty * (est - stop)
            committed += qty * est


def load_benchmark(cfg: Config) -> pd.Series | None:
    df = store.load(BENCHMARK)
    return df["close"] if df is not None else None
