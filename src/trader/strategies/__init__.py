from .base import SignalSet, Strategy, features
from .breakout import Breakout
from .mean_reversion import MeanReversion
from .trend_pullback import TrendPullback

ALL = {s.name: s for s in (TrendPullback, Breakout, MeanReversion)}

__all__ = ["ALL", "Breakout", "MeanReversion", "SignalSet", "Strategy", "TrendPullback", "features"]
