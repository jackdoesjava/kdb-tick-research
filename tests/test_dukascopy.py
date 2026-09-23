import lzma
import struct
from datetime import date, datetime, timezone

import numpy as np

from ktr import dukascopy as dk


def fake_bi5(rows):
    raw = b"".join(struct.pack(">IIIff", *r) for r in rows)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


def test_decode_prices_and_times():
    hour = datetime(2025, 3, 12, 13, tzinfo=timezone.utc)
    raw = fake_bi5([(38, 108784, 108780, 1.8, 0.12), (1500, 108790, 108786, 1.0, 2.0)])
    df = dk.decode(raw, "EURUSD", hour)
    assert list(df.columns) == ["time", "bid", "ask", "bsize", "asize"]
    assert df["time"].iloc[0] == np.datetime64("2025-03-12T13:00:00.038")
    assert df["time"].iloc[1] == np.datetime64("2025-03-12T13:00:01.500")
    assert np.isclose(df["bid"].iloc[0], 1.08780)
    assert np.isclose(df["ask"].iloc[0], 1.08784)
    # ask volume is the 4th field, bid volume the 5th
    assert np.isclose(df["asize"].iloc[0], 1.8)
    assert np.isclose(df["bsize"].iloc[0], 0.12, atol=1e-6)


def test_jpy_pairs_use_three_decimals():
    hour = datetime(2025, 3, 12, 13, tzinfo=timezone.utc)
    df = dk.decode(fake_bi5([(0, 162234, 162220, 1.2, 1.2)]), "EURJPY", hour)
    assert np.isclose(df["bid"].iloc[0], 162.220)
    assert np.isclose(df["ask"].iloc[0], 162.234)


def test_empty_hour():
    hour = datetime(2025, 3, 15, 13, tzinfo=timezone.utc)
    df = dk.decode(b"", "EURUSD", hour)
    assert len(df) == 0
    assert df["time"].dtype == "datetime64[ns]"


def test_month_in_url_is_zero_based():
    hour = datetime(2025, 1, 2, 7, tzinfo=timezone.utc)
    assert dk.hour_url("EURUSD", hour).endswith("/EURUSD/2025/00/02/07h_ticks.bi5")


def test_weekend_hours_skipped():
    assert dk.hours_of(date(2025, 3, 15)) == []            # Saturday
    sunday = dk.hours_of(date(2025, 3, 16))
    assert [h.hour for h in sunday] == [20, 21, 22, 23]
    assert len(dk.hours_of(date(2025, 3, 14))) == 24        # Friday kept whole
