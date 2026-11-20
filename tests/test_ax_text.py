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

from computer_history import cli
from computer_history.cli import ingest as cli_ingest
from computer_history.sources import (
    AX_TEXT_SOURCE,
    MAX_AX_TEXT_LENGTH,
    MAX_TEXT_LENGTH,
    SCREENSHOT_KIND,
    SCREENSHOT_SOURCE,
    SPOOL_ENV_VAR,
    SPOOL_VERSION,
    UNREADABLE_FOLDER,
    ActivityWatch,
    AWError,
    CaptureSpool,
    FailureKind,
    IngestOutcome,
    InvalidRecord,
    commit_pull,
    finished_files,
    parse_record,
    poll,
    projector_for,
    reproject_signals,
    resolve_spool_path,
    watch,
)
from computer_history.sources.capture_spool import adapter as spool_adapter
from computer_history.store import connect, get_progress, table_counts, utc_iso

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "spool" / "records.jsonl"
FIXTURE_LINES = [
    line
    for line in FIXTURE.read_text(encoding="utf-8").splitlines()
    if json.loads(line)["kind"] != SCREENSHOT_KIND
]
FIXTURE_CAPTURES = sum(json.loads(line)["kind"] == "capture" for line in FIXTURE_LINES)
T0 = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
WINDOW_BUCKET = "aw-watcher-window_test-host.local"
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


@pytest.fixture
def spool_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "spool"
    folder.mkdir()
    return folder


def file_name(minute: int) -> str:
    return (T0 + timedelta(minutes=minute)).strftime("%Y%m%dT%H%M%S.000Z.jsonl")


def write_file(folder: Path, name: str, lines: list[str] | bytes) -> Path:
    path = folder / name
    if isinstance(lines, bytes):
        path.write_bytes(lines)
    else:
        path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


def record(n: int, when: datetime, **fields: Any) -> str:
    data = json.loads(FIXTURE_LINES[0])
    data.update(id=f"00000000-0000-4000-8000-{n:012x}", captured_at=_spool_time(when))
    data.update(fields)
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def _spool_time(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def observations(conn: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    rows = conn.execute(
        "SELECT source_id, started_at, ended_at, payload FROM observations"
        " WHERE source = ? ORDER BY id",
        (AX_TEXT_SOURCE,),
    )
    return [tuple(row) for row in rows]


def signals(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in conn.execute("SELECT * FROM signals ORDER BY observation_id")]


def down_aw() -> FakeAW:
    class Down(FakeAW):
        def get_buckets(self) -> dict[str, dict[str, Any]]:
            raise AWError("ActivityWatch unreachable at http://127.0.0.1:5600/api/0")

    return Down({})


def healthy_aw(now: datetime = NOW) -> FakeAW:
    fake = FakeAW({WINDOW_BUCKET: "currentwindow"}, t0=now - timedelta(minutes=30))
    fake.add(WINDOW_BUCKET, 0, 60, {"app": "Code"})
    return fake


def test_the_fixture_ingests_to_its_observations_and_signals(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    spooled = write_file(spool_dir, file_name(1), FIXTURE_LINES)

    summary = poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    latest = datetime(2026, 11, 18, 9, 15, 42, 999000, tzinfo=UTC)
    assert summary.ok
    assert summary.outcomes == {
        AX_TEXT_SOURCE: IngestOutcome(len(FIXTURE_LINES), 0, 0, latest),
        SCREENSHOT_SOURCE: IngestOutcome(0, 0, 0, None),
    }
    records = [json.loads(line) for line in FIXTURE_LINES]
    assert observations(conn) == [
        (r["id"], utc_iso(r["captured_at"]), utc_iso(r["captured_at"]), line)
        for r, line in zip(records, FIXTURE_LINES, strict=True)
    ]
    rows = conn.execute(
        "SELECT o.source_id, s.source, s.started_at, s.ended_at, s.app, s.domain, s.url,"
        " s.title, s.text, s.extras FROM signals AS s JOIN observations AS o"
        " ON o.id = s.observation_id ORDER BY s.observation_id"
    ).fetchall()
    expected_text = [
        'def finish(path): return "done" # ✓ naïve',
        "Pull requests https://github.com/thewisepup/computer-history/pulls",
        "M2 plan Ship the spool writer",
        None,
    ]
    captures = [r for r in records if r["kind"] == "capture"]
    assert len(rows) == len(captures) == len(expected_text)
    extra_keys = (
        "bundle_id",
        "trigger",
        "text_sha256",
        "full_text_bytes",
        "text_cut_off",
        "timed_out",
    )
    for row, r, text in zip(rows, captures, expected_text, strict=True):
        source_id, source, started, ended, app, domain, url, title, stored_text, extras = row
        assert (source_id, source, started, ended) == (
            r["id"],
            AX_TEXT_SOURCE,
            utc_iso(r["captured_at"]),
            utc_iso(r["captured_at"]),
        )
        assert (app, domain, url, title, stored_text) == (
            r["app_name"],
            None,
            None,
            r["window_title"],
            text,
        )
        assert json.loads(extras) == {key: r[key] for key in extra_keys}
    assert get_progress(conn, AX_TEXT_SOURCE).position == utc_iso(latest)
    assert get_progress(conn, AX_TEXT_SOURCE).settled_until == latest
    assert not spooled.exists()


def test_excluded_paused_and_resumed_records_have_no_signal() -> None:
    project = projector_for([CaptureSpool])
    kinds = {json.loads(line)["kind"]: line for line in FIXTURE_LINES}
    for kind in ("excluded", "paused", "resumed"):
        assert project(AX_TEXT_SOURCE, kinds[kind]) is None
    assert project(AX_TEXT_SOURCE, kinds["capture"]) is not None


def test_rebuild_reprojects_the_spool_to_identical_signals(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    write_file(spool_dir, file_name(1), FIXTURE_LINES)
    write_file(spool_dir, file_name(2), [record(1, T0, text="x" * 20_000)])
    poll(conn, [CaptureSpool(spool_dir)], now=NOW)
    before = signals(conn)
    assert len(before) == FIXTURE_CAPTURES + 1

    result = reproject_signals(conn)

    assert signals(conn) == before
    assert result.signals_before == result.signals_after == len(before)
    assert result.skipped == 0


def test_a_crash_between_commit_and_removal_re_reads_nothing_new(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    spooled = write_file(spool_dir, file_name(1), FIXTURE_LINES)
    spool = CaptureSpool(spool_dir)
    pulled = spool.pull_after(AX_TEXT_SOURCE, None, now=NOW)
    crashed = replace(pulled, after_commit=None)
    commit_pull(
        conn,
        AX_TEXT_SOURCE,
        crashed,
        project=projector_for([spool]),
        now=NOW,
        progress_from=crashed,
    )
    assert spooled.exists()
    stored, projected, progress = observations(conn), signals(conn), get_progress(conn, "ax-text")

    summary = poll(conn, [spool], now=NOW + timedelta(minutes=1))

    assert summary.outcomes[AX_TEXT_SOURCE] == IngestOutcome(0, len(FIXTURE_LINES), 0, None)
    assert observations(conn) == stored and signals(conn) == projected
    assert get_progress(conn, AX_TEXT_SOURCE) == progress
    assert not spooled.exists()


def test_open_part_agent_lock_and_other_entries_are_ignored_and_left_in_place(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    kept = [
        write_file(spool_dir, "open.part", [record(1, T0)]),
        write_file(spool_dir, "agent.lock", b""),
        write_file(spool_dir, "._20261118T090000.000Z.jsonl", b"\x00\x05\x16\x07"),
        write_file(spool_dir, "notes.txt", [record(2, T0)]),
    ]
    (spool_dir / "folder.jsonl").mkdir()
    write_file(spool_dir, file_name(1), [record(3, T0)])

    assert finished_files(spool_dir) == [spool_dir / file_name(1)]
    summary = poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    assert summary.outcomes[AX_TEXT_SOURCE].inserted == 1
    assert all(path.exists() for path in kept) and (spool_dir / "folder.jsonl").is_dir()
    assert sorted(p.name for p in spool_dir.iterdir()) == sorted(
        [*(p.name for p in kept), "folder.jsonl"]
    )


def test_a_missing_spool_folder_is_nothing_to_ingest(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    summary = poll(conn, [CaptureSpool(tmp_path / "no-such-spool")], now=NOW)

    assert summary.ok
    assert summary.outcomes == {
        AX_TEXT_SOURCE: IngestOutcome(0, 0, 0, None),
        SCREENSHOT_SOURCE: IngestOutcome(0, 0, 0, None),
    }
    assert get_progress(conn, AX_TEXT_SOURCE) is None
    assert not (tmp_path / "no-such-spool").exists()


def test_a_large_backlog_is_ingested_oldest_first_in_one_poll(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    expected = []
    for minute in reversed(range(300)):
        lines = [record(minute * 2 + k, T0 + timedelta(minutes=minute, seconds=k)) for k in (0, 1)]
        write_file(spool_dir, file_name(minute), lines)
    for minute in range(300):
        expected += [f"00000000-0000-4000-8000-{minute * 2 + k:012x}" for k in (0, 1)]

    summary = poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    last = T0 + timedelta(minutes=299, seconds=1)
    assert summary.outcomes[AX_TEXT_SOURCE] == IngestOutcome(600, 0, 0, last)
    assert [row[0] for row in observations(conn)] == expected
    assert get_progress(conn, AX_TEXT_SOURCE).position == utc_iso(last)
    assert list(spool_dir.iterdir()) == []


def test_progress_never_moves_back_to_an_older_capture(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    write_file(spool_dir, file_name(5), [record(1, T0 + timedelta(minutes=5))])
    poll(conn, [CaptureSpool(spool_dir)], now=NOW)
    write_file(spool_dir, file_name(6), [record(2, T0)])

    summary = poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    assert summary.outcomes[AX_TEXT_SOURCE] == IngestOutcome(1, 0, 0, None)
    assert get_progress(conn, AX_TEXT_SOURCE).position == utc_iso(T0 + timedelta(minutes=5))


@pytest.mark.skipif(os.geteuid() == 0, reason="root can remove files from a read-only folder")
def test_a_file_that_cannot_be_removed_fails_once_and_does_not_block_later_files(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    first = write_file(spool_dir, file_name(1), [record(1, T0)])
    spool = CaptureSpool(spool_dir)
    spool_dir.chmod(0o555)
    try:
        failed = poll(conn, [spool], now=NOW)
        spool_dir.chmod(0o755)
        second = write_file(spool_dir, file_name(2), [record(2, T0)])
        spool_dir.chmod(0o555)
        again = poll(conn, [spool], now=NOW)
    finally:
        spool_dir.chmod(0o755)

    assert [f.kind for f in failed.failures] == [FailureKind.SOURCE]
    assert "cannot remove stored spool file" in failed.failures[0].error
    assert "spool/" + file_name(2) in again.failures[0].error
    assert len(observations(conn)) == 2 and first.exists() and second.exists()
    drained = poll(conn, [CaptureSpool(spool_dir)], now=NOW)
    assert drained.outcomes[AX_TEXT_SOURCE] == IngestOutcome(0, 2, 0, None)
    assert finished_files(spool_dir) == []


def test_a_capture_dated_after_now_is_stored_but_does_not_move_progress(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    future = NOW + timedelta(days=400)
    write_file(spool_dir, file_name(1), [record(1, T0), record(2, future)])
    poll(conn, [CaptureSpool(spool_dir)], now=NOW)
    assert len(observations(conn)) == 2
    assert get_progress(conn, AX_TEXT_SOURCE).position == utc_iso(T0)

    write_file(spool_dir, file_name(2), [record(3, future)])
    later = future + timedelta(minutes=1)
    poll(conn, [CaptureSpool(spool_dir)], now=later)
    write_file(spool_dir, file_name(3), [record(4, T0 + timedelta(minutes=3))])
    poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    assert get_progress(conn, AX_TEXT_SOURCE).position == utc_iso(T0 + timedelta(minutes=3))


def test_a_backlog_is_listed_once_per_drain(
    conn: sqlite3.Connection, spool_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for minute in range(20):
        write_file(spool_dir, file_name(minute), [record(minute, T0 + timedelta(minutes=minute))])
    listings: list[int] = []

    def counted(folder: Path) -> list[Path]:
        found = finished_files(folder)
        listings.append(len(found))
        return found

    monkeypatch.setattr(spool_adapter, "finished_files", counted)
    spool = CaptureSpool(spool_dir)

    assert poll(conn, [spool], now=NOW).outcomes[AX_TEXT_SOURCE].inserted == 20
    assert listings == [20, 20]
    poll(conn, [spool], now=NOW)
    assert listings == [20, 20, 0, 0]


def test_malformed_lines_and_unknown_versions_are_skipped_and_counted(
    conn: sqlite3.Connection, spool_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    good = [record(1, T0), record(2, T0 + timedelta(seconds=1))]
    lines = [
        good[0],
        "{not json",
        record(3, T0, version=SPOOL_VERSION + 1),
        record(10, T0, version=1.0),
        record(4, T0, version=True),
        "[1, 2]",
        "",
        record(5, T0, kind="snapshot"),
        record(6, T0, id="NOT-A-UUID"),
        record(7, T0, captured_at="2026-11-18T09:00:00"),
        record(8, T0, text=42),
        record(9, T0, timed_out="no"),
        good[1],
    ]
    path = write_file(spool_dir, file_name(1), lines)
    with path.open("ab") as handle:
        handle.write(b"\xff\xfe broken utf-8\n")
    kept = path.read_bytes()

    summary = poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    assert summary.ok
    assert summary.outcomes[AX_TEXT_SOURCE] == IngestOutcome(
        2, 0, 0, T0 + timedelta(seconds=1), rejected=7
    )
    assert [row[3] for row in observations(conn)] == good
    assert not path.exists()
    assert (spool_dir / UNREADABLE_FOLDER / file_name(1)).read_bytes() == kept
    assert "skipped 7 unusable record(s)" in caplog.text
    assert "line 3: unknown version 2" in caplog.text
    assert "it has 11 unusable line(s), 4 of no readable kind" in caplog.text
    assert "its usable lines are stored" in caplog.text


@pytest.mark.parametrize(
    ("line", "problem"),
    [
        ("{", "not JSON"),
        ("1", "not a JSON object"),
        (record(1, T0, version=SPOOL_VERSION + 1), "unknown version"),
        (record(1, T0, version=float(SPOOL_VERSION)), "unknown version"),
        (record(1, T0, kind=None), "unknown kind"),
        (record(1, T0, id=7), "bad id"),
        (record(1, T0, captured_at="yesterday"), "bad captured_at"),
        (record(1, T0, full_text_bytes=True), "full_text_bytes is not a int"),
    ],
)
def test_a_record_failing_validation_says_why(line: str, problem: str) -> None:
    with pytest.raises(InvalidRecord, match=problem):
        parse_record(line)


def test_a_file_with_no_usable_record_is_moved_aside_not_deleted(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    junk = b"\x00\x01\x02 not a spool file\nstill not\n"
    write_file(spool_dir, file_name(1), junk)
    write_file(spool_dir, file_name(2), [record(1, T0)])

    summary = poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    assert summary.ok
    assert summary.outcomes[AX_TEXT_SOURCE] == IngestOutcome(1, 0, 0, T0)
    aside = spool_dir / UNREADABLE_FOLDER / file_name(1)
    assert aside.read_bytes() == junk
    assert finished_files(spool_dir) == []


def test_a_set_aside_name_already_taken_gets_its_own_copy(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    (spool_dir / UNREADABLE_FOLDER).mkdir()
    write_file(spool_dir / UNREADABLE_FOLDER, file_name(1), b"older")
    write_file(spool_dir, file_name(1), b"newer")

    poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    names = sorted(p.name for p in (spool_dir / UNREADABLE_FOLDER).iterdir())
    assert names == [file_name(1).replace(".jsonl", ".1.jsonl"), file_name(1)]
    assert (spool_dir / UNREADABLE_FOLDER / file_name(1)).read_bytes() == b"older"


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads files without read permission")
def test_an_unreadable_file_is_moved_aside_and_the_rest_ingested(
    conn: sqlite3.Connection, spool_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    locked = write_file(spool_dir, file_name(1), [record(1, T0)])
    locked.chmod(0o000)
    write_file(spool_dir, file_name(2), [record(2, T0)])

    summary = poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    aside = spool_dir / UNREADABLE_FOLDER / file_name(1)
    aside.chmod(0o644)
    assert summary.ok and summary.outcomes[AX_TEXT_SOURCE].inserted == 1
    assert aside.read_text(encoding="utf-8") == record(1, T0) + "\n"
    assert finished_files(spool_dir) == []
    assert f"moved spool file {file_name(1)}" in caplog.text and "cannot read it" in caplog.text


def test_text_is_capped_at_ten_thousand_characters_and_titles_keep_theirs(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    text, title = "a" * 12_000, "t" * 3_000
    write_file(spool_dir, file_name(1), [record(1, T0, text=text, window_title=title)])

    poll(conn, [CaptureSpool(spool_dir)], now=NOW)

    stored_text, stored_title = conn.execute("SELECT text, title FROM signals").fetchone()
    assert MAX_AX_TEXT_LENGTH == 10_000
    assert stored_text == "a" * MAX_AX_TEXT_LENGTH
    assert stored_title == "t" * MAX_TEXT_LENGTH
    assert json.loads(observations(conn)[0][3])["text"] == text


def test_activitywatch_down_does_not_stop_the_spool(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    write_file(spool_dir, file_name(1), FIXTURE_LINES)

    summary = poll(conn, [ActivityWatch(down_aw()), CaptureSpool(spool_dir)], now=NOW)

    assert [(f.stream, f.kind) for f in summary.failures] == [(None, FailureKind.SOURCE)]
    assert summary.outcomes[AX_TEXT_SOURCE].inserted == len(FIXTURE_LINES)


def test_an_unlistable_spool_does_not_stop_activitywatch(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    not_a_folder = tmp_path / "spool"
    not_a_folder.write_text("a file where the folder should be")

    summary = poll(conn, [CaptureSpool(not_a_folder), ActivityWatch(healthy_aw())], now=NOW)

    assert [(f.stream, f.kind) for f in summary.failures] == [(AX_TEXT_SOURCE, FailureKind.SOURCE)]
    assert "cannot list the spool" in summary.failures[0].error
    assert summary.outcomes["aw-window"].inserted == 1


def test_watch_polls_activitywatch_and_the_spool_in_one_loop(
    conn: sqlite3.Connection, spool_dir: Path
) -> None:
    write_file(spool_dir, file_name(1), [record(1, T0)])
    reports: list[str] = []
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 1:
            write_file(spool_dir, file_name(2), [record(2, T0)])
        else:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        watch(
            conn,
            [ActivityWatch(down_aw()), CaptureSpool(spool_dir)],
            report=lambda summary, delay: reports.append(cli_ingest.cycle_line(summary)),
            clock=lambda: NOW,
            sleep=sleep,
        )

    assert len(reports) == 2
    assert all("ax-text +1 (0 dup, 0 held)" in line for line in reports)
    assert all("ActivityWatch unreachable" in line for line in reports)
    assert len(observations(conn)) == 2


def test_the_spool_path_is_the_flag_then_the_env_var_then_beside_the_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "data" / "history.db"
    monkeypatch.delenv(SPOOL_ENV_VAR, raising=False)
    assert resolve_spool_path(None, db_path) == tmp_path / "data" / "spool"
    monkeypatch.setenv(SPOOL_ENV_VAR, "")
    assert resolve_spool_path("", db_path) == tmp_path / "data" / "spool"
    monkeypatch.setenv(SPOOL_ENV_VAR, str(tmp_path / "env-spool"))
    assert resolve_spool_path(None, db_path) == tmp_path / "env-spool"
    assert resolve_spool_path(str(tmp_path / "flag"), db_path) == tmp_path / "flag"
    assert resolve_spool_path("~/x", db_path) == Path.home() / "x"


@pytest.fixture
def cli_aw(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(SPOOL_ENV_VAR, raising=False)

    def install(fake: FakeAW) -> None:
        monkeypatch.setattr(cli_ingest, "AWClient", lambda *args, **kwargs: fake)

    return install


def test_cli_ingest_reads_the_spool_beside_the_database(
    capsys: pytest.CaptureFixture[str], cli_aw, tmp_path: Path
) -> None:
    cli_aw(healthy_aw(datetime.now(UTC)))
    db_path = tmp_path / "history.db"
    (tmp_path / "spool").mkdir()
    write_file(tmp_path / "spool", file_name(1), FIXTURE_LINES)

    code = cli.main(["--db-path", str(db_path), "ingest"])
    out = capsys.readouterr().out

    assert code == 0
    assert f"and {tmp_path / 'spool'} into {db_path}" in out
    assert re.search(
        rf"ax-text\s+inserted\s+{len(FIXTURE_LINES)}\s+skipped\s+0\s+held back\s+0\n", out
    )
    assert re.search(r"aw-window\s+inserted\s+1", out)
    assert "no ActivityWatch sources found" not in out
    conn = connect(db_path)
    try:
        assert table_counts(conn)["observations"] == len(FIXTURE_LINES) + 1
    finally:
        conn.close()


def test_cli_ingest_honors_the_spool_flag_and_prints_rejected_records(
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
    cli_aw,
    tmp_path: Path,
) -> None:
    cli_aw(healthy_aw(datetime.now(UTC)))
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    write_file(elsewhere, file_name(1), [record(1, T0), record(2, T0, timed_out="no"), "{broken"])

    code = cli.main(["--db-path", str(tmp_path / "h.db"), "ingest", "--spool-path", str(elsewhere)])
    out = capsys.readouterr().out

    assert code == 0
    assert re.search(r"ax-text\s+inserted\s+1\s+skipped\s+0\s+held back\s+0\s+rejected 1", out)
    assert "it has 2 unusable line(s), 1 of no readable kind" in caplog.text
    assert finished_files(elsewhere) == []


def test_cli_ingest_with_activitywatch_down_still_stores_the_spool(
    capsys: pytest.CaptureFixture[str], cli_aw, tmp_path: Path
) -> None:
    cli_aw(down_aw())
    (tmp_path / "spool").mkdir()
    write_file(tmp_path / "spool", file_name(1), FIXTURE_LINES)

    code = cli.main(["--db-path", str(tmp_path / "h.db"), "ingest"])
    out, err = capsys.readouterr()

    assert code == 1
    assert re.search(rf"ax-text\s+inserted\s+{len(FIXTURE_LINES)}", out)
    assert "Is ActivityWatch running?" in err and "Traceback" not in err


def test_cli_ingest_with_an_unlistable_spool_gives_the_spool_hint(
    capsys: pytest.CaptureFixture[str], cli_aw, tmp_path: Path
) -> None:
    cli_aw(healthy_aw(datetime.now(UTC)))
    (tmp_path / "spool").write_text("not a folder")

    code = cli.main(["--db-path", str(tmp_path / "h.db"), "ingest"])
    out, err = capsys.readouterr()

    assert code == 1
    assert re.search(r"aw-window\s+inserted\s+1", out)
    assert "error on the spool: cannot list the spool" in err
    assert "spool folder" in err and "Is ActivityWatch running?" not in err
