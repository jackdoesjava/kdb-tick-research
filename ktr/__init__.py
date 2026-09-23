import os

# Python only ever talks to q over IPC, which is what pykx's unlicensed mode
# is for. Without it, pykx finds the KDB-X licence and tries to embed q in
# the Python process.
os.environ.setdefault("PYKX_UNLICENSED", "true")

# pykx also swaps numpy's memory allocator for one that allocates inside q's
# memory. On this setup (Windows, numpy 2.5, pykx 4.1) that made Python
# segfault whenever a large array was freed, e.g. in the middle of a pandas
# sort in the FX backfill. We never pass arrays to an embedded q, so the
# allocator buys nothing here.
os.environ.setdefault("PYKX_NO_ALLOCATOR", "true")
