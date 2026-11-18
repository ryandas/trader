"""Rolling walk-forward: tune on 3 years, trade the next unseen year, repeat.

Per fold: (1) for each strategy pick the parameter set with the best in-sample Sharpe,
(2) fit the selector's strategy x market-regime expectancy table on those in-sample trades,
(3) trade the OOS year with the chosen parameters and selector. Only OOS results are reported.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import backtest as bt
from .config import Config
from .metrics import summarize
from .selector import Selector
from .strategies import ALL, Strategy

MIN_IS_TRADES = 30
WARMUP_BARS = 260  # indicators (200 SMA, 126d momentum) need history before signals are valid

GRIDS: dict[str, list[dict]] = {
    "trend_pullback": [
        {},  # defaults: RSI 40-50, 2R target, 3 ATR trail
        {"rsi_lo": 35, "rsi_hi": 45},
        {"rr": 3.0},
        {"rr": 1.5, "trail_atr": 2.5},
    ],
    "breakout": [
        {},  # defaults: 1.5x volume, 2 ATR stop
        {"vol_mult": 2.0},
        {"atr_stop": 3.0},
    ],
    "mean_reversion": [
        {},  # defaults: RSI2 < 10, 2.5 ATR stop
        {"rsi2_max": 5},
        {"rsi2_max": 15},
        {"atr_stop": 3.5},
    ],
}


def build_grid() -> dict[str, Strategy]:
    """key -> strategy instance for every parameter set. Key '<name>#0' is the default set."""
    out: dict[str, Strategy] = {}
    for name, grid in GRIDS.items():
        for i, params in enumerate(grid):
            st = ALL[name](**params)
            st.key, st.params = f"{name}#{i}", params
            out[st.key] = st
    return out


def fold_windows(dates: pd.DatetimeIndex, is_years: int = 3) -> list[tuple]:
    """(is_start, is_end, oos_start, oos_end) per calendar-year OOS fold."""
    first_ok = dates[min(WARMUP_BARS, len(dates) - 1)]
    folds = []
    for year in range(first_ok.year + is_years, dates[-1].year + 1):
        oos_start = pd.Timestamp(year, 1, 1)
        is_start = oos_start - pd.DateOffset(years=is_years)
        if is_start < first_ok or oos_start > dates[-1]:
            continue
        oos_end = min(pd.Timestamp(year, 12, 31), dates[-1])
        if (oos_end - oos_start).days < 60:
            continue
        folds.append((is_start, oos_start - pd.Timedelta(days=1), oos_start, oos_end))
    return folds


def _sharpe(equity: pd.DataFrame) -> float:
    r = equity["equity"].pct_change().dropna()
    return float(r.mean() / r.std() * np.sqrt(252)) if len(r) > 20 and r.std() > 0 else -np.inf


def fit(
    cfg: Config, prep: bt.Prepared, grid: dict[str, Strategy], is_start, is_end
) -> tuple[dict[str, str], Selector, pd.DataFrame]:
    """Pick parameters per strategy and fit the selector on [is_start, is_end]."""
    chosen: dict[str, str] = {}
    all_trades = []
    for name, grid_cfg in GRIDS.items():
        best_key, best_score, best_trades = f"{name}#0", -np.inf, pd.DataFrame()
        for i in range(len(grid_cfg)):
            key = f"{name}#{i}"
            res = bt.run(cfg, prep, grid, is_start, is_end, only={key})
            score = _sharpe(res.equity) if len(res.trades) >= MIN_IS_TRADES else -np.inf
            if score > best_score or best_trades.empty and i == 0:
                best_key, best_score, best_trades = key, score, res.trades
        chosen[name] = best_key
        all_trades.append(best_trades)
    trades = pd.concat([t for t in all_trades if len(t)]) if any(len(t) for t in all_trades) else pd.DataFrame()
    return chosen, Selector.from_trades(trades, cfg.regime.min_stat_trades), trades


@dataclass
class WFResult:
    folds: pd.DataFrame
    trades: pd.DataFrame
    equity: pd.DataFrame
    baseline_equity: pd.DataFrame
    baseline_trades: pd.DataFrame


def _chain(parts: list[pd.DataFrame], capital: float) -> pd.DataFrame:
    """Join per-fold equity curves, carrying the ending equity into the next fold.

    Every fold's curve is a fresh start from `capital`, so its first row already includes day-1's return."""
    out, level = [], capital
    for p in parts:
        scaled = p.copy()
        # Each fold's curve starts from its own capital at the open of day 1, so its first-day
        # return is equity[0] / capital - 1. Scale by level / capital to keep that return.
        scaled["equity"] = p["equity"] / capital * level
        level = scaled["equity"].iloc[-1]
        out.append(scaled)
    return pd.concat(out)


def walk_forward(
    cfg: Config, prep: bt.Prepared, base_prep: bt.Prepared, grid: dict[str, Strategy]
) -> WFResult:
    defaults = {k: v for k, v in grid.items() if k.endswith("#0")}
    fold_rows, oos_eq, oos_tr, base_eq, base_tr = [], [], [], [], []
    for is_s, is_e, oos_s, oos_e in fold_windows(prep.dates):
        chosen, sel, _ = fit(cfg, prep, grid, is_s, is_e)
        res = bt.run(cfg, prep, grid, oos_s, oos_e, sel, only=set(chosen.values()))
        base = bt.run(cfg, base_prep, defaults, oos_s, oos_e)  # step-3 baseline, defaults
        for r, bucket_e, bucket_t, tag in ((res, oos_eq, oos_tr, "wf"), (base, base_eq, base_tr, "base")):
            if len(r.equity):
                bucket_e.append(r.equity)
                t = r.trades.copy()
                t["fold"] = oos_s.year
                bucket_t.append(t)
        m = summarize(res.equity, res.trades)
        mb = summarize(base.equity, base.trades)
        fold_rows.append({
            "oos_year": oos_s.year, "is": f"{is_s.date()}..{is_e.date()}",
            "params": json.dumps({k: v for k, v in chosen.items()}),
            "switched_off": json.dumps(sorted(f"{n}|{r}" for (n, r), v in sel.stats.items() if v <= 0)),
            "oos_return_pct": m["total_return_pct"], "oos_maxdd_pct": m["max_drawdown_pct"],
            "oos_trades": m["trades"], "base_return_pct": mb["total_return_pct"],
            "base_maxdd_pct": mb["max_drawdown_pct"], "base_trades": mb["trades"],
        })
        print(
            f"fold {oos_s.year}: wf {m['total_return_pct']:+.1f}% (dd {m['max_drawdown_pct']:.1f}%, "
            f"{m['trades']} trades) | baseline {mb['total_return_pct']:+.1f}% (dd {mb['max_drawdown_pct']:.1f}%)"
        )
    if not oos_eq:
        raise SystemExit("Not enough history for a walk-forward fold. Run `trader update` for more data.")
    cat = lambda xs: pd.concat(xs, ignore_index=True) if xs else pd.DataFrame()  # noqa: E731
    return WFResult(
        pd.DataFrame(fold_rows), cat(oos_tr), _chain(oos_eq, cfg.capital),
        _chain(base_eq, cfg.capital), cat(base_tr),
    )
