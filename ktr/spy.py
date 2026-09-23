"""Turn the Databento SPY MBP-10 file into quote and trade tables.

The file is Nasdaq TotalView-ITCH for SPY on 2021-01-28, one record per book
event with the top 10 levels attached. A few things worth knowing about it:

* action 'A'/'C' records change the book, 'T' records are trades. The book
  carried on a 'T' record is the book *before* the fill; the fill itself shows
  up as a following 'C' with the same ts_recv.
* on trades, side is the aggressor ('B' lifted the offer, 'A' hit the bid).
  'N' trades are hidden/midpoint executions with no aggressor, about 11% of
  prints. They're kept but can't be signed.
* flags bit 128 (F_LAST) marks the last record of an exchange packet. Only
  those book states are complete. In this file every book record has it set,
  and only some trades don't, but the filter is kept in case other days differ.

Timestamps: ts_recv (when Databento's capture box saw the packet) is used as
the time column, not ts_event (the matching engine clock). ts_recv is what a
trader could actually have known and is the order the file is sorted in.
"""

import databento as db
import numpy as np
import pandas as pd

F_LAST = 128
DEPTH_LEVELS = 5  # levels summed into bdepth/adepth
UNDEF_PRICE = np.iinfo(np.int64).max


def read(path):
    return db.DBNStore.from_file(path).to_ndarray()


def _px(a):
    # fixed-point 1e-9 prices, with int64 max meaning "no level"
    out = a.astype(float) / 1e9
    out[a == UNDEF_PRICE] = np.nan
    return out


def quotes(rec, sym="SPY"):
    """One row per book event where top-of-book or top-5 depth changed."""
    act = rec["action"].view("S1")
    book = (act != b"T") & ((rec["flags"] & F_LAST) > 0)
    r = rec[book]

    bdepth = sum(r[f"bid_sz_{i:02d}"].astype(float) for i in range(DEPTH_LEVELS))
    adepth = sum(r[f"ask_sz_{i:02d}"].astype(float) for i in range(DEPTH_LEVELS))
    q = pd.DataFrame({
        "time": r["ts_recv"].astype("datetime64[ns]"),
        "sym": sym,
        "bid": _px(r["bid_px_00"]),
        "ask": _px(r["ask_px_00"]),
        "bsize": r["bid_sz_00"].astype(float),
        "asize": r["ask_sz_00"].astype(float),
        "bdepth": bdepth,
        "adepth": adepth,
    })

    # most events deeper than level 5 leave these columns untouched, so drop
    # rows that repeat the previous state exactly
    cols = ["bid", "ask", "bsize", "asize", "bdepth", "adepth"]
    v = q[cols].to_numpy()
    eq = (v[1:] == v[:-1]) | (np.isnan(v[1:]) & np.isnan(v[:-1]))
    same = np.zeros(len(q), bool)
    same[1:] = eq.all(axis=1)
    return q[~same].reset_index(drop=True)


def trades(rec, sym="SPY"):
    act = rec["action"].view("S1")
    r = rec[act == b"T"]
    side = pd.Series(r["side"].view("S1")).map({b"B": "B", b"A": "S", b"N": ""})
    return pd.DataFrame({
        "time": r["ts_recv"].astype("datetime64[ns]"),
        "sym": sym,
        "price": _px(r["price"]),
        "size": r["size"].astype(np.int64),
        "side": side.to_numpy(),
    })
