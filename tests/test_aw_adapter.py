"""ActivityWatch adapter tests. No network: a fake AW reproduces the real API's
range semantics (overlap filter, inclusive end, newest-first, ``limit``, and
clipping returned events to the query range, as verified on AW v0.14.2)."""

from __future__ import annotations

import copy
import io
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from computer_history.sources import activitywatch as aw
from computer_history.sources.activitywatch import (
    AFK_SOURCE,
    CURSOR_OVERLAP_SECONDS,
    MAPPING_VERSION,
    STABILITY_MARGIN_SECONDS,
    WEB_SOURCE,
    WINDOW_SOURCE,
    AWClient,
    AWError,
    AWSource,
    IngestOutcome,
    discover_sources,
    extract_domain,
    ingest_all,
    ingest_source,
    project_signal,
    pull_bucket,
)
from computer_history.store import (
    Signal,
    get_cursor,
    get_mapping_version,
    set_mapping_version,
    table_counts,
    to_utc,
    utc_iso,
)

WINDOW_BUCKET = "aw-watcher-window_test-host.local"
AFK_BUCKET = "aw-watcher-afk_test-host.local"
WEB_BUCKET = "aw-watcher-web-chrome_test-host.local"
OLD_WEB_BUCKET = "aw-watcher-web-chrome"

T0 = datetime(2026, 11, 17, 10, 0, 0, 250000, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


# Realistic payloads, shaped like the AW API's responses.
WINDOW_EVENT = {
    "id": 5709,
    "timestamp": "2026-11-17T10:00:00.250000+00:00",
    "duration": 674.067,
    "data": {"app": "T3 Code (Beta)", "title": "computer-history / Milestone 1 Skeleton"},
}
WEB_EVENT = {
    "id": 812,
    "timestamp": "2026-11-17T10:01:00.250000+00:00",
    "duration": 42.5,
    "data": {
        "url": "https://www.github.com/brandon/computer-history/pull/4",
        "title": "  M1   ticket 04 \n · GitHub ",
        "audible": False,
        "incognito": False,
        "tabCount": 7,
    },
}
AFK_EVENT = {
    "id": 77,
    "timestamp": "2026-11-17T10:00:00.250000+00:00",
    "duration": 1800.0,
    "data": {"status": "not-afk"},
}


class FakeAW:
    """In-memory stand-in for the AW API with the real server's query semantics."""

    def __init__(self, buckets: dict[str, str]) -> None:
        self.buckets = {
            bucket_id: {
                "id": bucket_id,
                "type": bucket_type,
                "client": "aw-client-web" if bucket_type == "web.tab.current" else bucket_id,
                "hostname": "test-host.local",
                "data": {},
            }
            for bucket_id, bucket_type in buckets.items()
        }
        self.events: dict[str, list[dict[str, Any]]] = {b: [] for b in buckets}
        self.refetches: list[tuple[str, Any]] = []
        self._next_id = 1

    def add(self, bucket_id: str, start: float, seconds: float, data: dict[str, Any]) -> dict:
        """Add an event starting ``start`` minutes after T0, lasting ``seconds``."""
        raw = {
            "id": self._next_id,
            "timestamp": at(start).isoformat(),
            "duration": seconds,
            "data": data,
        }
        self._next_id += 1
        self.events[bucket_id].append(raw)
        return raw

    def get_buckets(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self.buckets)

    def get_events(
        self,
        bucket_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = -1,
    ) -> list[dict[str, Any]]:
        found = []
        for raw in self.events[bucket_id]:
            event = copy.deepcopy(raw)
            try:
                ts = to_utc(raw["timestamp"])
                te = ts + timedelta(seconds=raw["duration"])
            except (KeyError, ValueError):
                found.append(event)  # malformed: passed through unfiltered
                continue
            if (start is not None and te < start) or (end is not None and ts > end):
                continue
            if start is not None and ts < start:  # AW clips to the query range
                event["timestamp"], ts = start.isoformat(), start
                event["duration"] = (te - ts).total_seconds()
            if end is not None and te > end:
                event["duration"] = (end - ts).total_seconds()
            found.append(event)
        found.sort(key=_sort_key, reverse=True)
        return found if limit < 0 else found[:limit]

    def get_event(self, bucket_id: str, event_id: Any) -> dict[str, Any] | None:
        self.refetches.append((bucket_id, event_id))
        for raw in self.events[bucket_id]:
            if raw["id"] == event_id:
                return copy.deepcopy(raw)
        return None


def _sort_key(event: dict[str, Any]) -> datetime:
    try:
        return to_utc(event["timestamp"])
    except (KeyError, ValueError):
        return datetime.min.replace(tzinfo=UTC)


def counts(outcome: IngestOutcome) -> tuple[int, int]:
    return outcome.inserted, outcome.skipped


def window_aw() -> FakeAW:
    return FakeAW({WINDOW_BUCKET: "currentwindow"})


def rows(conn: sqlite3.Connection, source: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM observations WHERE source = ? ORDER BY started_at, source_id", (source,)
    ).fetchall()


WINDOW = AWSource(WINDOW_SOURCE, (WINDOW_BUCKET,))


# --- discovery ---------------------------------------------------------------


def test_discovery_maps_bucket_types_to_sources() -> None:
    fake = FakeAW(
        {
            WINDOW_BUCKET: "currentwindow",
            AFK_BUCKET: "afkstatus",
            WEB_BUCKET: "web.tab.current",
            OLD_WEB_BUCKET: "web.tab.current",
            "aw-watcher-input_test-host.local": "os.hid.input",
        }
    )
    assert discover_sources(fake) == [
        AWSource(AFK_SOURCE, (AFK_BUCKET,)),
        AWSource(WEB_SOURCE, (OLD_WEB_BUCKET, WEB_BUCKET)),
        AWSource(WINDOW_SOURCE, (WINDOW_BUCKET,)),
    ]


def test_discovery_with_no_known_buckets_is_empty() -> None:
    assert discover_sources(FakeAW({"other": "something.else"})) == []


# --- settled-events rule -----------------------------------------------------


def test_latest_event_is_held_back_older_events_ingested() -> None:
    fake = window_aw()
    first = fake.add(WINDOW_BUCKET, 0, 60, {"app": "A", "title": "a"})
    second = fake.add(WINDOW_BUCKET, 1, 60, {"app": "B", "title": "b"})
    latest = fake.add(WINDOW_BUCKET, 2, 30, {"app": "C", "title": "c"})
    pull = pull_bucket(fake, WINDOW_SOURCE, WINDOW_BUCKET, now=at(2.5) + timedelta(seconds=5))
    assert [o.source_id for o in pull.observations] == [
        f"{WINDOW_BUCKET}/{second['id']}",
        f"{WINDOW_BUCKET}/{first['id']}",
    ]
    assert pull.held_back == 1
    assert pull.frontier == to_utc(latest["timestamp"])


def test_superseded_event_is_settled_even_if_it_just_ended() -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})  # ends at 1:00, superseded
    fake.add(WINDOW_BUCKET, 1, 1, {"app": "B"})
    pull = pull_bucket(fake, WINDOW_SOURCE, WINDOW_BUCKET, now=at(1) + timedelta(seconds=2))
    assert [o.signal.app for o in pull.observations] == ["A"]


@pytest.mark.parametrize(
    ("age_seconds", "settled"),
    [
        (STABILITY_MARGIN_SECONDS + 1, True),
        (STABILITY_MARGIN_SECONDS + 0.001, True),
        (STABILITY_MARGIN_SECONDS, False),  # exactly at the margin: not yet
        (STABILITY_MARGIN_SECONDS - 1, False),
    ],
)
def test_latest_event_settles_once_its_end_is_older_than_the_margin(
    age_seconds: float, settled: bool
) -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    now = at(1) + timedelta(seconds=age_seconds)
    pull = pull_bucket(fake, WINDOW_SOURCE, WINDOW_BUCKET, now=now)
    assert len(pull.observations) == (1 if settled else 0)
    assert pull.held_back == (0 if settled else 1)
    # Nothing held back: the frontier is the pull time; else the held event's start.
    assert pull.frontier == (now if settled else at(0))


def test_event_created_during_the_pull_counts_as_latest() -> None:
    class RacingAW(FakeAW):
        """A new event lands between the 'latest' read and the range query."""

        def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
            result = super().get_events(bucket_id, **kwargs)
            if kwargs.get("limit") == 1:
                self.add(WINDOW_BUCKET, 1, 1, {"app": "New"})
            return result

    fake = RacingAW({WINDOW_BUCKET: "currentwindow"})
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "Old"})
    pull = pull_bucket(fake, WINDOW_SOURCE, WINDOW_BUCKET, now=at(1) + timedelta(seconds=2))
    # "Old" is now superseded (settled); "New" is still growing and must wait.
    assert [o.signal.app for o in pull.observations] == ["Old"]
    assert pull.held_back == 1
    assert pull.frontier == at(1)


# --- normalization -------------------------------------------------------------


def test_window_signal() -> None:
    assert project_signal(WINDOW_SOURCE, WINDOW_EVENT) == Signal(
        app="T3 Code (Beta)", title="computer-history / Milestone 1 Skeleton"
    )


def test_web_signal_domain_title_hygiene_and_extras() -> None:
    signal = project_signal(WEB_SOURCE, WEB_EVENT)
    assert signal is not None
    assert signal.url == "https://www.github.com/brandon/computer-history/pull/4"
    assert signal.domain == "github.com"
    assert signal.title == "M1 ticket 04 · GitHub"
    assert signal.app is None and signal.text is None
    # Leftover data keys, sorted for byte-stable rebuilds, round-trip losslessly.
    assert signal.extras == '{"audible": false, "incognito": false, "tabCount": 7}'
    assert json.loads(signal.extras) == {"audible": False, "incognito": False, "tabCount": 7}


def test_afk_has_no_signal() -> None:
    assert project_signal(AFK_SOURCE, AFK_EVENT) is None


def test_project_signal_accepts_stored_payload_text() -> None:
    assert project_signal(WEB_SOURCE, json.dumps(WEB_EVENT)) == project_signal(
        WEB_SOURCE, WEB_EVENT
    )


def test_project_signal_rejects_unknown_source() -> None:
    with pytest.raises(ValueError):
        project_signal("ax-text", WINDOW_EVENT)


@pytest.mark.parametrize(
    ("url", "domain"),
    [
        ("https://www.github.com/x", "github.com"),
        ("http://WWW.Example.COM:8080/path?q=1", "example.com"),
        ("https://user:pw@docs.google.com/doc", "docs.google.com"),
        ("https://www2.example.com/", "www2.example.com"),
        ("https://example.com./", "example.com"),
        ("https://localhost:3000/", "localhost"),
        ("  https://www.notion.so/page  ", "notion.so"),
        ("chrome://newtab/", None),
        ("file:///Users/brandon/notes.txt", None),
        ("http://[::1", None),  # invalid IPv6 netloc: urlsplit raises
        ("not a url", None),
        ("", None),
        (None, None),
    ],
)
def test_extract_domain(url: str | None, domain: str | None) -> None:
    assert extract_domain(url) == domain


def test_text_hygiene_collapse_cap_and_empty() -> None:
    long_title = "word " * 1000
    payload = {"data": {"app": "  Code\t", "title": long_title}}
    signal = project_signal(WINDOW_SOURCE, payload)
    assert signal.app == "Code"
    assert len(signal.title) == aw.MAX_TEXT_LENGTH
    assert "  " not in signal.title
    assert project_signal(WINDOW_SOURCE, {"data": {"app": "loginwindow", "title": " \n "}}) == (
        Signal(app="loginwindow", title=None)
    )


def test_lone_surrogates_are_scrubbed() -> None:
    signal = project_signal(WINDOW_SOURCE, {"data": {"app": "Chat", "title": "hi \ud83d there"}})
    assert signal.title == "hi ? there"
    signal.title.encode("utf-8")  # storable


def test_non_string_fields_and_unknown_keys_go_to_extras() -> None:
    payload = {"data": {"app": "Code", "title": 42, "zeta": [1], "alpha": {"b": 1, "a": 2}}}
    signal = project_signal(WINDOW_SOURCE, payload)
    assert signal.title is None
    assert signal.extras == '{"alpha": {"a": 2, "b": 1}, "title": 42, "zeta": [1]}'


def test_missing_data_gives_empty_signal() -> None:
    assert project_signal(WINDOW_SOURCE, {"id": 1}) == Signal()
    assert project_signal(WEB_SOURCE, {"data": {"title": "t"}}) == Signal(title="t")


# --- ingest: storage -----------------------------------------------------------


def full_aw() -> FakeAW:
    fake = FakeAW(
        {
            WINDOW_BUCKET: "currentwindow",
            AFK_BUCKET: "afkstatus",
            WEB_BUCKET: "web.tab.current",
            OLD_WEB_BUCKET: "web.tab.current",
        }
    )
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "Code", "title": "a.py"})
    fake.add(WINDOW_BUCKET, 1, 60, {"app": "Google Chrome", "title": "GitHub"})
    fake.add(AFK_BUCKET, 0, 120, {"status": "not-afk"})
    fake.add(AFK_BUCKET, 2, 60, {"status": "afk"})
    fake.add(WEB_BUCKET, 1, 30, {"url": "https://www.github.com/", "title": "GitHub"})
    fake.add(WEB_BUCKET, 1.5, 30, {"url": "https://news.ycombinator.com/", "title": "HN"})
    fake.add(OLD_WEB_BUCKET, 0, 10, {"url": "https://example.com/", "title": "Old"})
    return fake


def test_ingest_all_writes_observations_and_signals(conn: sqlite3.Connection) -> None:
    fake = full_aw()
    results = ingest_all(conn, fake, now=at(30))
    assert results == {
        AFK_SOURCE: IngestOutcome(2, 0, held_back=0, frontier=at(30)),
        WEB_SOURCE: IngestOutcome(3, 0, held_back=0, frontier=at(30)),
        WINDOW_SOURCE: IngestOutcome(2, 0, held_back=0, frontier=at(30)),
    }
    counts = table_counts(conn)
    assert counts["observations"] == 7
    assert counts["signals"] == 5  # AFK -> observations only
    web = conn.execute(
        "SELECT o.source_id, s.domain, s.url, s.title FROM observations o "
        "JOIN signals s ON s.observation_id = o.id WHERE o.source = ? ORDER BY o.started_at",
        (WEB_SOURCE,),
    ).fetchall()
    assert [tuple(r) for r in web] == [
        (f"{OLD_WEB_BUCKET}/7", "example.com", "https://example.com/", "Old"),
        (f"{WEB_BUCKET}/5", "github.com", "https://www.github.com/", "GitHub"),
        (f"{WEB_BUCKET}/6", "news.ycombinator.com", "https://news.ycombinator.com/", "HN"),
    ]
    assert conn.execute("SELECT COUNT(*) FROM signals WHERE source = ?", (AFK_SOURCE,)).fetchone()[
        0
    ] == 0
    assert get_mapping_version(conn) == MAPPING_VERSION


def test_payload_is_stored_verbatim_up_to_json_round_trip(conn: sqlite3.Connection) -> None:
    fake = window_aw()
    fake.events[WINDOW_BUCKET].append(copy.deepcopy(WINDOW_EVENT))
    ingest_source(conn, fake, WINDOW, now=at(60))
    (row,) = rows(conn, WINDOW_SOURCE)
    assert row["payload"] == json.dumps(WINDOW_EVENT)
    assert json.loads(row["payload"]) == WINDOW_EVENT
    assert row["source_id"] == f"{WINDOW_BUCKET}/5709"
    assert row["started_at"] == "2026-11-17T10:00:00.250000Z"
    assert row["ended_at"] == utc_iso(T0 + timedelta(seconds=674.067))


def test_same_event_id_in_two_buckets_are_distinct_rows(conn: sqlite3.Connection) -> None:
    fake = FakeAW({WEB_BUCKET: "web.tab.current", OLD_WEB_BUCKET: "web.tab.current"})
    for bucket in (WEB_BUCKET, OLD_WEB_BUCKET):
        event = copy.deepcopy(WEB_EVENT)
        fake.events[bucket].append(event)
    result = ingest_source(
        conn, fake, AWSource(WEB_SOURCE, (OLD_WEB_BUCKET, WEB_BUCKET)), now=at(60)
    )
    assert counts(result) == (2, 0)


def test_malformed_events_are_skipped_and_negative_duration_clamped(
    conn: sqlite3.Connection,
) -> None:
    fake = window_aw()
    fake.events[WINDOW_BUCKET] += [
        {"id": 900, "duration": 5, "data": {}},  # no timestamp
        {"id": 901, "timestamp": "2026-11-17T10:00:00", "duration": 5, "data": {}},  # naive
        {"timestamp": at(0).isoformat(), "duration": 5, "data": {}},  # no id
        {"id": 902, "timestamp": at(1).isoformat(), "duration": -3.0, "data": {"app": "X"}},
    ]
    fake.add(WINDOW_BUCKET, 2, 10, {"app": "Y"})
    result = ingest_source(conn, fake, WINDOW, now=at(60))
    assert counts(result) == (2, 0)
    clamped = rows(conn, WINDOW_SOURCE)[0]
    assert clamped["started_at"] == clamped["ended_at"]
    assert json.loads(clamped["payload"])["duration"] == -3.0  # raw kept as received


# --- ingest: idempotency and cursors ------------------------------------------


def test_reingesting_the_same_range_adds_nothing(conn: sqlite3.Connection) -> None:
    fake = full_aw()
    sources = discover_sources(fake)

    def ingest_range() -> dict[str, IngestOutcome]:
        return {
            s.name: ingest_source(conn, fake, s, start=at(-5), end=at(10), now=at(30))
            for s in sources
        }

    first = ingest_range()
    before = table_counts(conn)
    second = ingest_range()
    assert sum(r.inserted for r in first.values()) == 7
    assert all(r.inserted == 0 for r in second.values())
    assert {name: r.skipped for name, r in second.items()} == {
        name: r.inserted for name, r in first.items()
    }
    assert table_counts(conn) == before
    # An explicit range never touches the cursor.
    assert get_cursor(conn, WINDOW_SOURCE) is None


def test_repeated_incremental_polls_add_nothing(conn: sqlite3.Connection) -> None:
    fake = full_aw()
    ingest_all(conn, fake, now=at(30))
    before = table_counts(conn)
    again = ingest_all(conn, fake, now=at(31))
    assert all(r.inserted == 0 for r in again.values())
    assert table_counts(conn) == before


def test_cursor_is_start_of_held_event_and_polls_pick_up_new_events(
    conn: sqlite3.Connection,
) -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    fake.add(WINDOW_BUCKET, 1, 60, {"app": "B"})
    growing = fake.add(WINDOW_BUCKET, 2, 30, {"app": "C"})

    now = at(2.5) + timedelta(seconds=1)
    assert ingest_source(conn, fake, WINDOW, now=now) == IngestOutcome(2, 0, 1, at(2))
    assert get_cursor(conn, WINDOW_SOURCE) == utc_iso(at(2))

    # "C" grows in place, then is superseded by "D" (still growing).
    growing["duration"] = 90
    fake.add(WINDOW_BUCKET, 3.5, 20, {"app": "D"})
    now = at(4)
    result = ingest_source(conn, fake, WINDOW, now=now)
    # A and B are re-read through the overlap and skipped; C lands with its final length.
    assert result == IngestOutcome(inserted=1, skipped=2, held_back=1, frontier=at(3.5))
    assert get_cursor(conn, WINDOW_SOURCE) == utc_iso(at(3.5))
    c_row = rows(conn, WINDOW_SOURCE)[-1]
    assert c_row["ended_at"] == utc_iso(at(2) + timedelta(seconds=90))

    # Once D is older than the margin, it settles and the cursor moves to the poll time.
    later = at(3.5) + timedelta(seconds=20 + STABILITY_MARGIN_SECONDS + 1)
    assert ingest_source(conn, fake, WINDOW, now=later).inserted == 1
    assert get_cursor(conn, WINDOW_SOURCE) == utc_iso(later)
    assert len(rows(conn, WINDOW_SOURCE)) == 4


def test_cursor_is_min_over_buckets_and_dead_bucket_does_not_pin_it(
    conn: sqlite3.Connection,
) -> None:
    fake = FakeAW({WEB_BUCKET: "web.tab.current", OLD_WEB_BUCKET: "web.tab.current"})
    fake.add(OLD_WEB_BUCKET, -600, 10, {"url": "https://old.example/"})  # dead for 10h
    fake.add(WEB_BUCKET, 0, 60, {"url": "https://a.example/"})
    fake.add(WEB_BUCKET, 5, 30, {"url": "https://b.example/"})  # current tab
    source = AWSource(WEB_SOURCE, (OLD_WEB_BUCKET, WEB_BUCKET))
    ingest_source(conn, fake, source, now=at(5.5) + timedelta(seconds=1))
    assert get_cursor(conn, WEB_SOURCE) == utc_iso(at(5))
    # Both buckets idle long enough: the cursor reaches the poll time.
    now = at(30)
    ingest_source(conn, fake, source, now=now)
    assert get_cursor(conn, WEB_SOURCE) == utc_iso(now)
    assert len(rows(conn, WEB_SOURCE)) == 3


def test_late_arriving_event_inside_the_overlap_is_picked_up(conn: sqlite3.Connection) -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    now = at(10)
    ingest_source(conn, fake, WINDOW, now=now)
    assert get_cursor(conn, WINDOW_SOURCE) == utc_iso(now)
    # A queued heartbeat reaches AW late, stamped before the cursor.
    fake.add(WINDOW_BUCKET, 9, 30, {"app": "Late"})
    ingest_source(conn, fake, WINDOW, now=at(15))
    assert [json.loads(r["payload"])["data"]["app"] for r in rows(conn, WINDOW_SOURCE)] == [
        "A",
        "Late",
    ]
    assert CURSOR_OVERLAP_SECONDS >= 60


# --- clipping defence ----------------------------------------------------------


def test_event_straddling_the_query_start_is_never_stored_clipped(
    conn: sqlite3.Connection,
) -> None:
    fake = window_aw()
    long_event = fake.add(WINDOW_BUCKET, 0, 3600, {"app": "Long"})  # 10:00-11:00
    fake.add(WINDOW_BUCKET, 60, 10, {"app": "Next"})
    ingest_source(conn, fake, WINDOW, now=at(65))
    fake.add(WINDOW_BUCKET, 61, 10, {"app": "Later"})
    # Both the next poll (cursor - overlap = 55 min) and this explicit range query
    # AW from inside "Long", so AW returns it clipped; neither may store that copy.
    ingest_source(conn, fake, WINDOW, now=at(70))
    ingest_source(conn, fake, WINDOW, start=at(30), end=at(70), now=at(70))
    payloads = [json.loads(r["payload"]) for r in rows(conn, WINDOW_SOURCE)]
    stored = {payload["id"]: payload for payload in payloads}
    assert stored[long_event["id"]] == long_event
    assert len(stored) == 3


def test_range_never_stores_a_start_clipped_first_copy(conn: sqlite3.Connection) -> None:
    fake = window_aw()
    long_event = fake.add(WINDOW_BUCKET, 0, 3600, {"app": "Long"})  # 10:00-11:00
    fake.add(WINDOW_BUCKET, 60, 10, {"app": "Next"})
    # Fresh DB; the range starts inside "Long", which belongs to an earlier range.
    assert ingest_source(conn, fake, WINDOW, start=at(30), end=at(90), now=at(120)).inserted == 1
    assert [json.loads(r["payload"])["data"]["app"] for r in rows(conn, WINDOW_SOURCE)] == [
        "Next"
    ]
    ingest_source(conn, fake, WINDOW, start=at(0), end=at(30), now=at(120))
    assert json.loads(rows(conn, WINDOW_SOURCE)[0]["payload"]) == long_event


def test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent(
    conn: sqlite3.Connection,
) -> None:
    fake = window_aw()
    events = [
        fake.add(WINDOW_BUCKET, 0, 300, {"app": "A"}),  # 0-5 min
        fake.add(WINDOW_BUCKET, 5, 900, {"app": "B"}),  # 5-20 min: straddles 10
        fake.add(WINDOW_BUCKET, 20, 60, {"app": "C"}),
        fake.add(WINDOW_BUCKET, 30, 60, {"app": "D"}),  # starts exactly at a chunk edge
    ]
    fake.add(WINDOW_BUCKET, 100, 5, {"app": "Now"})  # latest; outside the chunks
    now = at(200)
    chunks = [(at(0), at(10)), (at(10), at(30)), (at(30), at(40))]
    results = [ingest_source(conn, fake, WINDOW, start=s, end=e, now=now) for s, e in chunks]
    assert [r.inserted for r in results] == [2, 1, 1]
    assert (WINDOW_BUCKET, events[1]["id"]) in fake.refetches
    payloads = [json.loads(r["payload"]) for r in rows(conn, WINDOW_SOURCE)]
    assert payloads == events  # every event whole, none duplicated across chunk edges
    before = table_counts(conn)
    whole = ingest_source(conn, fake, WINDOW, start=at(0), end=at(40), now=now)
    assert whole == IngestOutcome(0, 4, held_back=0, frontier=at(40))
    assert table_counts(conn) == before


def test_empty_range_is_rejected() -> None:
    with pytest.raises(ValueError):
        pull_bucket(window_aw(), WINDOW_SOURCE, WINDOW_BUCKET, start=at(5), end=at(5))


# --- AWClient (urlopen stubbed; no network) -------------------------------------


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def test_client_builds_read_only_get_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def fake_urlopen(request, timeout):
        seen.append(request)
        return _Response(b"[]")

    monkeypatch.setattr(aw, "urlopen", fake_urlopen)
    client = AWClient("http://aw.test/api/0/")
    assert client.get_events(WEB_BUCKET, start=at(0), end=at(1), limit=-1) == []
    (request,) = seen
    assert request.get_method() == "GET"
    assert request.data is None
    assert request.full_url == (
        "http://aw.test/api/0/buckets/aw-watcher-web-chrome_test-host.local/events?"
        "limit=-1&start=2026-11-17T10%3A00%3A00.250000%2B00%3A00"
        "&end=2026-11-17T10%3A01%3A00.250000%2B00%3A00"
    )


def test_client_maps_404_to_none_and_failures_to_awerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def not_found(request, timeout):
        raise HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(aw, "urlopen", not_found)
    assert AWClient().get_event(WINDOW_BUCKET, 1) is None

    def refused(request, timeout):
        raise URLError(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr(aw, "urlopen", refused)
    with pytest.raises(AWError):
        AWClient().get_buckets()

    monkeypatch.setattr(aw, "urlopen", lambda request, timeout: _Response(b"not json"))
    with pytest.raises(AWError):
        AWClient().get_buckets()


def test_awerror_aborts_the_source_without_writing(conn: sqlite3.Connection) -> None:
    class BrokenAW(FakeAW):
        def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
            if bucket_id == WEB_BUCKET:
                raise AWError("down")
            return super().get_events(bucket_id, **kwargs)

    fake = BrokenAW({OLD_WEB_BUCKET: "web.tab.current", WEB_BUCKET: "web.tab.current"})
    fake.add(OLD_WEB_BUCKET, 0, 10, {"url": "https://example.com/"})
    with pytest.raises(AWError):
        ingest_source(conn, fake, AWSource(WEB_SOURCE, (OLD_WEB_BUCKET, WEB_BUCKET)), now=at(30))
    assert table_counts(conn)["observations"] == 0
    assert get_cursor(conn, WEB_SOURCE) is None


# --- explicit ranges reaching into the stability margin ---------------------------


def test_backfill_chunk_with_growing_event_reports_it_held_back(
    conn: sqlite3.Connection,
) -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    growing = fake.add(WINDOW_BUCKET, 5, 7 * 60, {"app": "Growing"})  # 5 min -> now
    now = at(12)
    # The chunk ends inside the growing event: AW end-clips it, it is re-fetched
    # whole, and it is still too young, so it is held back, not silently dropped.
    outcome = ingest_source(conn, fake, WINDOW, start=at(0), end=at(10), now=now)
    assert outcome == IngestOutcome(inserted=1, skipped=0, held_back=1, frontier=at(5))
    assert (WINDOW_BUCKET, growing["id"]) in fake.refetches
    assert get_cursor(conn, WINDOW_SOURCE) is None  # explicit ranges never move it

    # Re-pulling [frontier, end) once the event has settled completes the chunk.
    later = at(12) + timedelta(seconds=STABILITY_MARGIN_SECONDS + 1)
    resumed = ingest_source(conn, fake, WINDOW, start=outcome.frontier, end=at(10), now=later)
    assert resumed == IngestOutcome(inserted=1, skipped=0, held_back=0, frontier=at(10))
    assert json.loads(rows(conn, WINDOW_SOURCE)[-1]["payload"]) == growing


def test_range_ending_in_the_future_stops_the_frontier_at_now(conn: sqlite3.Connection) -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    now = at(10)
    outcome = ingest_source(conn, fake, WINDOW, start=at(0), end=at(60), now=now)
    # Nothing held back, but [now, end) has not happened yet: frontier = now, not end.
    assert outcome == IngestOutcome(inserted=1, skipped=0, held_back=0, frontier=now)


def test_range_ending_in_the_future_with_a_held_event(conn: sqlite3.Connection) -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    fake.add(WINDOW_BUCKET, 1, 8.5 * 60, {"app": "Current"})  # ends 30s before now
    outcome = ingest_source(conn, fake, WINDOW, start=at(0), end=at(60), now=at(10))
    assert outcome == IngestOutcome(inserted=1, skipped=0, held_back=1, frontier=at(1))
    assert fake.refetches == []  # ends before the query end: never end-clipped


def test_incremental_outcome_reports_held_back_and_cursor(conn: sqlite3.Connection) -> None:
    fake = full_aw()
    fake.add(WINDOW_BUCKET, 25, 4 * 60, {"app": "Current"})  # ends 1 min before now
    outcomes = ingest_all(conn, fake, now=at(30))
    assert outcomes[WINDOW_SOURCE] == IngestOutcome(2, 0, held_back=1, frontier=at(25))
    assert get_cursor(conn, WINDOW_SOURCE) == utc_iso(outcomes[WINDOW_SOURCE].frontier)


def test_source_without_buckets_has_no_frontier(conn: sqlite3.Connection) -> None:
    outcome = ingest_source(conn, window_aw(), AWSource(WEB_SOURCE, ()), now=at(1))
    assert outcome == IngestOutcome(0, 0, held_back=0, frontier=None)
    assert get_cursor(conn, WEB_SOURCE) is None


# --- URL sanitization ----------------------------------------------------------


def test_stored_url_and_domain_come_from_the_same_sanitized_string() -> None:
    raw = " \thttps://www.git\nhub.com/a\tb/\x00c\r\n "
    signal = project_signal(WEB_SOURCE, {"data": {"url": raw}})
    assert signal.url == "https://www.github.com/ab/c"
    assert signal.domain == "github.com"
    assert extract_domain(raw) == "github.com"
    assert project_signal(WEB_SOURCE, {"data": {"url": "\n\t \x7f"}}).url is None


def test_url_is_capped() -> None:
    url = "https://example.com/" + "a" * 10_000
    signal = project_signal(WEB_SOURCE, {"data": {"url": url}})
    assert len(signal.url) == aw.MAX_URL_LENGTH
    assert signal.domain == "example.com"


# --- mapping version ordering ----------------------------------------------------


def test_mapping_version_is_recorded_before_any_signal_exists(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})

    def failing_insert(*args: Any, **kwargs: Any) -> None:
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(aw, "insert_observations", failing_insert)
    with pytest.raises(sqlite3.OperationalError):
        ingest_source(conn, fake, WINDOW, now=at(10))
    # The invariant: a meta row may exist without signals (vacuously true), but
    # signals never exist without a meta row.
    assert get_mapping_version(conn) == MAPPING_VERSION
    assert table_counts(conn)["signals"] == 0


def test_ingest_never_overwrites_a_recorded_mapping_version(conn: sqlite3.Connection) -> None:
    set_mapping_version(conn, MAPPING_VERSION - 1)  # signals built by older code
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    ingest_source(conn, fake, WINDOW, now=at(10))
    assert get_mapping_version(conn) == MAPPING_VERSION - 1  # mismatch stays visible


# --- package surface -------------------------------------------------------------


def test_sources_package_reexports_exactly_the_adapter_api() -> None:
    import computer_history.sources as sources

    assert sources.__all__ == aw.__all__
    for name in aw.__all__:
        assert getattr(sources, name) is getattr(aw, name)
