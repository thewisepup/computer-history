from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fake_aw import FakeAW
from log_records import logged

from computer_history import cli
from computer_history.cli import ingest as cli_ingest
from computer_history.sources import (
    MAX_RECOGNIZED_TEXT_LENGTH,
    SCREENSHOT_KIND,
    SCREENSHOT_SOURCE,
    UNREADABLE_FOLDER,
    WINDOW_TEXT_SOURCE,
    CaptureSpool,
    IngestOutcome,
    commit_pull,
    poll,
    projector_for,
    reproject_signals,
    spool_backlog,
)
from computer_history.sources.capture_spool import adapter as spool_adapter
from computer_history.store import connect, get_progress, utc_iso

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "spool" / "records.jsonl"
FIXTURE_LINES = FIXTURE.read_text(encoding="utf-8").splitlines()
SCREENSHOT_LINES = [line for line in FIXTURE_LINES if json.loads(line)["kind"] == SCREENSHOT_KIND]
CAPTURE_AGENT_LINES = [line for line in FIXTURE_LINES if line not in SCREENSHOT_LINES]
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)
T0 = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
FILE_NAME = "20261118T090100.000Z.jsonl"


@pytest.fixture
def spool_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "spool"
    folder.mkdir()
    return folder


def write_file(folder: Path, lines: list[str], name: str = FILE_NAME) -> Path:
    path = folder / name
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


def stored(conn: sqlite3.Connection, source: str) -> list[tuple[str, str, str, str]]:
    rows = conn.execute(
        "SELECT source_id, started_at, ended_at, payload FROM observations"
        " WHERE source = ? ORDER BY id",
        (source,),
    )
    return [tuple(row) for row in rows]


def screenshot_signals(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    rows = conn.execute(
        "SELECT o.source_id, s.source, s.started_at, s.ended_at, s.app, s.domain, s.url, s.title,"
        " s.text, s.extras FROM signals AS s JOIN observations AS o ON o.id = s.observation_id"
        " WHERE s.source = ? ORDER BY s.observation_id",
        (SCREENSHOT_SOURCE,),
    )
    return [(*row[:9], json.loads(row[9])) for row in rows]


def all_signals(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in conn.execute("SELECT * FROM signals ORDER BY observation_id")]


def screenshot(n: int, when: datetime, **fields: Any) -> str:
    data = json.loads(SCREENSHOT_LINES[1])
    at = when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"
    data.update(id=f"00000000-0000-4000-8000-{n:012x}", captured_at=at, **fields)
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def test_the_fixture_stores_every_screenshot_record_verbatim_with_its_signal(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    spooled = write_file(spool_dir, FIXTURE_LINES)

    summary = poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    newest = datetime(2026, 11, 18, 9, 1, 1, 500000, tzinfo=UTC)
    assert summary.ok
    assert summary.outcomes[SCREENSHOT_SOURCE] == IngestOutcome(5, 0, 0, newest)
    assert stored(conn, SCREENSHOT_SOURCE) == [
        (
            json.loads(line)["id"],
            utc_iso(json.loads(line)["captured_at"]),
            utc_iso(json.loads(line)["captured_at"]),
            line,
        )
        for line in SCREENSHOT_LINES
    ]
    assert [row[3] for row in stored(conn, WINDOW_TEXT_SOURCE)] == CAPTURE_AGENT_LINES
    capture = "6f1c2a52-8d0e-4b7a-9c3e-1a2b3c4d5e0"
    shot = "6f1c2a52-8d0e-4b7a-9c3e-1a2b3c4d5e1"
    assert screenshot_signals(conn) == [
        (
            f"{shot}0",
            SCREENSHOT_SOURCE,
            "2026-11-18T08:59:58.000000Z",
            "2026-11-18T08:59:58.000000Z",
            "Safari",
            None,
            None,
            "Sign In – Apple Account",
            None,
            {"capture_id": f"{capture}0", "status": "secure-field"},
        ),
        (
            f"{shot}1",
            SCREENSHOT_SOURCE,
            "2026-11-18T09:00:00.000000Z",
            "2026-11-18T09:00:00.000000Z",
            "Cursor",
            None,
            None,
            "spool.py — computer-history",
            'def finish(path): return "done" # ✓ naïve',
            {
                "capture_id": f"{capture}1",
                "image_bytes": 183442,
                "image_path": f"screenshots/2026-11-18/{shot}1.jpg",
                "perceptual_hash": "c3a1f0e2d4b69785",
                "status": "kept",
            },
        ),
        (
            f"{shot}2",
            SCREENSHOT_SOURCE,
            "2026-11-18T09:00:05.250000Z",
            "2026-11-18T09:00:05.250000Z",
            "Google Chrome",
            None,
            None,
            "Pull requests · thewisepup/computer-history",
            "Pull requests Open 3 Closed 27",
            {
                "capture_id": f"{capture}2",
                "image_path": "screenshots/2026-11-17/6f1c2a52-8d0e-4b7a-9c3e-1a2b3c4d5e09.jpg",
                "perceptual_hash": "9f8e7d6c5b4a3921",
                "status": "duplicate",
            },
        ),
        (
            f"{shot}3",
            SCREENSHOT_SOURCE,
            "2026-11-18T09:00:31.007000Z",
            "2026-11-18T09:00:31.007000Z",
            "Notion",
            None,
            None,
            "M2 plan",
            None,
            {"capture_id": f"{capture}3", "status": "failed"},
        ),
        (
            f"{shot}4",
            SCREENSHOT_SOURCE,
            "2026-11-18T09:01:01.500000Z",
            "2026-11-18T09:01:01.500000Z",
            "Spotify",
            None,
            None,
            "Spotify Premium",
            None,
            {"capture_id": f"{capture}4", "status": "no-permission"},
        ),
    ]
    progress = get_progress(conn, SCREENSHOT_SOURCE)
    assert progress is not None
    assert progress.position == utc_iso(newest)
    assert progress.settled_until == newest
    assert not spooled.exists()


def test_recognized_text_in_the_signal_stops_at_the_recognized_text_cap(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    line = screenshot(1, T0, text="word " * 4000)
    write_file(spool_dir, [line])

    poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    assert stored(conn, SCREENSHOT_SOURCE)[0][3] == line
    text = screenshot_signals(conn)[0][8]
    assert len(text) == MAX_RECOGNIZED_TEXT_LENGTH and text.startswith("word word")


def test_rebuild_reproduces_the_screenshot_signals(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    write_file(spool_dir, FIXTURE_LINES)
    poll(conn, [CaptureSpool(spool_dir)], now=NOW)
    before = all_signals(conn)
    assert len(screenshot_signals(conn)) == len(SCREENSHOT_LINES)

    result = reproject_signals(conn)

    assert all_signals(conn) == before
    assert result.signals_before == result.signals_after == len(before)
    assert result.skipped == 0


def test_re_ingesting_the_same_file_stores_nothing_twice(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    write_file(spool_dir, FIXTURE_LINES)
    poll(conn, [CaptureSpool(spool_dir)], now=NOW)
    observed, projected = stored(conn, SCREENSHOT_SOURCE), all_signals(conn)
    progress = get_progress(conn, SCREENSHOT_SOURCE)
    again = write_file(spool_dir, FIXTURE_LINES, "20261118T090200.000Z.jsonl")

    summary = poll(conn, [CaptureSpool(spool_dir)], now=NOW + timedelta(minutes=1))

    assert summary.outcomes[SCREENSHOT_SOURCE] == IngestOutcome(0, 5, 0, None)
    assert stored(conn, SCREENSHOT_SOURCE) == observed and all_signals(conn) == projected
    assert get_progress(conn, SCREENSHOT_SOURCE) == progress
    assert not again.exists()


def commit(conn: sqlite3.Connection, spool: CaptureSpool, stream: str, *, crash: bool = False):
    pulled = spool.pull_after(stream, None, now=NOW)
    if crash:
        pulled = replace(pulled, after_commit=None)
    commit_pull(conn, stream, pulled, project=projector_for([spool]), now=NOW, progress_from=pulled)
    return pulled


@pytest.mark.parametrize(
    ("first", "second"),
    [(WINDOW_TEXT_SOURCE, SCREENSHOT_SOURCE), (SCREENSHOT_SOURCE, WINDOW_TEXT_SOURCE)],
)
def test_a_spool_file_is_removed_only_once_both_streams_have_stored_it(
    conn: sqlite3.Connection, spool_dir: Path, first: str, second: str
) -> None:
    spooled = write_file(spool_dir, FIXTURE_LINES)
    spool = CaptureSpool(spool_dir)

    commit(conn, spool, first)
    assert spooled.exists()
    assert stored(conn, second) == []

    commit(conn, spool, second)
    assert not spooled.exists()
    assert len(stored(conn, WINDOW_TEXT_SOURCE)) == len(CAPTURE_AGENT_LINES)
    assert len(stored(conn, SCREENSHOT_SOURCE)) == len(SCREENSHOT_LINES)


@pytest.mark.parametrize("crashed", [WINDOW_TEXT_SOURCE, SCREENSHOT_SOURCE])
def test_a_crash_after_one_stream_stores_a_file_loses_nothing_from_either(
    conn: sqlite3.Connection, spool_dir: Path, crashed: str
) -> None:
    spooled = write_file(spool_dir, FIXTURE_LINES)
    commit(conn, CaptureSpool(spool_dir), crashed, crash=True)
    assert spooled.exists()

    summary = poll(conn, [CaptureSpool(spool_dir)], now=NOW + timedelta(minutes=1))

    assert summary.ok
    assert len(stored(conn, WINDOW_TEXT_SOURCE)) == len(CAPTURE_AGENT_LINES)
    assert len(stored(conn, SCREENSHOT_SOURCE)) == len(SCREENSHOT_LINES)
    assert not spooled.exists()


def test_a_new_file_under_a_name_one_stream_already_stored_waits_for_both(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    spooled = write_file(spool_dir, CAPTURE_AGENT_LINES)
    spool = CaptureSpool(spool_dir)
    commit(conn, spool, WINDOW_TEXT_SOURCE)
    other = CaptureSpool(spool_dir)
    commit(conn, other, WINDOW_TEXT_SOURCE)
    commit(conn, other, SCREENSHOT_SOURCE)
    assert not spooled.exists()
    write_file(spool_dir, SCREENSHOT_LINES)

    commit(conn, spool, SCREENSHOT_SOURCE)

    assert spooled.exists()
    assert len(stored(conn, SCREENSHOT_SOURCE)) == len(SCREENSHOT_LINES)


def test_a_file_of_screenshot_records_alone_is_stored_and_removed(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    spooled = write_file(spool_dir, SCREENSHOT_LINES)

    summary = poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    assert summary.outcomes[WINDOW_TEXT_SOURCE] == IngestOutcome(0, 0, 0, None)
    assert summary.outcomes[SCREENSHOT_SOURCE].inserted == len(SCREENSHOT_LINES)
    assert get_progress(conn, WINDOW_TEXT_SOURCE) is None
    assert not spooled.exists()


def test_each_stream_counts_its_own_unusable_lines_and_the_file_is_set_aside_once(
    conn: sqlite3.Connection, spool_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    capture = json.loads(CAPTURE_AGENT_LINES[0])
    lines = [
        *FIXTURE_LINES,
        screenshot(1, T0, status="blurry"),
        screenshot(2, T0, image_bytes="big"),
        screenshot(3, T0, version=2),
        screenshot(4, T0).replace('"id": "00000000-0000-4000-8000-000000000004"', '"id": "x"'),
        "{not json",
        json.dumps(capture | {"kind": "snapshot"}),
        json.dumps(capture | {"timed_out": "no"}),
        json.dumps(capture | {"version": 2}),
    ]
    spooled = write_file(spool_dir, lines)
    kept = spooled.read_bytes()

    summary = poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    assert summary.outcomes[SCREENSHOT_SOURCE].inserted == len(SCREENSHOT_LINES)
    assert summary.outcomes[SCREENSHOT_SOURCE].rejected == 4
    assert summary.outcomes[WINDOW_TEXT_SOURCE].inserted == len(CAPTURE_AGENT_LINES)
    assert summary.outcomes[WINDOW_TEXT_SOURCE].rejected == 2
    assert not spooled.exists()
    assert [p.read_bytes() for p in (spool_dir / UNREADABLE_FOLDER).iterdir()] == [kept]
    skipped = logged(caplog, "unusable spool records skipped")
    assert {(r["stream"], r["rejected"]) for r in skipped} == {
        (SCREENSHOT_SOURCE, 4),
        (WINDOW_TEXT_SOURCE, 2),
    }
    [aside] = logged(caplog, "spool file set aside")
    assert "it has 8 unusable line(s), 2 of no readable kind" in str(aside["error"])


def test_screenshot_records_never_move_the_window_text_progress(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    capture = json.loads(CAPTURE_AGENT_LINES[0])
    write_file(spool_dir, [CAPTURE_AGENT_LINES[0], screenshot(1, T0 + timedelta(minutes=9))])

    poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    window_text = get_progress(conn, WINDOW_TEXT_SOURCE)
    screenshots = get_progress(conn, SCREENSHOT_SOURCE)
    assert window_text is not None and screenshots is not None
    assert window_text.position == utc_iso(capture["captured_at"])
    assert screenshots.position == utc_iso(T0 + timedelta(minutes=9))


def test_the_spool_backlog_names_its_newest_capture_agent_record_not_a_screenshot(
    spool_dir: Path,
) -> None:
    paused = next(line for line in CAPTURE_AGENT_LINES if json.loads(line)["kind"] == "paused")
    write_file(spool_dir, [paused, screenshot(1, datetime(2026, 11, 18, 9, 2, tzinfo=UTC))])

    newest = spool_backlog(spool_dir).newest

    assert newest == (datetime(2026, 11, 18, 9, 3, tzinfo=UTC), "paused")


def test_the_spool_feeds_both_streams() -> None:
    spool = CaptureSpool(Path("unused"))

    assert spool.streams() == [WINDOW_TEXT_SOURCE, SCREENSHOT_SOURCE]
    assert set(spool.projectors) == {WINDOW_TEXT_SOURCE, SCREENSHOT_SOURCE}


@pytest.mark.skipif(os.geteuid() == 0, reason="root can remove files from a read-only folder")
def test_cli_ingest_gives_the_spool_hint_when_the_screenshot_stream_fails(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli_ingest, "AWClient", lambda *args, **kwargs: FakeAW({}))
    spool = tmp_path / "spool"
    spool.mkdir()
    write_file(spool, FIXTURE_LINES)
    spool.chmod(0o555)
    try:
        code = cli.main(["--db-path", str(tmp_path / "h.db"), "ingest"])
    finally:
        spool.chmod(0o755)
    out, err = capsys.readouterr()

    assert code == 1
    assert re.search(rf"ax-text\s+inserted\s+{len(CAPTURE_AGENT_LINES)}\s", out)
    assert "error on the spool: cannot remove stored spool file" in err
    assert "screenshot" not in err
    assert "spool folder" in err and "Is ActivityWatch running?" not in err
    conn = connect(tmp_path / "h.db")
    try:
        assert len(stored(conn, SCREENSHOT_SOURCE)) == len(SCREENSHOT_LINES)
    finally:
        conn.close()


def failing_read(monkeypatch: pytest.MonkeyPatch, *, failing_call: int) -> None:
    calls = []
    real = spool_adapter.read_file

    def read(path: Path):
        calls.append(path)
        if len(calls) == failing_call:
            raise OSError(24, "Too many open files")
        return real(path)

    monkeypatch.setattr(spool_adapter, "read_file", read)


@pytest.mark.parametrize(
    ("stored_first", "failed"),
    [(WINDOW_TEXT_SOURCE, SCREENSHOT_SOURCE), (SCREENSHOT_SOURCE, WINDOW_TEXT_SOURCE)],
)
def test_one_streams_failed_read_never_sets_aside_what_the_other_stream_still_needs(
    conn: sqlite3.Connection,
    spool_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stored_first: str,
    failed: str,
) -> None:
    spooled = write_file(spool_dir, FIXTURE_LINES)
    spool = CaptureSpool(spool_dir)
    failing_read(monkeypatch, failing_call=2)
    commit(conn, spool, stored_first)

    commit(conn, spool, failed)

    assert spooled.exists() and not (spool_dir / UNREADABLE_FOLDER).exists()
    assert stored(conn, failed) == []
    retried = logged(caplog, "spool file unreadable, will retry")
    assert [(r["file"], r["stream"]) for r in retried] == [(FILE_NAME, failed)]
    summary = poll(conn, [spool], now=NOW + timedelta(minutes=1))
    assert summary.ok
    assert len(stored(conn, WINDOW_TEXT_SOURCE)) == len(CAPTURE_AGENT_LINES)
    assert len(stored(conn, SCREENSHOT_SOURCE)) == len(SCREENSHOT_LINES)
    assert not spooled.exists() and not (spool_dir / UNREADABLE_FOLDER).exists()


def test_a_read_failing_for_one_stream_before_any_stream_stored_the_file_waits_too(
    conn: sqlite3.Connection, spool_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spooled = write_file(spool_dir, FIXTURE_LINES)
    spool = CaptureSpool(spool_dir)
    failing_read(monkeypatch, failing_call=1)

    first = poll(conn, [spool], now=NOW)

    assert first.ok and spooled.exists()
    assert stored(conn, WINDOW_TEXT_SOURCE) == []
    assert len(stored(conn, SCREENSHOT_SOURCE)) == len(SCREENSHOT_LINES)
    poll(conn, [spool], now=NOW + timedelta(minutes=1))
    assert len(stored(conn, WINDOW_TEXT_SOURCE)) == len(CAPTURE_AGENT_LINES)
    assert not spooled.exists() and not (spool_dir / UNREADABLE_FOLDER).exists()
