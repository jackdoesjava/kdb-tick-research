"""Block bootstrap over per-block sums.

Tick data is heavily autocorrelated and the horizons overlap, so treating
every observation as independent would give confidence intervals that are
far too narrow. Instead each block (a day for FX, five minutes for the one
SPY day) is reduced in q to a handful of sums, and we resample whole blocks.
Anything that's a function of totals of those sums (a mean, a regression
slope) can then be bootstrapped cheaply because resampling blocks is just
resampling rows of a small array.
"""

import numpy as np


def bootstrap(blocks, stat, n=2000, seed=0):
    """blocks: (n_blocks, k) array of per-block sums.
    stat: maps a length-k vector of totals to a number (or array).
    Returns (estimate on the full sample, array of n bootstrap draws)."""
    b = np.asarray(blocks, dtype=float)
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n):
        idx = rng.integers(0, len(b), len(b))
        draws.append(stat(b[idx].sum(axis=0)))
    return stat(b.sum(axis=0)), np.array(draws)


def interval(draws, level=0.95):
    """Percentile interval of the bootstrap draws."""
    a = (1 - level) / 2
    return np.nanquantile(draws, [a, 1 - a], axis=0)


def centred(n, sx, sy, sxy):
    """Within-block centred cross-product: sum((x - xbar)(y - ybar)).

    Centring inside each block means a slope built from these ignores
    level differences between blocks (a per-day intercept)."""
    n = np.asarray(n, dtype=float)
    return np.asarray(sxy) - np.asarray(sx) * np.asarray(sy) / np.where(n > 0, n, np.nan)


def slope(totals):
    """totals = [sum of centred xy, sum of centred xx]."""
    return totals[0] / totals[1]


def mean(totals):
    """totals = [sum, count]."""
    return totals[0] / totals[1]


def half_life(horizons, rho):
    """First horizon where the autocorrelation drops to 0.5, interpolating
    linearly in between the horizons we measured. nan if it never does."""
    horizons = np.asarray(horizons, dtype=float)
    rho = np.asarray(rho, dtype=float)
    below = np.nonzero(rho <= 0.5)[0]
    if len(below) == 0:
        return np.nan
    i = below[0]
    if i == 0:
        return horizons[0]
    h0, h1, r0, r1 = horizons[i - 1], horizons[i], rho[i - 1], rho[i]
    return h0 + (r0 - 0.5) / (r0 - r1) * (h1 - h0)
