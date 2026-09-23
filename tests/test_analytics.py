"""Research functions in analytics.q, checked against hand examples and
straightforward numpy versions of the same calculation."""

import numpy as np
import pandas as pd
import pytest

from conftest import HDB, needs_q, quotes
from ktr.qproc import QProc, connect

pytestmark = needs_q

LOADER = 15020
FXDAY = "2025.01.02"
SPYDAY = "2021.01.28"


def random_walk(rng, n, start, t0, spacing_ms, tick):
    times = pd.Timestamp(t0) + pd.to_timedelta(np.cumsum(rng.integers(1, 2 * spacing_ms, n)), unit="ms")
    mid = start + tick * np.cumsum(rng.choice([-1, 0, 1], n))
    return times, mid


def fx_quotes(rng):
    frames = []
    for sym, start, tick in [("EURUSD", 1.10, 1e-5), ("USDJPY", 150.0, 1e-3), ("EURJPY", 165.0, 1e-3)]:
        t, m = random_walk(rng, 3000, start, "2025-01-02 10:00", 100, tick)
        frames.append(quotes(t, sym=sym, bid=m - 2 * tick, ask=m + 2 * tick))
    return pd.concat(frames).sort_values("time", kind="mergesort", ignore_index=True)


def spy_tables(rng):
    t, m = random_walk(rng, 5000, 370.0, "2021-01-28 15:00", 20, 0.01)
    m = np.round(m, 2)
    # rounded so equal prices are exactly equal: q compares floats with a
    # small tolerance and numpy doesn't, which otherwise breaks the OFI check
    bid = np.round(m - 0.005 - 0.01 * rng.integers(0, 2, len(m)), 3)
    q = quotes(t, sym="SPY", bid=bid, ask=np.round(m + 0.005, 3))
    q["bsize"] = rng.integers(1, 20, len(q)) * 100.0
    q["asize"] = rng.integers(1, 20, len(q)) * 100.0
    q["bdepth"] = q["bsize"] * 5
    q["adepth"] = q["asize"] * 5
    idx = np.sort(rng.choice(len(q), 300, replace=False))
    tr = pd.DataFrame({"time": q["time"].iloc[idx].to_numpy(), "sym": "SPY",
                       "price": q["ask"].iloc[idx].to_numpy(), "size": np.full(300, 100),
                       "side": rng.choice(["B", "S", ""], 300)})
    return q, tr


@pytest.fixture(scope="module")
def hdb(tmp_path_factory):
    d = tmp_path_factory.mktemp("hdb")
    rng = np.random.default_rng(7)
    fx = fx_quotes(rng)
    sq, st = spy_tables(rng)
    import pykx as kx
    with QProc("q/schema.q", LOADER) as _:
        q = connect(LOADER)
        db = kx.SymbolAtom(":" + str(d).replace("\\", "/"))
        for day, qt, tt in [(SPYDAY, sq, st), (FXDAY, fx, None)]:
            q("insert", kx.SymbolAtom("quote"), qt)
            if tt is not None:
                q("insert", kx.SymbolAtom("trade"), tt)
            q(f"{{[d] .Q.dpft[d;{day};`sym;] each `quote`trade; delete from `quote; delete from `trade}}", db)
    with QProc("q/hdb.q", HDB, ["-db", str(d)]):
        yield connect(HDB)


def asof(times, values, at):
    i = np.searchsorted(times, at, side="right") - 1
    out = np.where(i >= 0, values[np.maximum(i, 0)], np.nan)
    return out


def test_grid_uses_only_past_quotes(hdb):
    g = hdb(f"`time xasc .fx.grid[{FXDAY};`EURJPY`EURUSD`USDJPY`mul;0D00:00:00.1;0D10:00;0D10:05;0D00:01]").pd()
    raw = hdb(f"select time,sym,bid,ask from quote where date={FXDAY}").pd()
    grid = g["time"].to_numpy()
    for sym, col in [("EURJPY", "cb"), ("EURUSD", "b1"), ("USDJPY", "b2")]:
        r = raw[raw["sym"] == sym]
        expect = asof(r["time"].to_numpy(), r["bid"].to_numpy(), grid)
        np.testing.assert_allclose(g[col].to_numpy(), expect, equal_nan=True)
    sm = (g.b1 + g.a1) / 2 * (g.b2 + g.a2) / 2
    np.testing.assert_allclose(g["gap"], 1e4 * np.log((g.cb + g.ca) / 2 / sm), equal_nan=True)


def test_closure_sums_match_numpy(hdb):
    g = hdb(f".fx.grid[{FXDAY};`EURJPY`EURUSD`USDJPY`mul;0D00:00:00.1;0D10:00;0D10:05;0D00:01]").pd()
    for k in (1, 10):
        got = hdb(f".fx.closure[.fx.grid[{FXDAY};`EURJPY`EURUSD`USDJPY`mul;0D00:00:00.1;0D10:00;0D10:05;0D00:01];{k}]").py()
        x = g["gap"].to_numpy()
        yc = 1e4 * np.log(np.roll(g["cm"].to_numpy(), -k) / g["cm"].to_numpy())
        ys = 1e4 * np.log(np.roll(g["sm"].to_numpy(), -k) / g["sm"].to_numpy())
        yc[-k:] = np.nan
        ys[-k:] = np.nan
        ok = ~np.isnan(x) & ~np.isnan(yc) & ~np.isnan(ys)
        assert got["n"] == ok.sum()
        assert np.isclose(got["sxyc"], (x * yc)[ok].sum())
        assert np.isclose(got["sxys"], (x * ys)[ok].sum())
        assert np.isclose(got["sxx"], (x * x)[ok].sum())


def test_taker_counts_onsets_only(hdb):
    g = hdb(f".fx.grid[{FXDAY};`EURJPY`EURUSD`USDJPY`mul;0D00:00:00.1;0D10:00;0D10:05;0D00:01]").pd()
    th, lat, hold = 1.0, 1, 5
    got = hdb(f".fx.taker[.fx.grid[{FXDAY};`EURJPY`EURUSD`USDJPY`mul;0D00:00:00.1;0D10:00;0D10:05;0D00:01];{th};{lat};{hold}]").py()
    gap = g["gap"].to_numpy()
    cb, ca = g["cb"].to_numpy(), g["ca"].to_numpy()
    n = len(g)
    buy = ~np.isnan(gap) & (gap < -th)
    sell = ~np.isnan(gap) & (gap > th)
    buy = buy & ~np.r_[False, buy[:-1]]
    sell = sell & ~np.r_[False, sell[:-1]]
    pnl, free_at = [], 0
    for i in np.nonzero(buy | sell)[0]:
        if i < free_at:
            continue                     # previous trade still open
        free_at = i + lat + hold
        if i + lat + hold >= n:
            continue
        if buy[i]:
            pnl.append(1e4 * np.log(cb[i + lat + hold] / ca[i + lat]))
        else:
            pnl.append(1e4 * np.log(cb[i + lat] / ca[i + lat + hold]))
    pnl = np.array(pnl)
    pnl = pnl[~np.isnan(pnl)]
    assert got["n"] == len(pnl)
    assert np.isclose(got["s"], pnl.sum())


def test_taker_with_no_signals(hdb):
    got = hdb(f".fx.taker[.fx.grid[{FXDAY};`EURJPY`EURUSD`USDJPY`mul;0D00:00:00.1;0D10:00;0D10:05;0D00:01];1e6;1;5]").py()
    assert got == {"n": 0, "s": 0.0, "s2": 0.0}


def test_fx_day_runs(hdb):
    r = hdb(f".fx.day[{FXDAY};`EURJPY`EURUSD`USDJPY`mul]")
    r = dict(zip(r.keys().py(), r.values()))
    assert len(r["closure"].pd()) == 9
    assert len(r["taker"].pd()) == 5 * 4 * 3


def test_markouts(hdb):
    q = hdb(f"select time,mid:0.5*bid+ask from quote where date={SPYDAY}").pd()
    t = hdb(f"select time,price,side from trade where date={SPYDAY}, side in `B`S").pd()
    m = hdb(f".spy.markouts[{SPYDAY};0D00:00:00 0D00:00:01]").pd()
    assert len(m) == len(t)          # one fill per timestamp in the test data
    qt, qm = q["time"].to_numpy(), q["mid"].to_numpy()
    tt = t["time"].to_numpy()
    # the trades sit exactly on quote timestamps, so strictly-before matters
    m0 = asof(qt, qm, tt - np.timedelta64(1, "ns"))
    m1 = asof(qt, qm, tt + np.timedelta64(1, "s"))
    sign = np.where(t["side"] == "B", 1.0, -1.0)
    np.testing.assert_allclose(m["hs"], 1e4 * sign * np.log(t["price"] / m0), atol=1e-9)
    np.testing.assert_allclose(m["mk1"], 1e4 * sign * np.log(t["price"] / m1), atol=1e-9)
    assert not np.allclose(m0, asof(qt, qm, tt))


def test_markouts_merge_fills_of_one_order(hdb):
    # three fills of a buy sweeping the book at one timestamp are one order
    got = hdb("{t:([] time:3#2021.01.28D15:00:00; sym:`SPY; price:370.01 370.02 370.03; size:100 200 100; side:`B);"
              " 0!select price:size wavg price, sum size by time,sym,side from t}[]").pd()
    assert len(got) == 1
    assert got["size"].iloc[0] == 400
    assert np.isclose(got["price"].iloc[0], 370.02)


def test_next_mid_of_each_run(hdb):
    # same expressions as .spy.qimb on a hand-made mid path
    got = hdb("{mid:1 1 2 2 2 1 3f; r:sums differ mid; m:mid where differ mid; m r}[]").py()
    assert got[:6] == [2, 2, 1, 1, 1, 3]
    assert np.isnan(got[6])


def test_ofi_matches_cont_formula(hdb):
    raw = hdb(f"select time,bid,ask,bsize,asize from quote where date={SPYDAY}").pd()
    b = hdb(f".spy.ofi[{SPYDAY};0D14:30;0D21:00;0D00:00:10]").pd()
    pb, pa = raw.bid.shift(), raw.ask.shift()
    pbs, pas = raw.bsize.shift(), raw.asize.shift()
    e = ((raw.bid >= pb) * raw.bsize - (raw.bid <= pb) * pbs
         - (raw.ask <= raw.ask.shift()) * raw.asize + (raw.ask >= pa) * pas).iloc[1:]
    bucket = raw.time.iloc[1:].dt.floor("10s")
    expect = e.groupby(bucket).sum()
    np.testing.assert_allclose(b["ofi"].to_numpy(), expect.to_numpy())
