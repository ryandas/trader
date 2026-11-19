"""Test helpers shared across modules."""
import importlib
import sys

import numpy as np
import pandas as pd

from trader import backtest as bt
from trader import momentum as mom
from trader import paper
from trader.accounting import CashBox
from trader.costs import apply_slippage, trade_costs
from trader.data import store
from trader.selector import Selector

MP = mom.MomParams(lookback=126, skip=21, top_n=5, buffer=3)
CP = mom.MomParams(lookback=60, skip=5, top_n=3, buffer=2)  # a candidate sleeve: different ranking, 3 names
CAPITAL, DEPOSIT = 50_000.0, 5_000.0
HONEST = "def score(prep, **k):\n    return (prep.close_df / prep.close_df.shift(60) - 1).to_numpy()"


def patch_candles(monkeypatch, frames: dict) -> None:
    """Serve synthetic candle frames instead of the database."""
    monkeypatch.setattr(store, "load", lambda s: frames.get(s))
    monkeypatch.setattr(store, "load_many", lambda syms: {s: frames[s] for s in syms if s in frames})


def synth(n=500, seed=1, drift=0.0006):
    rng = np.random.default_rng(seed)
    close = 200 * np.exp(np.cumsum(rng.normal(drift, 0.015, n)))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
    vol = rng.integers(2_000_000, 6_000_000, n).astype(float)
    vol[::37] *= 3
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=pd.bdate_range("2022-01-03", periods=n, name="date"),
    )


def _frames():
    frames = {f"S{i}": synth(600, seed=i) for i in range(8)}
    frames["NIFTY500"] = synth(600, seed=99, drift=0.0004)
    return frames


def _books(acct, cash):
    cfg, _, idx, sprep, strats, mprep = acct
    box = CashBox(cash)
    swing = bt.SwingBook(cfg, sprep, strats, box, Selector())
    mbook = mom.MomBook(cfg, mprep, MP, box)
    return cfg, idx, sprep, mprep, box, swing, mbook


def buy_cost(cfg, open_px, qty):
    """Cash a buy of `qty` shares takes at the open: shares x (open + 5 bps slippage) + the statutory charges."""
    fp = apply_slippage(open_px, "buy", cfg.costs.slippage_bps)
    return qty * fp + trade_costs("buy", qty * fp, cfg.costs)


def write_cand(cdir, slug, body, grid="[{}]", extra=""):
    (cdir / f"{slug}.py").write_text(
        f'META = {{"slug": "{slug}", "kind": "rotation", "hypothesis": "h", "source": "s", "grid": {grid}{extra}}}\n{body}\n')
    sys.modules.pop(f"trader.research.candidates.{slug}", None)
    importlib.invalidate_caches()  # FileFinder caches dir listings; same-second writes are otherwise missed


def _ledger(lab, slug, body, extra=""):
    cfg, inst, idx, cdir = lab
    write_cand(cdir, slug, body, extra=extra)
    paper.init_momentum(cfg, idx[300], mom.MomParams(top_n=5, buffer=3), None)
    return cfg, inst, idx, cdir
