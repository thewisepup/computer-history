from __future__ import annotations

import copy
import io
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError

import pytest
from fake_aw import T0, FakeAW, at
from log_records import logged
from projectors import AW

from computer_history.sources import (
    FailureKind,
    IngestOutcome,
    Pull,
    SourceUnavailable,
    StreamFailure,
    poll,
)
from computer_history.sources import activitywatch as aw
from computer_history.sources.activitywatch import (
    AFK_SOURCE,
    RESUME_OVERLAP_SECONDS,
    STABILITY_MARGIN_SECONDS,
    WEB_SOURCE,
    WINDOW_SOURCE,
    ActivityWatch,
    AWClient,
    AWError,
    AWSource,
    discover_sources,
    extract_domain,
    project_signal,
)
from computer_history.sources.activitywatch import client as aw_client
from computer_history.sources.activitywatch.pull import CLIP_GUARD
from computer_history.store import (
    Signal,
    get_progress,
    insert_observations,
    table_counts,
    to_utc,
    utc_iso,
)

WINDOW_BUCKET = "aw-watcher-window_test-host.local"
AFK_BUCKET = "aw-watcher-afk_test-host.local"
WEB_BUCKET = "aw-watcher-web-chrome_test-host.local"
OLD_WEB_BUCKET = "aw-watcher-web-chrome"

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


def counts(outcome: IngestOutcome) -> tuple[int, int]:
    return outcome.inserted, outcome.skipped


def window_aw() -> FakeAW:
    return FakeAW({WINDOW_BUCKET: "currentwindow"})


def pull_window(fake: FakeAW, *, now: datetime) -> Pull:
    return ActivityWatch(fake).pull_after(WINDOW_SOURCE, None, now=now)


def rows(conn: sqlite3.Connection, source: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM observations WHERE source = ? ORDER BY started_at, source_id", (source,)
    ).fetchall()


def poll_aw(conn: sqlite3.Connection, fake: FakeAW, *, now) -> dict[str, IngestOutcome]:
    summary = poll(conn, [ActivityWatch(fake)], now=now)
    assert summary.ok, summary.failures
    return summary.outcomes


def poll_window(conn: sqlite3.Connection, fake: FakeAW, *, now) -> IngestOutcome:
    return poll_aw(conn, fake, now=now)[WINDOW_SOURCE]


def ingest_range(
    conn: sqlite3.Connection, fake: FakeAW, start, end, *, now, stream: str = WINDOW_SOURCE
) -> IngestOutcome:
    pulled = ActivityWatch(fake).pull_range(stream, start, end, now=now)
    written = insert_observations(conn, pulled.observations, project=AW)
    return IngestOutcome(written.inserted, written.skipped, pulled.held_back, pulled.settled_until)


def settled(conn: sqlite3.Connection, source: str):
    progress = get_progress(conn, source)
    return None if progress is None else progress.settled_until


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


def test_latest_event_is_held_back_older_events_ingested() -> None:
    fake = window_aw()
    first = fake.add(WINDOW_BUCKET, 0, 60, {"app": "A", "title": "a"})
    second = fake.add(WINDOW_BUCKET, 1, 60, {"app": "B", "title": "b"})
    latest = fake.add(WINDOW_BUCKET, 2, 30, {"app": "C", "title": "c"})
    pull = pull_window(fake, now=at(2.5) + timedelta(seconds=5))
    assert [o.source_id for o in pull.observations] == [
        f"{WINDOW_BUCKET}/{second['id']}",
        f"{WINDOW_BUCKET}/{first['id']}",
    ]
    assert pull.held_back == 1
    assert pull.settled_until == to_utc(latest["timestamp"])


def test_superseded_event_is_settled_even_if_it_just_ended() -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    fake.add(WINDOW_BUCKET, 1, 1, {"app": "B"})
    pull = pull_window(fake, now=at(1) + timedelta(seconds=2))
    assert [json.loads(o.payload)["data"]["app"] for o in pull.observations] == ["A"]


@pytest.mark.parametrize(
    ("age_seconds", "settled"),
    [
        (STABILITY_MARGIN_SECONDS + 1, True),
        (STABILITY_MARGIN_SECONDS + 0.001, True),
        (STABILITY_MARGIN_SECONDS, False),
        (STABILITY_MARGIN_SECONDS - 1, False),
    ],
)
def test_latest_event_settles_once_its_end_is_older_than_the_margin(
    age_seconds: float, settled: bool
) -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    now = at(1) + timedelta(seconds=age_seconds)
    pull = pull_window(fake, now=now)
    assert len(pull.observations) == (1 if settled else 0)
    assert pull.held_back == (0 if settled else 1)
    assert pull.settled_until == (now if settled else at(0))


def test_event_created_during_the_pull_counts_as_latest() -> None:
    class RacingAW(FakeAW):
        def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
            result = super().get_events(bucket_id, **kwargs)
            if kwargs.get("limit") == 1:
                self.add(WINDOW_BUCKET, 1, 1, {"app": "New"})
            return result

    fake = RacingAW({WINDOW_BUCKET: "currentwindow"})
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "Old"})
    pull = pull_window(fake, now=at(1) + timedelta(seconds=2))
    assert [json.loads(o.payload)["data"]["app"] for o in pull.observations] == ["Old"]
    assert pull.held_back == 1
    assert pull.settled_until == at(1)


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
    assert signal is not None and signal.title is not None
    assert signal.app == "Code"
    assert len(signal.title) == aw.MAX_TEXT_LENGTH
    assert "  " not in signal.title
    assert project_signal(WINDOW_SOURCE, {"data": {"app": "loginwindow", "title": " \n "}}) == (
        Signal(app="loginwindow", title=None)
    )


def test_lone_surrogates_are_scrubbed() -> None:
    signal = project_signal(WINDOW_SOURCE, {"data": {"app": "Chat", "title": "hi \ud83d there"}})
    assert signal is not None and signal.title is not None
    assert signal.title == "hi ? there"
    signal.title.encode("utf-8")


def test_non_string_fields_and_unknown_keys_go_to_extras() -> None:
    payload = {"data": {"app": "Code", "title": 42, "zeta": [1], "alpha": {"b": 1, "a": 2}}}
    signal = project_signal(WINDOW_SOURCE, payload)
    assert signal is not None
    assert signal.title is None
    assert signal.extras == '{"alpha": {"a": 2, "b": 1}, "title": 42, "zeta": [1]}'


def test_missing_data_gives_empty_signal() -> None:
    assert project_signal(WINDOW_SOURCE, {"id": 1}) == Signal()
    assert project_signal(WEB_SOURCE, {"data": {"title": "t"}}) == Signal(title="t")


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


def test_poll_writes_observations_and_signals(conn: sqlite3.Connection) -> None:
    fake = full_aw()
    results = poll_aw(conn, fake, now=at(30))
    assert results == {
        AFK_SOURCE: IngestOutcome(2, 0, held_back=0, settled_until=at(30)),
        WEB_SOURCE: IngestOutcome(3, 0, held_back=0, settled_until=at(30)),
        WINDOW_SOURCE: IngestOutcome(2, 0, held_back=0, settled_until=at(30)),
    }
    counts = table_counts(conn)
    assert counts["observations"] == 7
    assert counts["signals"] == 5
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
    assert (
        conn.execute("SELECT COUNT(*) FROM signals WHERE source = ?", (AFK_SOURCE,)).fetchone()[0]
        == 0
    )


def test_payload_is_stored_verbatim_up_to_json_round_trip(conn: sqlite3.Connection) -> None:
    fake = window_aw()
    fake.events[WINDOW_BUCKET].append(copy.deepcopy(WINDOW_EVENT))
    poll_window(conn, fake, now=at(60))
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
    result = poll_aw(conn, fake, now=at(60))[WEB_SOURCE]
    assert counts(result) == (2, 0)


def test_malformed_events_are_skipped_and_negative_duration_clamped(
    conn: sqlite3.Connection,
) -> None:
    fake = window_aw()
    fake.events[WINDOW_BUCKET] += [
        {"id": 900, "duration": 5, "data": {}},
        {"id": 901, "timestamp": "2026-11-17T10:00:00", "duration": 5, "data": {}},
        {"timestamp": at(0).isoformat(), "duration": 5, "data": {}},
        {"id": 902, "timestamp": at(1).isoformat(), "duration": -3.0, "data": {"app": "X"}},
    ]
    fake.add(WINDOW_BUCKET, 2, 10, {"app": "Y"})
    result = poll_window(conn, fake, now=at(60))
    assert counts(result) == (2, 0)
    clamped = rows(conn, WINDOW_SOURCE)[0]
    assert clamped["started_at"] == clamped["ended_at"]
    assert json.loads(clamped["payload"])["duration"] == -3.0


def test_reingesting_the_same_range_adds_nothing(conn: sqlite3.Connection) -> None:
    fake = full_aw()
    sources = discover_sources(fake)

    def ingest_every_stream() -> dict[str, IngestOutcome]:
        return {
            s.name: ingest_range(conn, fake, at(-5), at(10), now=at(30), stream=s.name)
            for s in sources
        }

    first = ingest_every_stream()
    before = table_counts(conn)
    second = ingest_every_stream()
    assert sum(r.inserted for r in first.values()) == 7
    assert all(r.inserted == 0 for r in second.values())
    assert {name: r.skipped for name, r in second.items()} == {
        name: r.inserted for name, r in first.items()
    }
    assert table_counts(conn) == before
    assert get_progress(conn, WINDOW_SOURCE) is None


def test_repeated_incremental_polls_add_nothing(conn: sqlite3.Connection) -> None:
    fake = full_aw()
    poll_aw(conn, fake, now=at(30))
    before = table_counts(conn)
    again = poll_aw(conn, fake, now=at(31))
    assert all(r.inserted == 0 for r in again.values())
    assert table_counts(conn) == before


def test_progress_settles_at_held_event_and_polls_pick_up_new_events(
    conn: sqlite3.Connection,
) -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    fake.add(WINDOW_BUCKET, 1, 60, {"app": "B"})
    growing = fake.add(WINDOW_BUCKET, 2, 30, {"app": "C"})

    now = at(2.5) + timedelta(seconds=1)
    assert poll_window(conn, fake, now=now) == IngestOutcome(2, 0, 1, at(2))
    assert settled(conn, WINDOW_SOURCE) == at(2)

    growing["duration"] = 90
    fake.add(WINDOW_BUCKET, 3.5, 20, {"app": "D"})
    now = at(4)
    result = poll_window(conn, fake, now=now)
    assert result == IngestOutcome(inserted=1, skipped=2, held_back=1, settled_until=at(3.5))
    assert settled(conn, WINDOW_SOURCE) == at(3.5)
    c_row = rows(conn, WINDOW_SOURCE)[-1]
    assert c_row["ended_at"] == utc_iso(at(2) + timedelta(seconds=90))

    later = at(3.5) + timedelta(seconds=20 + STABILITY_MARGIN_SECONDS + 1)
    assert poll_window(conn, fake, now=later).inserted == 1
    assert settled(conn, WINDOW_SOURCE) == later
    assert len(rows(conn, WINDOW_SOURCE)) == 4


def test_progress_is_min_over_buckets_and_dead_bucket_does_not_pin_it(
    conn: sqlite3.Connection,
) -> None:
    fake = FakeAW({WEB_BUCKET: "web.tab.current", OLD_WEB_BUCKET: "web.tab.current"})
    fake.add(OLD_WEB_BUCKET, -600, 10, {"url": "https://old.example/"})
    fake.add(WEB_BUCKET, 0, 60, {"url": "https://a.example/"})
    fake.add(WEB_BUCKET, 5, 30, {"url": "https://b.example/"})
    poll_aw(conn, fake, now=at(5.5) + timedelta(seconds=1))
    assert settled(conn, WEB_SOURCE) == at(5)
    now = at(30)
    poll_aw(conn, fake, now=now)
    assert settled(conn, WEB_SOURCE) == now
    assert len(rows(conn, WEB_SOURCE)) == 3


def test_late_arriving_event_inside_the_overlap_is_picked_up(conn: sqlite3.Connection) -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    now = at(10)
    poll_window(conn, fake, now=now)
    assert settled(conn, WINDOW_SOURCE) == now
    fake.add(WINDOW_BUCKET, 9, 30, {"app": "Late"})
    poll_window(conn, fake, now=at(15))
    assert [json.loads(r["payload"])["data"]["app"] for r in rows(conn, WINDOW_SOURCE)] == [
        "A",
        "Late",
    ]
    assert RESUME_OVERLAP_SECONDS >= 60


def test_event_written_late_reaching_back_past_the_resume_start_is_stored(
    conn: sqlite3.Connection,
) -> None:
    fake = FakeAW({AFK_BUCKET: "afkstatus"})
    fake.add(AFK_BUCKET, 0, 1, {"status": "not-afk"})
    poll_aw(conn, fake, now=at(11))
    woke_up_idle = fake.add(AFK_BUCKET, 0.02, 11 * 60, {"status": "afk"})
    poll_aw(conn, fake, now=at(60))
    stored = [json.loads(r["payload"]) for r in rows(conn, AFK_SOURCE)]
    assert stored[-1] == woke_up_idle
    assert len(stored) == 2


def test_event_straddling_the_query_start_is_never_stored_clipped(
    conn: sqlite3.Connection,
) -> None:
    fake = window_aw()
    long_event = fake.add(WINDOW_BUCKET, 0, 3600, {"app": "Long"})
    fake.add(WINDOW_BUCKET, 60, 10, {"app": "Next"})
    poll_window(conn, fake, now=at(65))
    fake.add(WINDOW_BUCKET, 61, 10, {"app": "Later"})
    poll_window(conn, fake, now=at(70))
    ingest_range(conn, fake, at(30), at(70), now=at(70))
    payloads = [json.loads(r["payload"]) for r in rows(conn, WINDOW_SOURCE)]
    stored = {payload["id"]: payload for payload in payloads}
    assert stored[long_event["id"]] == long_event
    assert len(stored) == 3


def test_range_never_stores_a_start_clipped_first_copy(conn: sqlite3.Connection) -> None:
    fake = window_aw()
    long_event = fake.add(WINDOW_BUCKET, 0, 3600, {"app": "Long"})
    fake.add(WINDOW_BUCKET, 60, 10, {"app": "Next"})
    assert ingest_range(conn, fake, at(30), at(90), now=at(120)).inserted == 1
    assert [json.loads(r["payload"])["data"]["app"] for r in rows(conn, WINDOW_SOURCE)] == ["Next"]
    ingest_range(conn, fake, at(0), at(30), now=at(120))
    assert json.loads(rows(conn, WINDOW_SOURCE)[0]["payload"]) == long_event


def test_chunked_backfill_refetches_end_clipped_events_and_is_idempotent(
    conn: sqlite3.Connection,
) -> None:
    fake = window_aw()
    events = [
        fake.add(WINDOW_BUCKET, 0, 300, {"app": "A"}),
        fake.add(WINDOW_BUCKET, 5, 900, {"app": "B"}),
        fake.add(WINDOW_BUCKET, 20, 60, {"app": "C"}),
        fake.add(WINDOW_BUCKET, 30, 60, {"app": "D"}),
    ]
    fake.add(WINDOW_BUCKET, 100, 5, {"app": "Now"})
    now = at(200)
    chunks = [(at(0), at(10)), (at(10), at(30)), (at(30), at(40))]
    results = [ingest_range(conn, fake, s, e, now=now) for s, e in chunks]
    assert [r.inserted for r in results] == [2, 1, 1]
    assert (WINDOW_BUCKET, events[1]["id"]) in fake.refetches
    payloads = [json.loads(r["payload"]) for r in rows(conn, WINDOW_SOURCE)]
    assert payloads == events
    before = table_counts(conn)
    whole = ingest_range(conn, fake, at(0), at(40), now=now)
    assert whole == IngestOutcome(0, 4, held_back=0, settled_until=at(40))
    assert table_counts(conn) == before


def test_empty_range_is_rejected() -> None:
    with pytest.raises(ValueError):
        ActivityWatch(window_aw()).pull_range(WINDOW_SOURCE, at(5), at(5), now=at(10))


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

    monkeypatch.setattr(aw_client, "urlopen", fake_urlopen)
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
        raise HTTPError(request.full_url, 404, "Not Found", Message(), None)

    monkeypatch.setattr(aw_client, "urlopen", not_found)
    assert AWClient().get_event(WINDOW_BUCKET, 1) is None

    def refused(request, timeout):
        raise URLError(ConnectionRefusedError(61, "Connection refused"))

    monkeypatch.setattr(aw_client, "urlopen", refused)
    with pytest.raises(AWError):
        AWClient().get_buckets()

    monkeypatch.setattr(aw_client, "urlopen", lambda request, timeout: _Response(b"not json"))
    with pytest.raises(AWError):
        AWClient().get_buckets()


def test_awerror_fails_the_stream_without_writing(conn: sqlite3.Connection) -> None:
    class BrokenAW(FakeAW):
        def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
            if bucket_id == WEB_BUCKET:
                raise AWError("down")
            return super().get_events(bucket_id, **kwargs)

    fake = BrokenAW({OLD_WEB_BUCKET: "web.tab.current", WEB_BUCKET: "web.tab.current"})
    fake.add(OLD_WEB_BUCKET, 0, 10, {"url": "https://example.com/"})
    summary = poll(conn, [ActivityWatch(fake)], now=at(30))
    assert summary.failures == (StreamFailure(WEB_SOURCE, "down", FailureKind.SOURCE),)
    assert table_counts(conn)["observations"] == 0
    assert get_progress(conn, WEB_SOURCE) is None


def test_backfill_chunk_with_growing_event_reports_it_held_back(
    conn: sqlite3.Connection,
) -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    growing = fake.add(WINDOW_BUCKET, 5, 7 * 60, {"app": "Growing"})
    now = at(12)
    outcome = ingest_range(conn, fake, at(0), at(10), now=now)
    assert outcome == IngestOutcome(inserted=1, skipped=0, held_back=1, settled_until=at(5))
    assert (WINDOW_BUCKET, growing["id"]) in fake.refetches
    assert get_progress(conn, WINDOW_SOURCE) is None

    later = at(12) + timedelta(seconds=STABILITY_MARGIN_SECONDS + 1)
    resumed = ingest_range(conn, fake, outcome.settled_until, at(10), now=later)
    assert resumed == IngestOutcome(inserted=1, skipped=0, held_back=0, settled_until=at(10))
    assert json.loads(rows(conn, WINDOW_SOURCE)[-1]["payload"]) == growing


def test_range_ending_in_the_future_stops_the_frontier_at_now(conn: sqlite3.Connection) -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    now = at(10)
    outcome = ingest_range(conn, fake, at(0), at(60), now=now)
    assert outcome == IngestOutcome(inserted=1, skipped=0, held_back=0, settled_until=now)


def test_range_ending_in_the_future_with_a_held_event(conn: sqlite3.Connection) -> None:
    fake = window_aw()
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "A"})
    fake.add(WINDOW_BUCKET, 1, 8.5 * 60, {"app": "Current"})
    outcome = ingest_range(conn, fake, at(0), at(60), now=at(10))
    assert outcome == IngestOutcome(inserted=1, skipped=0, held_back=1, settled_until=at(1))
    assert fake.refetches == []


def test_incremental_outcome_reports_held_back_and_progress(conn: sqlite3.Connection) -> None:
    fake = full_aw()
    fake.add(WINDOW_BUCKET, 25, 4 * 60, {"app": "Current"})
    outcomes = poll_aw(conn, fake, now=at(30))
    assert outcomes[WINDOW_SOURCE] == IngestOutcome(2, 0, held_back=1, settled_until=at(25))
    assert settled(conn, WINDOW_SOURCE) == outcomes[WINDOW_SOURCE].settled_until


def test_adapter_reports_a_stream_without_buckets_as_unavailable() -> None:
    adapter = ActivityWatch(window_aw())
    assert adapter.streams() == [WINDOW_SOURCE]
    with pytest.raises(AWError, match="no buckets for 'aw-web'"):
        adapter.pull_after(WEB_SOURCE, None, now=at(1))
    assert issubclass(AWError, SourceUnavailable)


def test_adapter_resumes_a_little_before_its_position() -> None:
    class RecordingAW(FakeAW):
        starts: list = []

        def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
            if kwargs.get("limit") == -1:
                self.starts.append(kwargs.get("start"))
            return super().get_events(bucket_id, **kwargs)

    fake = RecordingAW({WINDOW_BUCKET: "currentwindow"})
    adapter = ActivityWatch(fake)
    first = adapter.pull_after(WINDOW_SOURCE, None, now=at(30))
    assert first.settled_until == at(30) and first.position is not None
    fake.starts = []
    pulled = adapter.pull_after(WINDOW_SOURCE, first.position, now=at(40))
    overlap = timedelta(seconds=RESUME_OVERLAP_SECONDS)
    assert fake.starts == [at(30) - overlap - CLIP_GUARD]
    assert pulled.settled_until == at(40) and pulled.position not in (None, first.position)


def test_stored_url_and_domain_come_from_the_same_sanitized_string() -> None:
    raw = " \thttps://www.git\nhub.com/a\tb/\x00c\r\n "
    signal = project_signal(WEB_SOURCE, {"data": {"url": raw}})
    assert signal is not None
    assert signal.url == "https://www.github.com/ab/c"
    assert signal.domain == "github.com"
    assert extract_domain(raw) == "github.com"
    blank = project_signal(WEB_SOURCE, {"data": {"url": "\n\t \x7f"}})
    assert blank is not None
    assert blank.url is None


def test_url_is_capped() -> None:
    url = "https://example.com/" + "a" * 10_000
    signal = project_signal(WEB_SOURCE, {"data": {"url": url}})
    assert signal is not None and signal.url is not None
    assert len(signal.url) == aw.MAX_URL_LENGTH
    assert signal.domain == "example.com"


def test_sources_package_reexports_exactly_the_runner_and_adapter_api() -> None:
    import computer_history.sources as sources
    from computer_history.sources import (
        agent_health,
        backfill,
        capture_spool,
        commit,
        contract,
        cycle_report,
        ingest_health,
        projection,
        runner,
    )

    modules = (
        contract,
        commit,
        projection,
        runner,
        ingest_health,
        cycle_report,
        backfill,
        aw,
        capture_spool,
        agent_health,
    )
    names = [name for module in modules for name in module.__all__]
    assert sorted(sources.__all__) == sorted(names)
    assert len(set(sources.__all__)) == len(sources.__all__)
    for module in modules:
        for name in module.__all__:
            assert getattr(sources, name) is getattr(module, name)


@pytest.mark.parametrize(
    ("raw_id", "logged_id"),
    [(7, 7), ("short-id", "short-id"), ("x" * 500, None), ([1, 2], None)],
    ids=["int", "short-str", "long-str", "list"],
)
def test_a_malformed_event_warns_with_its_error_type_and_only_a_short_id(
    caplog: pytest.LogCaptureFixture, raw_id: object, logged_id: object
) -> None:
    caplog.set_level(logging.DEBUG)
    fake = FakeAW({WINDOW_BUCKET: "currentwindow"})
    fake.events[WINDOW_BUCKET].append({"id": raw_id, "timestamp": "never", "data": {}})

    pulled = pull_window(fake, now=at(30))

    assert pulled.observations == ()
    warnings = logged(caplog, "malformed event skipped")
    assert warnings and all(
        (w["event_id"], w["error"], w["levelno"]) == (logged_id, "ValueError", logging.WARNING)
        for w in warnings
    )
    details = logged(caplog, "malformed event detail")
    assert details and all(
        d["levelno"] == logging.DEBUG and d["raw_id"] == repr(raw_id) for d in details
    )
