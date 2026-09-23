"""Replay the SPY day through the tick stack into db/.

Brings up tickerplant (logging to logs/tp), RDB and the checks process,
replays 2021-01-28 through the TP in one-minute windows, ends the day and
waits for the RDB to write db/2021.01.28. Alert counts from the checks
process, by hour (UTC) and rule, go to results/checks_spy.csv.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ktr import spy  # noqa: E402
from ktr.feed import Feed  # noqa: E402
from ktr.qproc import QProc, connect, wait_for_day  # noqa: E402

TP, RDB, CHK = 5010, 5011, 5012
RAW = ROOT / "data" / "raw" / "xnas-itch-20210128.mbp-10.dbn.zst"
DAY = "2021-01-28"


def main():
    (ROOT / "logs" / "tp").mkdir(parents=True, exist_ok=True)
    (ROOT / "results").mkdir(exist_ok=True)

    rec = spy.read(RAW)
    tables = {"quote": spy.quotes(rec), "trade": spy.trades(rec)}
    print({k: len(v) for k, v in tables.items()})

    log = ROOT / "logs" / "load_spy.log"
    with QProc("q/tick.q", TP, ["-log", "logs/tp"], log=log), \
         QProc("q/rdb.q", RDB, ["-tp", TP, "-hdb", "db"], log=log), \
         QProc("q/checks.q", CHK, ["-tp", TP], log=log):
        feed = Feed(TP)
        t0 = time.time()
        n = feed.replay_day(tables)
        feed.end_of_day()
        wait_for_day(connect(RDB), ".rdb.saved", DAY)
        secs = time.time() - t0
        print(f"replayed {n:,} rows in {secs:.1f}s ({n / secs:,.0f} rows/s), partition written")

        chk = connect(CHK)
        wait_for_day(chk, ".chk.ended", DAY)
        counts = chk("select n:count i by hour:`hh$time, rule from alerts").pd().reset_index()
        counts.to_csv(ROOT / "results" / "checks_spy.csv", index=False)
        print(chk("select n:count i by rule from alerts").pd())


if __name__ == "__main__":
    main()
