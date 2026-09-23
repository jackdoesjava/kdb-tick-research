# kdb-tick-research

A small kdb+ tick stack (tickerplant, RDB, date-partitioned HDB) with two
studies on top: how fast FX crosses like EUR/JPY reprice off their legs, and
what the Nasdaq order book said about short-term moves in SPY on 28 Jan 2021.

Work in progress. The tick stack, the tests and the SPY study are done
(results in `results/spy_study.md`). The FX study is written and tested on a
few days; the full year of 2025 is still being loaded.

## Layout

```
q/schema.q      quote and trade tables, one schema for equities and FX
q/tick.q        tickerplant (cut down from kdb+tick)
q/rdb.q         real-time database: replays the TP log on startup, writes the HDB at end of day
q/checks.q      sanity checks on the quote stream (crossed, wide, jumps, gaps) with a per-symbol hold
q/analytics.q   research queries that run inside the HDB
q/hdb.q         HDB with analytics.q loaded
ktr/            Python: data readers, feed handler, q process helper, block bootstrap
scripts/        download, load, backfill and the two studies
tests/          pytest; the q tests start real q processes
results/        tables and figures
```

## Setup

1. KDB-X Community Edition (free): get a licence at
   https://developer.kx.com/products/kdb-x/install, put `q.exe` in
   `~/kx/w64/` and the licence as `~/kx/kc.lic`. Set `QHOME` or `QEXE` if
   you put it somewhere else.
2. `python -m venv .venv`, then `pip install -r requirements.txt`.
3. `python -m pytest` (the q tests skip themselves if q isn't found).

Market data isn't in the repo because of the licences:

* SPY: Databento `XNAS.ITCH`, schema `mbp-10`, 2021-01-28, saved as
  `data/raw/xnas-itch-20210128.mbp-10.dbn.zst`.
* FX: `python scripts/download_fx.py 2025-01-01 2025-12-31` fetches
  Dukascopy ticks for the 07:00-17:00 UTC session. It's slow (a few hours)
  because the server throttles.

Then:

```
python scripts/load_spy.py                          # SPY day -> db/2021.01.28
python scripts/backfill_fx.py 2025-01-01 2025-12-31 # FX year -> db/
python scripts/spy_study.py
python scripts/fx_study.py
```
