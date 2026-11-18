"""Test helpers shared across modules."""
from trader.data import store


def patch_candles(monkeypatch, frames: dict) -> None:
    """Serve synthetic candle frames instead of the database."""
    monkeypatch.setattr(store, "load", lambda s: frames.get(s))
    monkeypatch.setattr(store, "load_many", lambda syms: {s: frames[s] for s in syms if s in frames})
