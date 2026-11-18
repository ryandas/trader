"""Pure fill/exit simulation shared by the backtester and the paper ledger."""
from __future__ import annotations


def fill_entry(
    entry_type: str,
    trigger: float | None,
    max_entry: float | None,
    o: float,
    h: float,
    l: float,
) -> float | None:
    """Entry price on the session after the signal, or None if the order doesn't fill.

    'open': buy at the open. 'stop': buy-stop at `trigger`, gap-ups fill at the open.
    `max_entry` rejects fills that are too far above the signal level.
    """
    if entry_type == "open":
        price = o
    elif entry_type == "stop":
        if h < trigger:
            return None
        price = max(o, trigger)
    else:
        raise ValueError(entry_type)
    if max_entry is not None and price > max_entry:
        return None
    return price


def check_exit(
    stop: float, target: float | None, o: float, h: float, l: float
) -> tuple[float, str] | None:
    """Stop/target exit within a bar. If both are reachable, the stop is assumed first."""
    if o <= stop:
        return o, "stop_gap"
    if l <= stop:
        return stop, "stop"
    if target is not None:
        if o >= target:
            return o, "target_gap"
        if h >= target:
            return target, "target"
    return None
