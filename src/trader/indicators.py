"""Vectorised indicators. All use only data up to and including each bar (no lookahead)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _wilder(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat(
        [df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1
    ).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return _wilder(true_range(df), n)


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up, down = _wilder(d.clip(lower=0), n), _wilder((-d).clip(lower=0), n)
    out = 100 - 100 / (1 + up / down)
    return out.where(down != 0, 100.0)


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up, down = df["high"].diff(), -df["low"].diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr = _wilder(true_range(df), n)
    pdi, mdi = 100 * _wilder(plus, n) / tr, 100 * _wilder(minus, n) / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    return _wilder(dx.fillna(0), n)


def donchian_high(df: pd.DataFrame, n: int) -> pd.Series:
    """Highest high of the PREVIOUS n bars (excludes the current bar)."""
    return df["high"].shift(1).rolling(n, min_periods=n).max()


def donchian_low(df: pd.DataFrame, n: int) -> pd.Series:
    return df["low"].shift(1).rolling(n, min_periods=n).min()


def roc(s: pd.Series, n: int) -> pd.Series:
    return s / s.shift(n) - 1


def volume_ratio(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Volume relative to the average of the previous n bars."""
    return df["volume"] / df["volume"].shift(1).rolling(n, min_periods=n).mean()
