"""Amihud illiquidity premium: rank by the highest trailing Amihud illiquidity (|return| / traded value)."""
META = {
    "slug": "amihud",
    "kind": "rotation",
    "hypothesis": "Less liquid stocks earn a premium for bearing illiquidity risk (Amihud 2002), so within the liquid "
                  "universe the relatively least liquid names should earn more.",
    "source": "Amihud (2002), 'Illiquidity and stock returns: cross-section and time-series effects', J. Financial "
              "Markets 5. Not yet checked for India-specific evidence; effect size sample-dependent.",
    # fixed before any result: window 20 or 60 bars; quarterly cadence (INR 15.34 per sale), ~10 names
    "grid": [
        {"window": 20, "top_n": 10, "buffer": 5, "rebalance": "Q"},
        {"window": 60, "top_n": 10, "buffer": 5, "rebalance": "Q"},
    ],
}


def score(prep, window: int = 20):
    """Amihud illiquidity (higher = less liquid = buy), from `prep.amihud`. Uses bars <= t only."""
    return prep.amihud(window)
