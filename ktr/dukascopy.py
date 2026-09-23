"""Download and decode Dukascopy historical FX ticks.

Dukascopy serves one LZMA-compressed .bi5 file per symbol per UTC hour at
    https://datafeed.dukascopy.com/datafeed/EURUSD/2025/00/02/13h_ticks.bi5
Note the month is zero-based (00 = January). Each decompressed record is 20
bytes, big-endian:
    uint32  ms since the start of the hour
    uint32  ask * point
    uint32  bid * point
    float32 ask volume
    float32 bid volume
where point is 1e3 for JPY-quoted pairs and 1e5 for everything else.

These are quotes from Dukascopy's own ECN, not the interbank market, and they
arrive at roughly 100ms spacing, so nothing faster than that can be measured.
"""

import lzma
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

BASE_URL = "https://datafeed.dukascopy.com/datafeed"

RECORD = np.dtype([("ms", ">u4"), ("ask", ">u4"), ("bid", ">u4"),
                   ("askvol", ">f4"), ("bidvol", ">f4")])


def point(sym):
    return 1e3 if sym.endswith("JPY") else 1e5


def hour_url(sym, hour):
    return f"{BASE_URL}/{sym}/{hour.year}/{hour.month - 1:02d}/{hour.day:02d}/{hour.hour:02d}h_ticks.bi5"


def cache_path(root, sym, hour):
    return Path(root) / sym / f"{hour:%Y}" / f"{hour:%m}" / f"{hour:%d}" / f"{hour.hour:02d}h_ticks.bi5"


def decode(raw, sym, hour):
    """Turn the bytes of one .bi5 file into a DataFrame of quotes."""
    if not raw:
        # Dukascopy returns an empty body for hours with no ticks (weekends)
        return empty_frame()
    rec = np.frombuffer(lzma.decompress(raw), dtype=RECORD)
    start = np.datetime64(hour.replace(tzinfo=None), "ns")
    p = point(sym)
    return pd.DataFrame({
        "time": start + rec["ms"].astype("timedelta64[ms]"),
        "bid": rec["bid"] / p,
        "ask": rec["ask"] / p,
        "bsize": rec["bidvol"].astype(float),
        "asize": rec["askvol"].astype(float),
    })


def empty_frame():
    return pd.DataFrame({"time": np.array([], "datetime64[ns]"), "bid": [], "ask": [],
                         "bsize": [], "asize": []})


def fetch_hour(sym, hour, root, session=None, retries=8):
    """Download one hour into the cache unless it's already there.

    Empty hours are cached as empty files too, otherwise every rerun would
    hit the server again. The server throttles hard (503s and very slow
    connects) if you go at it with many threads, hence the long backoff.
    """
    path = cache_path(root, sym, hour)
    if path.exists():
        return path
    s = session or requests
    for attempt in range(retries):
        try:
            r = s.get(hour_url(sym, hour), timeout=90, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".part")
                tmp.write_bytes(r.content)
                tmp.replace(path)
                return path
            if r.status_code == 404:
                # some holidays come back as 404 rather than an empty file
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")
                return path
        except requests.RequestException:
            pass
        time.sleep(min(60, 2 ** attempt))
    raise RuntimeError(f"could not download {sym} {hour:%Y-%m-%d %H}h")


# The study only looks at 07:00-17:00 UTC (London open to New York lunch),
# and Dukascopy throttles hard enough that a full year of 24h days for five
# pairs takes most of a day to download, so by default only those hours are
# fetched and loaded.
SESSION = (7, 17)


def hours_of(day, session=SESSION):
    """UTC hours of a date to fetch: the session hours on weekdays.

    Spot FX shuts from Friday evening to Sunday evening, so weekends are
    skipped. With session=None it's every hour the market can be open
    (Sunday from 20:00, Friday kept whole to be safe around DST changes).
    """
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    wd = day.weekday()  # Monday = 0
    if session is not None:
        first, last = session if wd < 5 else (0, 0)
    elif wd == 5:
        first, last = 0, 0
    else:
        first, last = (20 if wd == 6 else 0), 24
    return [start + timedelta(hours=h) for h in range(first, last)]


def load_day(sym, day, root, session=SESSION):
    """Cached ticks for one symbol on one UTC date, in time order."""
    frames = [empty_frame()]
    for hour in hours_of(day, session):
        path = cache_path(root, sym, hour)
        if not path.exists():
            raise FileNotFoundError(f"{path} missing, run scripts/download_fx.py first")
        frames.append(decode(path.read_bytes(), sym, hour))
    out = pd.concat(frames, ignore_index=True)
    # the files are already in order but a partition must be sorted on time,
    # so check rather than assume
    assert out["time"].is_monotonic_increasing, f"{sym} {day} ticks out of order"
    return out


def days_between(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def parse_date(s):
    return date.fromisoformat(s)
