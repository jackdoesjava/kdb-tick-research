"""Download Dukascopy ticks for the FX study into data/dukascopy.

    python scripts/download_fx.py 2025-01-01 2025-12-31 [threads]

Only the 07:00-17:00 UTC session is fetched (see dukascopy.SESSION), which
is about 13k files for five pairs over a year. Individual requests are slow
(often 15-30s) and the server starts returning 503s if pushed with more than
a few threads, so expect a few hours. The cache makes it safe to stop and
rerun.
"""

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ktr import dukascopy as dk  # noqa: E402

# two triangles: EURJPY = EURUSD * USDJPY and EURGBP = EURUSD / GBPUSD
PAIRS = ["EURUSD", "USDJPY", "EURJPY", "GBPUSD", "EURGBP"]
ROOT = Path(__file__).resolve().parents[1] / "data" / "dukascopy"


def main(start, end, workers=3):
    jobs = [(sym, h) for sym in PAIRS
            for d in dk.days_between(dk.parse_date(start), dk.parse_date(end))
            for h in dk.hours_of(d)]
    todo = [(s, h) for s, h in jobs if not dk.cache_path(ROOT, s, h).exists()]
    print(f"{len(jobs)} hours in range, {len(todo)} still to fetch")

    session = requests.Session()
    done = failed = 0
    with ThreadPoolExecutor(workers) as pool:
        futures = [pool.submit(dk.fetch_hour, s, h, ROOT, session) for s, h in todo]
        for f in as_completed(futures):
            try:
                f.result()
            except RuntimeError as e:
                # keep going, a rerun picks up whatever is missing
                failed += 1
                print(f"  {e}", flush=True)
            done += 1
            if done % 1000 == 0:
                print(f"  {done}/{len(todo)}", flush=True)
    print(f"done, {failed} failed" + (" (run again to retry them)" if failed else ""))


if __name__ == "__main__":
    start, end = sys.argv[1:3]
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    main(start, end, workers)
