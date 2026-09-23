"""Sanity-check rules on the quote stream."""

import pytest

from conftest import CHK, TP, needs_q, quotes, wait_for
from ktr.feed import Feed
from ktr.qproc import QProc, connect

pytestmark = needs_q


@pytest.fixture
def stack():
    with QProc("q/tick.q", TP), QProc("q/checks.q", CHK, ["-tp", TP]):
        yield Feed(TP), connect(CHK)


def rules(chk):
    return chk("exec rule from alerts").py()


def test_clean_quotes_raise_nothing(stack):
    feed, chk = stack
    feed.publish("quote", quotes([f"2025-01-02 10:00:{s:02d}" for s in range(10)]))
    wait_for(lambda: int(chk("count .chk.prev").py()) == 1)
    assert rules(chk) == []
    assert chk("exec ok from tradeable[]").py() == [True]


def test_crossed_and_wide(stack):
    feed, chk = stack
    feed.publish("quote", quotes(["2025-01-02 10:00:00", "2025-01-02 10:00:01", "2025-01-02 10:00:02"],
                                 bid=[1.1000, 1.1002, 1.1000], ask=[1.1001, 1.1001, 1.1010]))
    wait_for(lambda: len(rules(chk)) >= 2)
    assert rules(chk) == ["crossed", "wide"]      # 1.1010-1.1000 is ~9bp, EURUSD limit is 3


def test_jump_across_batches(stack):
    feed, chk = stack
    # the jump is between the last quote of one batch and the first of the
    # next, so it's only caught if the previous mid is carried over
    feed.publish("quote", quotes(["2025-01-02 10:00:00"], bid=1.1000, ask=1.1001))
    feed.publish("quote", quotes(["2025-01-02 10:00:01"], bid=1.1100, ask=1.1101))
    wait_for(lambda: len(rules(chk)) >= 1)
    assert rules(chk) == ["jump"]
    # on hold for 5s of data time, then clear again
    assert chk("exec ok from tradeable[]").py() == [False]
    feed.publish("quote", quotes(["2025-01-02 10:00:07"], bid=1.1100, ask=1.1101))
    wait_for(lambda: chk("exec ok from tradeable[]").py() == [True])


def test_gap_logged_but_no_hold(stack):
    feed, chk = stack
    feed.publish("quote", quotes(["2025-01-02 10:00:00", "2025-01-02 10:05:00"]))
    wait_for(lambda: len(rules(chk)) >= 1)
    assert rules(chk) == ["gap"]
    assert chk("exec val from alerts").py() == [300.0]
    assert chk("exec ok from tradeable[]").py() == [True]


def test_state_reset_at_end_of_day(stack):
    feed, chk = stack
    feed.publish("quote", quotes(["2025-01-03 21:00:00"]))            # Friday
    feed.publish("quote", quotes(["2025-01-05 22:00:00"]))            # Sunday, new date
    wait_for(lambda: int(chk("count .chk.prev").py()) == 1)
    wait_for(lambda: chk("exec lt from .chk.prev").py()[0].day == 5)
    assert rules(chk) == []
