"""Backfill a date range of Dukascopy FX quotes into db/ through the tick stack.

    python scripts/backfill_fx.py 2025-01-01 2025-12-31

Same TP -> RDB path as the SPY load, but with the TP's log switched off:
for history, the downloaded files already are the recovery path, and a
year of logs would be several GB for nothing. The TP rolls the day itself
when the first quote of the next date arrives. Alert counts from the checks
process go to results/checks_fx.csv.

Dates that already have a partition in db/ are skipped, so if it falls over
partway through the year it can just be run again.
"""

import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ktr import dukascopy as dk  # noqa: E402
from ktr.feed import Feed  # noqa: E402
from ktr.qproc import QProc, connect, wait_for_day  # noqa: E402

TP, RDB, CHK = 5010, 5011, 5012
PAIRS = ["EURUSD", "USDJPY", "EURJPY", "GBPUSD", "EURGBP"]
CACHE = ROOT / "data" / "dukascopy"


def day_quotes(day):
    frames = []
    for sym in PAIRS:
        df = dk.load_day(sym, day, CACHE)
        df.insert(1, "sym", sym)
        frames.append(df)
    q = pd.concat(frames, ignore_index=True)
    q["bdepth"] = float("nan")
    q["adepth"] = float("nan")
    # mergesort is stable, so ticks with the same ms keep their original order
    return q.sort_values("time", kind="mergesort", ignore_index=True)


def main(start, end):
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "results").mkdir(exist_ok=True)
    days = [d for d in dk.days_between(dk.parse_date(start), dk.parse_date(end)) if dk.hours_of(d)]
    have = {p.name for p in (ROOT / "db").glob("20*")}
    days = [d for d in days if f"{d:%Y.%m.%d}" not in have]
    print(f"{len(days)} days to load")
    log = ROOT / "logs" / "backfill_fx.log"
    with QProc("q/tick.q", TP, log=log), \
         QProc("q/rdb.q", RDB, ["-tp", TP, "-hdb", "db"], log=log), \
         QProc("q/checks.q", CHK, ["-tp", TP], log=log):
        feed = Feed(TP)
        t0 = time.time()
        total = 0
        last = None
        for day in days:
            q = day_quotes(day)
            if len(q) == 0:
                continue
            total += feed.replay_day({"quote": q}, window="5min")
            last = day
            print(f"{day} {len(q):>9,} quotes   {total / (time.time() - t0):,.0f} rows/s", flush=True)
        if last is None:
            print("no data in range")
            return
        feed.end_of_day()
        wait_for_day(connect(RDB), ".rdb.saved", last)
        print(f"done: {total:,} quotes in {time.time() - t0:.0f}s")

        chk = connect(CHK)
        wait_for_day(chk, ".chk.ended", last)
        counts = chk("select n:count i by date:`date$time, hour:`hh$time, sym, rule from alerts").pd().reset_index()
        out = ROOT / "results" / "checks_fx.csv"
        # append when resuming; each date is only ever loaded once
        counts.to_csv(out, mode="a", header=not out.exists(), index=False)
        print(chk("select n:count i by sym, rule from alerts").pd())


if __name__ == "__main__":
    main(*sys.argv[1:3])
