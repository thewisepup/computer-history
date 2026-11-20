from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from db_states import corrupt_payloads
from fake_aw import FakeAW
from fake_source import FakeSource, at
from projectors import no_signal

from computer_history import cli
from computer_history.cli import ingest as cli_ingest
from computer_history.sources import (
    AFK_SOURCE,
    KNOWN_SOURCES,
    WEB_SOURCE,
    WINDOW_SOURCE,
    ActivityWatch,
    FailureKind,
    StreamFailure,
    plan_backfill,
    poll,
    projector_for,
    reproject_signals,
    run_backfill,
    watch,
)
from computer_history.store import (
    Observation,
    RebuildAborted,
    Signal,
    UnclaimedSource,
    connect,
    get_progress,
    insert_observations,
    transaction,
)

WINDOW_BUCKET = "aw-watcher-window_test-host.local"
AFK_BUCKET = "aw-watcher-afk_test-host.local"
WEB_BUCKET = "aw-watcher-web-chrome_test-host.local"


def full_aw(now: datetime) -> ActivityWatch:
    fake = FakeAW(
        {WINDOW_BUCKET: "currentwindow", AFK_BUCKET: "afkstatus", WEB_BUCKET: "web.tab.current"},
        t0=now - timedelta(hours=1),
    )
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "Code", "title": "  a.py\t— repo  "})
    fake.add(WINDOW_BUCKET, 1, 60, {"app": "Chrome", "title": "GitHub", "extra": 3})
    fake.add(AFK_BUCKET, 0, 120, {"status": "not-afk"})
    fake.add(WEB_BUCKET, 1, 30, {"url": "https://www.github.com/x", "title": "GitHub", "n": 4})
    fake.add(WEB_BUCKET, 2, 30, {"url": "chrome://newtab/", "title": "New Tab"})
    return ActivityWatch(fake)


def signal_rows(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return [tuple(r) for r in conn.execute("SELECT * FROM signals ORDER BY observation_id")]


def wipe_signals(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        conn.execute("DELETE FROM signals")


def stored_sources(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT source FROM observations ORDER BY source")
    return [row[0] for row in rows]


def unclaimed_capture(conn: sqlite3.Connection) -> None:
    capture = Observation("transcript", "spool/1", at(0), at(1), '{"text": "hello"}')
    insert_observations(conn, [capture], project=no_signal)


def test_known_sources_project_every_activitywatch_stream() -> None:
    project = projector_for(KNOWN_SOURCES)
    payload = json.dumps({"data": {"app": "Code", "title": "a.py"}})
    assert project(WINDOW_SOURCE, payload) == Signal(app="Code", title="a.py")
    web = project(WEB_SOURCE, payload)
    assert web is not None and web.title == "a.py"
    assert project(AFK_SOURCE, "not even json") is None


def test_an_unclaimed_source_raises_its_own_error() -> None:
    with pytest.raises(UnclaimedSource, match="'transcript'") as exc:
        projector_for(KNOWN_SOURCES)("transcript", "{}")
    assert exc.value.source == "transcript"


def test_two_sources_projecting_one_stream_differently_are_refused() -> None:
    with pytest.raises(ValueError, match="stream 'a' is fed by more than one source"):
        projector_for([FakeSource("a"), FakeSource("b", "a")])


def test_the_same_adapter_listed_twice_is_one_claim() -> None:
    projector_for([ActivityWatch, ActivityWatch(FakeAW({}))])


def test_rebuild_reproduces_what_the_runner_ingested_row_for_row(conn: sqlite3.Connection) -> None:
    now = datetime.now(UTC)
    spool = FakeSource("transcript")
    spool.add("transcript", "c1", 0)
    spool.add("transcript", "c2", 1)
    poll(conn, [full_aw(now), spool], now=now)
    history = FakeSource("ocr")
    history.add("ocr", "o1", 0)
    history.add("ocr", "o2", 90)
    plan = plan_backfill(
        history, "ocr", progress=get_progress(conn, "ocr"), now=at(180), chunk=timedelta(hours=1)
    )
    assert run_backfill(conn, history, [plan], clock=lambda: at(180)).ok
    ingested = signal_rows(conn)
    assert {row[1] for row in ingested} == {WINDOW_SOURCE, WEB_SOURCE, "transcript", "ocr"}

    wipe_signals(conn)
    result = reproject_signals(conn, sources=[*KNOWN_SOURCES, spool, history])

    assert signal_rows(conn) == ingested
    assert result.signals_after == len(ingested) and result.skipped == 0


def test_a_fake_adapters_projector_serves_both_ingest_and_rebuild(
    conn: sqlite3.Connection,
) -> None:
    spool = FakeSource("transcript")
    spool.add("transcript", "c1", 0)
    spool.add("transcript", "c2", 1)
    poll(conn, [spool], now=at(10))
    payloads = [row[0] for row in conn.execute("SELECT payload FROM observations ORDER BY id")]
    assert spool.projected == payloads
    titles = [row[0] for row in conn.execute("SELECT title FROM signals ORDER BY observation_id")]
    assert titles == ["c1", "c2"]

    with transaction(conn):
        conn.execute("UPDATE signals SET title = 'stale'")
    reproject_signals(conn, sources=[spool])

    assert spool.projected == payloads + payloads
    assert [row[0] for row in conn.execute("SELECT title FROM signals")] == ["c1", "c2"]


def test_ingest_projects_only_new_observations(conn: sqlite3.Connection) -> None:
    spool = FakeSource("transcript")
    spool.add("transcript", "c1", 0)
    poll(conn, [spool], now=at(10))
    spool.projected.clear()
    plan = plan_backfill(spool, "transcript", progress=None, now=at(10))
    assert run_backfill(conn, spool, [plan], clock=lambda: at(10)).results[0].skipped == 1
    assert spool.projected == []


def test_poll_reports_a_stream_its_adapter_does_not_project_and_goes_on(
    conn: sqlite3.Connection,
) -> None:
    spool = FakeSource("transcript", "ocr", "late")
    spool.projectors = {s: p for s, p in spool.projectors.items() if s != "ocr"}
    for stream in ("transcript", "ocr", "late"):
        spool.add(stream, f"{stream}1", 0)
    other = FakeSource("b")
    other.add("b", "b1", 0)

    summary = poll(conn, [spool, other], now=at(10))

    assert summary.failures == (
        StreamFailure(
            "ocr", "no source adapter projects observations from 'ocr'", FailureKind.ADAPTER
        ),
    )
    assert list(summary.outcomes) == ["transcript", "late", "b"]
    assert stored_sources(conn) == ["b", "late", "transcript"]
    assert get_progress(conn, "ocr") is None


def test_poll_reports_an_observation_from_another_stream_and_stores_none_of_its_batch(
    conn: sqlite3.Connection,
) -> None:
    spool = FakeSource("transcript", "ocr")
    spool.add("transcript", "c1", 0)
    spool.add("ocr", "o1", 0)
    spool.strays["transcript"] = "ocr"

    summary = poll(conn, [spool], now=at(10))

    assert summary.failures == (
        StreamFailure(
            "transcript",
            "a pull of 'transcript' returned an observation from 'ocr'",
            FailureKind.ADAPTER,
        ),
    )
    assert stored_sources(conn) == ["ocr"]
    assert get_progress(conn, "transcript") is None


def test_backfill_stops_at_an_observation_from_another_stream(conn: sqlite3.Connection) -> None:
    spool = FakeSource("a")
    spool.add("a", "a1", 0)
    spool.strays["a"] = "b"
    plan = plan_backfill(spool, "a", progress=None, now=at(10))
    run = run_backfill(conn, spool, [plan], clock=lambda: at(10))
    assert run.failure == StreamFailure(
        "a", "a pull of 'a' returned an observation from 'b'", FailureKind.ADAPTER
    )
    assert stored_sources(conn) == []


def test_watch_logs_an_unprojected_stream_and_keeps_polling(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    spool = FakeSource("transcript", "ocr")
    spool.projectors = {s: p for s, p in spool.projectors.items() if s != "ocr"}
    spool.add("transcript", "c1", 0)
    spool.add("ocr", "o1", 0)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        spool.add("transcript", f"c{len(sleeps) + 1}", len(sleeps))
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    caplog.set_level(logging.INFO)
    with pytest.raises(KeyboardInterrupt):
        watch(conn, [spool], report=cli_ingest.log_cycle, interval=60, sleep=sleep)

    lines = [r for r in caplog.records if r.name == cli_ingest.__name__]
    assert [r.levelno for r in lines] == [logging.WARNING, logging.WARNING]
    assert all(
        "ingest failed on ocr: no source adapter projects observations from 'ocr'" in r.getMessage()
        for r in lines
    )
    assert [r[0] for r in conn.execute("SELECT source_id FROM observations ORDER BY id")] == [
        "c1",
        "c2",
    ]


def test_cli_ingest_prints_an_unprojected_stream_and_exits_nonzero(
    capsys: pytest.CaptureFixture[str], db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aw = full_aw(datetime.now(UTC))
    monkeypatch.setattr(cli_ingest, "AWClient", lambda *args, **kwargs: aw.client)
    claims = {s: p for s, p in ActivityWatch.projectors.items() if s != WINDOW_SOURCE}
    monkeypatch.setattr(ActivityWatch, "projectors", claims)

    code = cli.main(["--db-path", str(db_path), "ingest"])
    out, err = capsys.readouterr()

    assert code == 1
    assert "aw-afk" in out and "aw-web" in out and "aw-window" not in out
    assert "error on aw-window: no source adapter projects observations from 'aw-window'" in err
    assert "locked" not in err and "Traceback" not in err


def test_rebuild_with_an_unclaimed_source_aborts_without_calling_it_malformed(
    conn: sqlite3.Connection,
) -> None:
    poll(conn, [full_aw(datetime.now(UTC))])
    unclaimed_capture(conn)
    before = signal_rows(conn)
    assert before

    with pytest.raises(RebuildAborted) as exc:
        reproject_signals(conn, allow_shrink=True)

    assert exc.value.unclaimed == "transcript"
    assert exc.value.failed == 0 and exc.value.failed_ids == () and not exc.value.shrink
    message = str(exc.value)
    assert "no source adapter projects 'transcript', the source of 1 stored observation " in message
    assert "signals unchanged" in message and "malformed" not in message
    assert isinstance(exc.value.__cause__, UnclaimedSource)
    assert signal_rows(conn) == before
    assert not conn.in_transaction


def test_unclaimed_rows_win_over_earlier_malformed_ones(conn: sqlite3.Connection) -> None:
    poll(conn, [full_aw(datetime.now(UTC))])
    before = signal_rows(conn)
    with transaction(conn):
        corrupt_payloads(conn, "source != ?", (AFK_SOURCE,))
    unclaimed_capture(conn)

    with pytest.raises(RebuildAborted) as exc:
        reproject_signals(conn)

    assert exc.value.unclaimed == "transcript" and exc.value.failed == 0
    assert "malformed" not in str(exc.value)
    assert signal_rows(conn) == before


def test_cli_rebuild_with_an_unclaimed_source_fails_loudly(
    capsys: pytest.CaptureFixture[str], db_path: Path
) -> None:
    conn = connect(db_path)
    try:
        poll(conn, [full_aw(datetime.now(UTC))])
        unclaimed_capture(conn)
        before = signal_rows(conn)
    finally:
        conn.close()

    code = cli.main(["--db-path", str(db_path), "rebuild-signals"])
    out, err = capsys.readouterr()

    assert code == 1 and out == ""
    assert "rebuild-signals aborted: no source adapter projects 'transcript'" in err
    assert "no adapter for that source" in err
    assert "malformed" not in err and "first failing" not in err
    conn = connect(db_path)
    try:
        assert signal_rows(conn) == before
    finally:
        conn.close()
