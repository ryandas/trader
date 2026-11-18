from __future__ import annotations

import numpy as np
import pandas as pd


def _cagr(eq: pd.Series) -> float:
    days = (eq.index[-1] - eq.index[0]).days
    # annualising a window shorter than a year is meaningless (6 weeks of +3% is not +40%/yr)
    return (eq.iloc[-1] / eq.iloc[0]) ** (365.25 / days) - 1 if days >= 365 else float("nan")


def _max_dd(eq: pd.Series) -> float:
    return float((eq / eq.cummax() - 1).min())


def summarize(
    equity: pd.DataFrame, trades: pd.DataFrame, benchmark: pd.Series | None = None
) -> dict:
    """`equity` has columns equity, invested (fraction of equity in positions)."""
    eq = equity["equity"]
    ret = eq.pct_change().dropna()
    down = ret[ret < 0]
    out = {
        "start": str(eq.index[0].date()),
        "end": str(eq.index[-1].date()),
        "final_equity": round(float(eq.iloc[-1]), 2),
        "total_return_pct": round(100 * (eq.iloc[-1] / eq.iloc[0] - 1), 2),
        "cagr_pct": None if np.isnan(_cagr(eq)) else round(100 * _cagr(eq), 2),
        "max_drawdown_pct": round(100 * _max_dd(eq), 2),
        "sharpe": round(float(ret.mean() / ret.std() * np.sqrt(252)), 2) if ret.std() > 0 else None,
        "sortino": round(float(ret.mean() / down.std() * np.sqrt(252)), 2)
        if len(down) > 1 and down.std() > 0
        else None,
        "exposure_pct": round(100 * float(equity["invested"].mean()), 1),
        "trades": int(len(trades)),
    }
    if len(trades):
        win = trades[trades["net_pnl"] > 0]
        loss = trades[trades["net_pnl"] <= 0]
        gl = abs(loss["net_pnl"].sum())
        out |= {
            "win_rate_pct": round(100 * len(win) / len(trades), 1),
            "avg_win": round(float(win["net_pnl"].mean()), 2) if len(win) else 0.0,
            "avg_loss": round(float(loss["net_pnl"].mean()), 2) if len(loss) else 0.0,
            "profit_factor": round(float(win["net_pnl"].sum() / gl), 2) if gl > 0 else None,
            "avg_hold_days": round(float(trades["bars_held"].mean()), 1),
            "total_costs": round(float(trades["costs"].sum()), 2),
        }
        if "risk" in trades:  # stop-based strategies: net P&L per unit of capital risked
            out["expectancy_R"] = round(float(trades["net_pnl"].sum() / trades["risk"].sum()), 3)
        if "ret_pct" in trades:  # rotation strategies have no stops, so no R
            out["avg_trade_return_pct"] = round(float(trades["ret_pct"].mean()), 2)
    if benchmark is not None and len(benchmark):
        b = benchmark.reindex(eq.index).ffill().dropna()
        if len(b) > 1:
            out["benchmark_total_return_pct"] = round(100 * (b.iloc[-1] / b.iloc[0] - 1), 2)
            if not np.isnan(_cagr(b)):
                out["benchmark_cagr_pct"] = round(100 * _cagr(b), 2)
            out["benchmark_max_drawdown_pct"] = round(100 * _max_dd(b), 2)
    return out
