"""Over random days at the Mac, polling stores every ActivityWatch event, unchanged."""

from __future__ import annotations

import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from aw_watchers import (
    AFK_BUCKET,
    WINDOW_BUCKET,
    Day,
    HeartbeatAW,
    Stretch,
    bucket_events,
    live_through,
    stored_events,
)
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from computer_history.sources import AFK_SOURCE, WINDOW_SOURCE, ActivityWatch, poll
from computer_history.store import connect

seconds = st.one_of(st.integers(1, 30), st.integers(100, 240), st.integers(1, 900))
stretches = st.builds(
    Stretch,
    kind=st.sampled_from(["active", "idle", "asleep"]),
    seconds=seconds,
    app=st.sampled_from(["Code", "Chrome"]),
)
days = st.builds(
    Day,
    stretches=st.lists(stretches, min_size=1, max_size=8).map(tuple),
    poll_phase=st.integers(0, 59),
    afk_phase=st.integers(0, 4),
    extra_polls=st.lists(st.integers(0, 3600), max_size=3).map(tuple),
)

checked = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@contextmanager
def ingest(day: Day) -> Iterator[tuple[HeartbeatAW, sqlite3.Connection]]:
    """Live through the day with ingest polling into a fresh store."""
    with tempfile.TemporaryDirectory() as folder:
        aw = HeartbeatAW()
        conn = connect(Path(folder) / "history.db")
        try:
            source = ActivityWatch(aw)
            live_through(day, aw, lambda now: poll(conn, [source], now=now))
            yield aw, conn
        finally:
            conn.close()


def missing_and_cut_off(
    aw: HeartbeatAW, conn: sqlite3.Connection, stream: str, bucket_id: str
) -> tuple[set[str], dict[str, tuple]]:
    """The events never stored, and the stored ones that differ from what ActivityWatch holds."""
    held, stored = bucket_events(aw, bucket_id), stored_events(conn, stream)
    missing = set(held) - set(stored)
    cut_off = {i: (stored[i], held[i]) for i in stored.keys() & held.keys() if stored[i] != held[i]}
    return missing, cut_off


@checked
@given(days)
def test_every_window_event_is_stored_whole(day: Day) -> None:
    with ingest(day) as (aw, conn):
        missing, cut_off = missing_and_cut_off(aw, conn, WINDOW_SOURCE, WINDOW_BUCKET)
    assert not missing
    assert not cut_off


A_PAUSE_OF_TWO_AND_A_HALF_MINUTES = Day(
    (Stretch("active", 600, "Code"), Stretch("idle", 150, "Code"), Stretch("active", 3600, "Code")),
    poll_phase=0,
    afk_phase=0,
)


@pytest.mark.xfail(
    strict=True,
    reason="a not-afk event settles after 120s but aw-watcher-afk can still extend it for 185s",
)
@checked
@example(A_PAUSE_OF_TWO_AND_A_HALF_MINUTES)
@given(days)
def test_every_afk_event_is_stored_whole(day: Day) -> None:
    with ingest(day) as (aw, conn):
        _, cut_off = missing_and_cut_off(aw, conn, AFK_SOURCE, AFK_BUCKET)
    assert not cut_off
