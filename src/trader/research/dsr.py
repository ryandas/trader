"""Deflated Sharpe ratio (Bailey & Lopez de Prado, 2014): the probability that the true Sharpe is
above what the best of `n_trials` skill-less strategies would show by luck."""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

EULER_GAMMA = 0.5772156649015329
# Used when too few past trials exist to estimate the spread of trial Sharpes:
# annualised Sharpes of unrelated ideas spread by roughly 0.5, i.e. this much per day.
DEFAULT_TRIAL_SR_VAR = (0.5 / math.sqrt(252)) ** 2
MIN_TRIALS_FOR_VAR = 5

_N = NormalDist()


def expected_max_sharpe(n_trials: int, trial_sr_var: float) -> float:
    """Expected maximum per-period Sharpe among `n_trials` independent skill-less trials."""
    if n_trials <= 1:
        return 0.0
    return math.sqrt(trial_sr_var) * (
        (1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n_trials)
        + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n_trials * math.e))
    )


def deflated_sharpe(returns: pd.Series, n_trials: int, past_trial_sharpes: list[float] | None = None) -> float:
    """DSR in [0, 1] from per-period returns. With one trial it is the probabilistic Sharpe vs 0."""
    r = pd.Series(returns).dropna()
    t = len(r)
    if t < 30 or r.std() == 0:
        return 0.0
    sr = float(r.mean() / r.std())
    skew = float(r.skew())
    kurt = float(r.kurt()) + 3.0  # pandas gives excess kurtosis
    ps = [s for s in (past_trial_sharpes or []) if np.isfinite(s)]
    var = float(np.var(ps, ddof=1)) if len(ps) >= MIN_TRIALS_FOR_VAR else DEFAULT_TRIAL_SR_VAR
    sr0 = expected_max_sharpe(n_trials, var)
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr**2
    if denom <= 0:
        return 0.0
    return float(_N.cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom)))
