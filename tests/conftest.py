import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ktr import qproc  # noqa: E402


def _q_works():
    try:
        exe = qproc.find_q()
        r = subprocess.run([exe, "-q"], input=b"-1 string 6*7;exit 0\n",
                           capture_output=True, timeout=30)
        return b"42" in r.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


HAVE_Q = _q_works()
needs_q = pytest.mark.skipif(not HAVE_Q, reason="needs a licensed q")

# well away from the ports the scripts use, so tests can run alongside them
TP, RDB, CHK, HDB = 15010, 15011, 15012, 15014


def quotes(times, sym="EURUSD", bid=1.1000, ask=1.1001):
    n = len(times)
    return pd.DataFrame({
        "time": pd.to_datetime(times),
        "sym": [sym] * n,
        "bid": [bid] * n if not hasattr(bid, "__len__") else list(bid),
        "ask": [ask] * n if not hasattr(ask, "__len__") else list(ask),
        "bsize": [1.0] * n,
        "asize": [1.0] * n,
        "bdepth": [float("nan")] * n,
        "adepth": [float("nan")] * n,
    })


def wait_for(fn, timeout=20):
    t0 = time.time()
    while not fn():
        if time.time() - t0 > timeout:
            raise TimeoutError
        time.sleep(0.05)
