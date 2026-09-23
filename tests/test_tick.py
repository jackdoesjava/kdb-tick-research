"""Tickerplant + RDB: publishing, end of day, and recovery from the log."""

import pandas as pd
import pytest

from conftest import RDB, TP, needs_q, quotes, wait_for
from ktr.feed import Feed
from ktr.qproc import QProc, connect

pytestmark = needs_q


@pytest.fixture
def dirs(tmp_path):
    (tmp_path / "logs").mkdir()
    return tmp_path


def start_tp(d, log=True):
    args = ["-log", str(d / "logs")] if log else []
    return QProc("q/tick.q", TP, args)


def start_rdb(d):
    return QProc("q/rdb.q", RDB, ["-tp", TP, "-hdb", str(d / "db")])


def count(conn, table):
    return int(conn(f"count {table}").py())


def test_rdb_gets_updates_and_writes_partition(dirs):
    with start_tp(dirs), start_rdb(dirs):
        feed = Feed(TP)
        feed.publish("quote", quotes(["2025-01-02 10:00:00", "2025-01-02 10:00:01"]))
        rdb = connect(RDB)
        wait_for(lambda: count(rdb, "quote") == 2)

        feed.end_of_day()
        wait_for(lambda: str(rdb(".rdb.saved").py()) == "2025-01-02")
        assert count(rdb, "quote") == 0
        # sym should keep its g# after the tables are emptied
        assert str(rdb("attr quote`sym").py()) == "g"

    part = dirs / "db" / "2025.01.02"
    assert (part / "quote").is_dir() and (part / "trade").is_dir()
    assert (dirs / "db" / "sym").exists()


def test_replay_over_several_windows(dirs):
    # later windows are slices whose index doesn't start at 0, which pykx
    # would send as keyed tables if the feed didn't reset the index
    times = pd.date_range("2025-01-02 10:00", periods=300, freq="1s")
    with start_tp(dirs), start_rdb(dirs):
        feed = Feed(TP)
        assert feed.replay_day({"quote": quotes(times)}, window="1min") == 300
        rdb = connect(RDB)
        wait_for(lambda: count(rdb, "quote") == 300)


def test_day_rolls_when_next_date_arrives(dirs):
    with start_tp(dirs), start_rdb(dirs):
        feed = Feed(TP)
        feed.publish("quote", quotes(["2025-01-02 23:59:59"]))
        feed.publish("quote", quotes(["2025-01-03 00:00:01"]))
        rdb = connect(RDB)
        wait_for(lambda: str(rdb(".rdb.saved").py()) == "2025-01-02")
        wait_for(lambda: count(rdb, "quote") == 1)
    assert (dirs / "db" / "2025.01.02" / "quote").is_dir()
    assert not (dirs / "db" / "2025.01.03").exists()


def test_restarted_rdb_recovers_from_log(dirs):
    with start_tp(dirs):
        feed = Feed(TP)
        with start_rdb(dirs):
            feed.publish("quote", quotes(["2025-01-02 10:00:00", "2025-01-02 10:00:01"]))
            rdb = connect(RDB)
            wait_for(lambda: count(rdb, "quote") == 2)
            rdb.close()
        # RDB is down while this arrives, so it only exists in the TP log
        feed.publish("quote", quotes(["2025-01-02 10:00:02"]))

        with start_rdb(dirs):
            rdb = connect(RDB)
            wait_for(lambda: count(rdb, "quote") == 3)
            # and live updates carry on after the replay without duplicates
            feed.publish("quote", quotes(["2025-01-02 10:00:03"]))
            wait_for(lambda: count(rdb, "quote") == 4)
            assert rdb("exec time from quote").py() == sorted(rdb("exec time from quote").py())


def test_bad_batches_rejected_before_logging(dirs):
    with start_tp(dirs) as tp_proc:
        feed = Feed(TP)
        feed.publish("quote", quotes(["2025-01-02 10:00:00"]))
        tp = connect(TP)
        before = int(tp(".u.i").py())

        wrong = quotes(["2025-01-02 10:00:01"]).drop(columns=["bdepth"])
        with pytest.raises(Exception, match="schema"):
            feed.publish("quote", wrong)

        split = quotes(["2025-01-02 23:59:59", "2025-01-03 00:00:01"])
        with pytest.raises(Exception, match="midnight"):
            feed.publish("quote", split)

        older = quotes(["2025-01-01 10:00:00"])
        with pytest.raises(Exception, match="already open"):
            feed.publish("quote", older)

        assert int(tp(".u.i").py()) == before


def test_no_log_mode(dirs):
    with start_tp(dirs, log=False), start_rdb(dirs):
        Feed(TP).publish("quote", quotes(["2025-01-02 10:00:00"]))
        rdb = connect(RDB)
        wait_for(lambda: count(rdb, "quote") == 1)
    assert not any((dirs / "logs").iterdir())
