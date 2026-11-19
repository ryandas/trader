"""Cross-sectional momentum rotation (long-only, equal weight, monthly).

On the last trading day of each month: rank liquid NIFTY 500 stocks above their own 200 SMA by
trailing return (`lookback` days, skipping the latest `skip`), hold the top `top_n` equal-weighted.
Holdings are kept while rank <= top_n + buffer to limit turnover. Orders fill at the NEXT open
with the same costs and slippage as the other strategies. If the market is bearish at a
rebalance the book goes to cash; with `bear_exit` it also sells the next open whenever the
market turns bearish mid-month (re-entry only at a later rebalance).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import sessions
from . import walkforward as wf
from .accounting import CashBox, Nav
from .config import Config
from .costs import apply_slippage, trade_costs
from .data import store
from .data.sources import BENCHMARK
from .metrics import summarize
from .regime import BEAR, NEUTRAL, market_regime


REBALANCE_CODES = ("M", "W", "Q", "S")


@dataclass(frozen=True)
class MomParams:
    lookback: int = 126
    skip: int = 21
    top_n: int = 20
    buffer: int = 10
    bear_exit: bool = True
    random_seed: int | None = None  # CONTROL ONLY: fixed random score per stock instead of momentum
    ranker: str = "momentum"  # research candidate slug (trader.research.candidates) replacing the momentum score
    ranker_params: tuple = ()  # sorted (name, value) pairs passed to the candidate's score()
    rebalance: str = "M"  # "M" monthly, "W" weekly, "Q" quarterly (Mar/Jun/Sep/Dec), "S" semi-annual (Jun/Dec); last session of the period

    def __post_init__(self):  # JSON round-trips tuples as lists; keep the field a hashable tuple of pairs
        if self.rebalance not in REBALANCE_CODES:
            raise ValueError(f"rebalance must be one of {REBALANCE_CODES}, got {self.rebalance!r}")
        object.__setattr__(self, "ranker_params", tuple(tuple(kv) for kv in self.ranker_params))

    def label(self) -> str:
        base = (f"lb{self.lookback}-skip{self.skip}-top{self.top_n}-buf{self.buffer}"
                f"{'-bearexit' if self.bear_exit else ''}")
        if self.ranker != "momentum":
            base = (f"{self.ranker}[{','.join(f'{k}={v}' for k, v in self.ranker_params)}]"
                    f"-top{self.top_n}-buf{self.buffer}{'-bearexit' if self.bear_exit else ''}")
        if self.rebalance != "M":
            base += f"-reb{self.rebalance}"
        return base + (f"-RANDOM{self.random_seed}" if self.random_seed is not None else "")


# Small grid for walk-forward; index 0 is the default.
GRID = [
    MomParams(),
    MomParams(lookback=252),
    MomParams(top_n=30),
    MomParams(bear_exit=False),
]


@dataclass
class MomPrep:
    dates: pd.DatetimeIndex
    syms: list[str]
    o: np.ndarray  # open, NaN where no bar
    c: np.ndarray  # close, forward-filled (for marking and ranking)
    liquid: np.ndarray
    above200: np.ndarray
    mkt: np.ndarray
    rebal: np.ndarray  # True on the last trading day of a month
    close_df: pd.DataFrame
    _scores: dict = field(default_factory=dict)
    rebal_w: np.ndarray | None = None  # True on the last trading day of a week
    _fund: dict = field(default_factory=dict)
    bench_close: np.ndarray | None = None  # NIFTY 500 close on each date (forward-filled), for market-relative scores
    sectors: list | None = None  # sector label per symbol (same order as syms)
    rebal_q: np.ndarray | None = None  # True on the last trading day of a quarter
    rebal_s: np.ndarray | None = None  # True on the last trading day of a half-year (Jun / Dec)

    def rebal_mask(self, code: str) -> np.ndarray:
        m = {"M": self.rebal, "W": self.rebal_w, "Q": self.rebal_q, "S": self.rebal_s}[code]
        if m is None:
            raise ValueError(f"this prep has no {code!r} rebalance mask")
        return m

    def score(self, lookback: int, skip: int) -> np.ndarray:
        key = (lookback, skip)
        if key not in self._scores:
            self._scores[key] = (self.close_df.shift(skip) / self.close_df.shift(lookback) - 1).to_numpy()
        return self._scores[key]

    def ranker_score(self, p: "MomParams") -> np.ndarray:
        """Score matrix (dates x syms) from a research candidate; cached per (ranker, params)."""
        key = ("ranker", p.ranker, p.ranker_params)
        if key not in self._scores:
            from .research import registry  # local import: research depends on this module

            self._scores[key] = np.asarray(registry.load(p.ranker).score(self, **dict(p.ranker_params)), dtype=float)
        return self._scores[key]

    def fund_panel(self, field_name: str) -> np.ndarray:
        """(dates x syms) values of one fundamentals field as KNOWN on each date: the newest snapshot
        dated on or before that date (NaN before the first snapshot). Never uses a later snapshot."""
        if field_name not in self._fund:
            from .data import fundamentals

            self._fund[field_name] = fundamentals.panel(self.dates, self.syms, field_name)
        return self._fund[field_name]


@dataclass
class MomResult:
    trades: pd.DataFrame
    equity: pd.DataFrame
    positions: dict
    pending_sells: dict
    pending_buys: list
    turnover_per_year: float


def truncate(prep: MomPrep, t: int) -> MomPrep:
    """The prep as it would look with history ending at row `t` (used by the lookahead guard)."""
    k = t + 1
    return MomPrep(
        prep.dates[:k], prep.syms, prep.o[:k], prep.c[:k], prep.liquid[:k], prep.above200[:k], prep.mkt[:k],
        prep.rebal[:k], prep.close_df.iloc[:k],
        rebal_w=None if prep.rebal_w is None else prep.rebal_w[:k],
        bench_close=None if prep.bench_close is None else prep.bench_close[:k], sectors=prep.sectors,
        rebal_q=None if prep.rebal_q is None else prep.rebal_q[:k], rebal_s=None if prep.rebal_s is None else prep.rebal_s[:k],
    )


def month_end_mask(dates: pd.DatetimeIndex) -> np.ndarray:
    """True on the last trading day of each month (final bar: is the next NSE session, holidays skipped, in a new month?)."""
    month = dates.to_period("M")
    m = np.zeros(len(dates), dtype=bool)
    m[:-1] = month[:-1] != month[1:]
    m[-1] = sessions.next_session(dates[-1]).to_period("M") != month[-1]
    return m


def prepare(cfg: Config, instruments: pd.DataFrame, liquid_top: int | None = None, pit: bool = False) -> MomPrep:
    """`liquid_top` keeps only the N most liquid names (by 20-day median traded value) on each day,
    a partial guard against survivorship bias: large caps were mostly large before they were indexed.

    `pit=True` (point-in-time universe): every past NIFTY 500 member with stored prices is loaded, and on each day only the
    stocks that were in the index per the newest snapshot dated on or before that day can be ranked or bought
    (see data/membership.py). Default off, so the paper ledger and every existing result are unchanged."""
    from .data import membership

    symbols = list(instruments["symbol"])
    if pit:
        symbols += [s for s in membership.all_symbols() if s not in set(symbols)]
    frames = {sym: df for sym, df in store.load_many(symbols).items() if len(df) >= cfg.universe.min_bars}
    bench = store.load(BENCHMARK)
    if not frames or bench is None:
        raise SystemExit("No candle data or benchmark. Run `trader update` first.")
    dates = pd.DatetimeIndex(sorted(set().union(*[f.index for f in frames.values()])))
    syms = list(frames)
    raw = lambda col: pd.DataFrame({s: frames[s][col] for s in syms}).reindex(dates)  # noqa: E731
    close = raw("close").ffill()  # a suspended day carries the last close
    value_cr = (close * raw("volume").fillna(0)).rolling(20, min_periods=20).median() / 1e7
    liquid = ((value_cr >= cfg.universe.min_median_value_cr) & (close >= cfg.universe.min_price))
    if pit:
        liquid = liquid & pd.DataFrame(membership.member_panel(dates, syms), index=dates, columns=syms)
    if liquid_top:
        vr = value_cr.where(liquid).rank(axis=1, ascending=False, method="first")
        liquid = liquid & (vr <= liquid_top)
    above200 = close > close.rolling(200, min_periods=200).mean()
    mkt = market_regime(bench["close"]).reindex(dates).ffill().fillna(NEUTRAL).astype(int).to_numpy()
    month = dates.to_period("M")
    rebal = month_end_mask(dates)
    nxt = sessions.next_session(dates[-1])
    week = dates.to_period("W")
    rebal_w = np.zeros(len(dates), dtype=bool)
    rebal_w[:-1] = week[:-1] != week[1:]
    rebal_w[-1] = nxt.to_period("W") != week[-1]

    def period_end(key) -> np.ndarray:  # last session before the (year, bucket) key changes
        k = np.asarray([key(d) for d in dates] + [key(nxt)], dtype=np.int64)  # scalar keys: 1-D result
        return k[:-1] != k[1:]

    rebal_q = period_end(lambda d: d.year * 10 + (d.month - 1) // 3)
    rebal_s = period_end(lambda d: d.year * 10 + (d.month - 1) // 6)
    return MomPrep(
        dates, syms, raw("open").to_numpy(), close.to_numpy(),
        liquid.to_numpy(dtype=bool), above200.to_numpy(dtype=bool), mkt, rebal, close,
        rebal_w=rebal_w, rebal_q=rebal_q, rebal_s=rebal_s,
        bench_close=bench["close"].reindex(dates).ffill().to_numpy(),
        sectors=(instruments.set_index("symbol")["sector"].reindex(syms).fillna("Unknown").tolist() if "sector" in instruments else None),
    )


class MomBook:
    """One momentum sleeve's positions and queued orders, stepped a session at a time.

    The book draws on a `CashBox`. Alone (`run`) it owns the box; in the paper ledger the same box is shared with the
    swing sleeve (`ledger.py`). Per session the caller runs `sell_at_open`, `buy_at_open`, then marks and calls `decide`
    with the equity the targets should be a share of (this sleeve's own value alone, or the whole account's)."""

    def __init__(self, cfg: Config, prep: MomPrep, p: MomParams, cash: CashBox):
        self.cfg, self.prep, self.p, self.cash = cfg, prep, p, cash
        self.rebal = prep.rebal_mask(p.rebalance)
        if p.random_seed is None and p.ranker != "momentum":
            self.score = prep.ranker_score(p)
        elif p.random_seed is None:
            self.score = prep.score(p.lookback, p.skip)
        else:  # control: same rules, costs and universe, but a persistent random pick (no momentum info)
            rnd = np.random.default_rng(p.random_seed).random(prep.c.shape[1])
            self.score = np.broadcast_to(rnd, prep.c.shape)
        self.pos: dict[int, dict] = {}  # symbol index -> position
        self.sells: dict[int, str] = {}  # symbol index -> reason, executed at next open
        self.buys: list[tuple[int, float]] = []  # (symbol index, target value)
        self.trades: list[dict] = []
        self.traded_value = 0.0

    def sell_at_open(self, d: int) -> None:
        prep, o, cc = self.prep, self.prep.o, self.cfg.costs
        for si in list(self.sells):
            if si not in self.pos or math.isnan(o[d, si]):
                continue  # no bar today (suspended): try again next session
            q = self.pos.pop(si)
            fp = apply_slippage(o[d, si], "sell", cc.slippage_bps)
            val = fp * q["qty"]
            cost = trade_costs("sell", val, cc)
            self.cash.value += val - cost
            self.traded_value += val
            gross = (fp - q["px"]) * q["qty"]
            net = gross - q["cost"] - cost
            self.trades.append({
                "symbol": prep.syms[si], "entry_date": prep.dates[q["d"]], "exit_date": prep.dates[d],
                "qty": q["qty"], "entry_price": round(q["px"], 2), "exit_price": round(fp, 2),
                "reason": self.sells[si], "bars_held": d - q["d"], "gross_pnl": round(gross, 2),
                "costs": round(q["cost"] + cost, 2), "net_pnl": round(net, 2),
                "ret_pct": round(100 * net / (q["px"] * q["qty"]), 2),
            })
            del self.sells[si]

    def buy_at_open(self, d: int, min_fraction: float = 0.0, room: float = math.inf) -> None:
        """Fill the queued buys. A buy is cut to the cash available and to `room` (how much more position value the
        shared account's sleeve cap lets this sleeve add); if the cut is below `min_fraction` of the intended quantity it
        is skipped (shared account only; a lone sleeve passes 0 and is never limited in practice)."""
        o, cc = self.prep.o, self.cfg.costs
        for si, tv in self.buys:
            if si in self.pos or math.isnan(o[d, si]):
                continue
            fp = apply_slippage(o[d, si], "buy", cc.slippage_bps)
            qty = math.floor(min(tv, self.cash.value, room) / (fp * 1.004))  # headroom for charges
            if qty < 1 or (min_fraction and qty < min_fraction * math.floor(tv / (fp * 1.004))):
                continue
            val = fp * qty
            cost = trade_costs("buy", val, cc)
            self.cash.value -= val + cost
            self.traded_value += val
            room -= val
            self.pos[si] = {"qty": qty, "px": fp, "cost": cost, "d": d}
        self.buys = []

    def value_at_open(self, d: int) -> float:
        """Positions valued at today's open (last close, then entry price, when there is no bar): no lookahead."""
        c, o = self.prep.c, self.prep.o
        tot = 0.0
        for si, q in self.pos.items():
            px = o[d, si]
            if math.isnan(px):
                px = c[d - 1, si] if d > 0 else math.nan
            tot += q["qty"] * (q["px"] if math.isnan(px) else px)
        return tot

    def invested(self, d: int) -> float:
        return sum(q["qty"] * self.prep.c[d, si] for si, q in self.pos.items())

    def decide(self, d: int, equity: float, force_rebalance: bool = False) -> None:
        """Queue orders for the next open from today's close. `equity` is what each target is a share of."""
        prep, p = self.prep, self.p
        bear = prep.mkt[d] == BEAR
        reb_d = bool(self.rebal[d]) or force_rebalance
        if bear and (p.bear_exit or reb_d):
            self.sells.update({si: "bear" for si in self.pos})
            return
        if not reb_d:
            return
        elig = prep.liquid[d] & prep.above200[d] & np.isfinite(self.score[d])
        idx = np.nonzero(elig)[0]
        ranked = idx[np.argsort(-self.score[d, idx], kind="stable")]
        rank = {int(si): r for r, si in enumerate(ranked)}
        keep = {si for si in self.pos if rank.get(si, 10**9) < p.top_n + p.buffer}
        for si in self.pos:
            if si not in keep:
                self.sells[si] = "rebalance"
        free = p.top_n - len(keep)
        target = equity / p.top_n
        for si in ranked:
            if free <= 0:
                break
            if int(si) not in keep:
                self.buys.append((int(si), target))
                free -= 1


def run(
    cfg: Config,
    prep: MomPrep,
    p: MomParams,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    emit_last: bool = False,
    warm_start: bool = False,
    contribution: float = 0.0,
) -> MomResult:
    """`warm_start`: treat the first session of the window as a rebalance day (orders fill at the next open), so a slow
    cadence starts invested like a continuously running account instead of idling in cash until its next signal.
    Used by the research harness for walk-forward windows; the paper ledger replays leave it off.

    `contribution`: INR added to cash at the close of the last session of every month (the same `prep.rebal` days,
    whatever the rebalance cadence), so it is in the book when that day's rebalance sizes positions and fills at the next
    open. The result's `equity` column is then a deposit-adjusted (time-weighted) curve starting at `cfg.capital`, so
    returns, drawdown and Sharpe never count a deposit as profit; `value` is the real money and `deposited` the running
    total paid in. With contribution 0 all three are identical to the old single `equity` curve."""
    dates = prep.dates
    n = len(dates)
    i0 = int(dates.searchsorted(start)) if start is not None else 0
    i1 = int(dates.searchsorted(end, side="right")) if end is not None else n
    cash = CashBox(cfg.capital)
    book = MomBook(cfg, prep, p, cash)
    navs = Nav(cfg.capital, contribution)
    eq_rows: list[tuple] = []

    for d in range(i0, i1):
        # 1. execute orders queued at the previous close: sells first, then buys
        book.sell_at_open(d)
        book.buy_at_open(d)
        # 2. mark to market (and deposit on the last session of each month: `prep.rebal`)
        invested = book.invested(d)
        nav, equity, deposited = navs.mark(cash, invested, bool(prep.rebal[d]))
        eq_rows.append((dates[d], nav, invested / equity if equity > 0 else 0.0, equity, deposited))
        # 3. decide for the next open
        if d == i1 - 1 and not emit_last:
            continue
        book.decide(d, equity, force_rebalance=warm_start and d == i0)

    equity_df = pd.DataFrame(eq_rows, columns=["date", "equity", "invested", "value", "deposited"]).set_index("date")
    years = max((equity_df.index[-1] - equity_df.index[0]).days / 365.25, 1e-9) if len(equity_df) else 1
    avg_eq = equity_df["value"].mean() if len(equity_df) else 1.0
    return MomResult(
        pd.DataFrame(book.trades), equity_df, book.pos, book.sells, book.buys, book.traded_value / avg_eq / years
    )


def deposit_schedule(prep: MomPrep, start, end, capital: float, contribution: float) -> pd.Series:
    """The money paid in over a window as `run` models it: `capital` on the first session, `contribution` on each
    month-end session. Used to give the index and the basket the same deposits on the same dates."""
    i0 = int(prep.dates.searchsorted(start)) if start is not None else 0
    i1 = int(prep.dates.searchsorted(end, side="right")) if end is not None else len(prep.dates)
    s = pd.Series(np.where(prep.rebal[i0:i1], float(contribution), 0.0), index=prep.dates[i0:i1])
    if len(s):
        s.iloc[0] += capital
    return s


def matched_value(prices: pd.Series, deposits: pd.Series) -> float:
    """Final value of buying `prices` (an index level series, costless) with the given deposits on their dates."""
    px = prices.reindex(deposits.index).ffill()
    units = (deposits / px).where(deposits > 0, 0.0).sum()
    return float(units * prices.reindex(deposits.index).ffill().iloc[-1])


# ---------------------------------------------------------------- walk-forward
def _sharpe(eq: pd.DataFrame) -> float:
    r = eq["equity"].pct_change().dropna()
    return float(r.mean() / r.std() * np.sqrt(252)) if len(r) > 20 and r.std() > 0 else -np.inf


def walk_forward(cfg: Config, prep: MomPrep, grid: list[MomParams] | None = None, warm_start: bool = False,
                 contribution: float = 0.0) -> dict:
    """Pick params by in-sample Sharpe, trade the next unseen year. Also runs every grid point
    on every OOS window (informational only, never used for selection) to show robustness.
    With `contribution` every window is a FRESH START: `cfg.capital` plus the monthly deposit, so each OOS year looks like
    the first year of a new small account (its equity is time-weighted, see `run`)."""
    grid = GRID if grid is None else grid
    bench = store.load(BENCHMARK)["close"]
    folds, chosen_eq, chosen_tr = [], [], []
    grid_eq: dict[int, list] = {i: [] for i in range(len(grid))}
    for is_s, is_e, oos_s, oos_e in wf.fold_windows(prep.dates):
        scores = []
        for i, p in enumerate(grid):
            r = run(cfg, prep, p, is_s, is_e, warm_start=warm_start, contribution=contribution)
            scores.append(_sharpe(r.equity) if len(r.trades) >= wf.MIN_IS_TRADES else -np.inf)
        best = int(np.argmax(scores)) if max(scores) > -np.inf else 0
        b = bench[(bench.index >= oos_s) & (bench.index <= oos_e)]
        for i, p in enumerate(grid):
            r = run(cfg, prep, p, oos_s, oos_e, warm_start=warm_start, contribution=contribution)
            grid_eq[i].append(r.equity)
            if i == best:
                chosen_eq.append(r.equity)
                t = r.trades.copy()
                t["fold"] = oos_s.year
                chosen_tr.append(t)
                m = summarize(r.equity, r.trades)
                dep = deposit_schedule(prep, oos_s, oos_e, cfg.capital, contribution)
                idx_val = matched_value(bench, dep) if len(dep) else float("nan")
                folds.append({
                    "end_value": round(float(r.equity["value"].iloc[-1]), 2), "deposited": round(float(dep.sum()), 2),
                    "index_end_value": round(idx_val, 2), "avg_value": round(float(r.equity["value"].mean()), 2),
                    "days": int((r.equity.index[-1] - r.equity.index[0]).days),
                    "oos_year": oos_s.year, "params": p.label(), "grid_index": i, "oos_return_pct": m["total_return_pct"],
                    "oos_maxdd_pct": m["max_drawdown_pct"], "trades": m["trades"],
                    "turnover_per_yr": round(r.turnover_per_year, 2), "exposure_pct": m["exposure_pct"],
                    "bench_return_pct": round(100 * (b.iloc[-1] / b.iloc[0] - 1), 2),
                })
    if not chosen_eq:
        raise SystemExit("Not enough history for walk-forward. Run `trader update`.")
    return {
        "folds": folds,
        "equity": wf._chain(chosen_eq, cfg.capital),
        "trades": pd.concat(chosen_tr, ignore_index=True) if chosen_tr else pd.DataFrame(),
        "grid": {grid[i].label(): wf._chain(v, cfg.capital) for i, v in grid_eq.items()},
    }
