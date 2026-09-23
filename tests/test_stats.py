import numpy as np

from ktr import stats


def test_centred_slope_ignores_block_levels():
    # two blocks with the same slope (2) but very different intercepts;
    # a pooled slope would be badly biased, the within-block one isn't
    rng = np.random.default_rng(1)
    rows = []
    for level in (0.0, 100.0):
        x = rng.normal(size=500) + level / 10
        y = level + 2 * x + rng.normal(scale=0.1, size=500)
        rows.append([len(x), x.sum(), y.sum(), (x * y).sum(), (x * x).sum()])
    n, sx, sy, sxy, sxx = np.array(rows).T
    cxy = stats.centred(n, sx, sy, sxy)
    cxx = stats.centred(n, sx, sx, sxx)
    assert abs(stats.slope([cxy.sum(), cxx.sum()]) - 2) < 0.01


def test_bootstrap_mean_interval_covers_truth():
    rng = np.random.default_rng(2)
    blocks = []
    for _ in range(200):
        x = rng.normal(loc=0.3, size=50)
        blocks.append([x.sum(), len(x)])
    est, draws = stats.bootstrap(blocks, stats.mean, n=500)
    lo, hi = stats.interval(draws)
    assert lo < 0.3 < hi
    assert abs(est - 0.3) < 0.05


def test_half_life_interpolates():
    assert stats.half_life([1, 2, 4], [0.9, 0.7, 0.3]) == 3.0
    assert np.isnan(stats.half_life([1, 2], [0.9, 0.8]))
    assert stats.half_life([1, 2], [0.4, 0.1]) == 1
