"""The capture agent in status: the coverage rule, liveness, the spool backlog and the CLI lines."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fake_aw import FakeAW
from projectors import AW

from computer_history import cli
from computer_history.cli import status as cli_status
from computer_history.sources import (
    AFK_SOURCE,
    AGENT_ALIVE_WITHIN,
    AX_TEXT_SOURCE,
    CAPTURE_TOLERANCE,
    HEARTBEAT_SECONDS,
    SPOOL_ENV_VAR,
    SPOOL_VERSION,
    UNREADABLE_FOLDER,
    StoredRecord,
    capture_coverage,
    capture_health,
    liveness,
    spool_backlog,
)
from computer_history.store import (
    Gap,
    Observation,
    ProgressUpdate,
    connect,
    insert_observations,
    source_summary,
)

NOW = datetime(2026, 11, 18, 18, 0, tzinfo=UTC)
DAY_START = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
AFK_BUCKET = "aw-watcher-afk_test-host.local"


def at(minutes: float, base: datetime = NOW) -> datetime:
    return base + timedelta(minutes=minutes)


def heartbeats(start: float, end: float, kind: str = "capture") -> list[StoredRecord]:
    """A record every heartbeat from start to end minutes."""
    step = HEARTBEAT_SECONDS / 60
    return [StoredRecord(at(start + i * step), kind) for i in range(int((end - start) / step) + 1)]


def gaps(*spans: tuple[float, float]) -> tuple[Gap, ...]:
    return tuple(Gap(at(a), at(b)) for a, b in spans)


def coverage(
    records: list[StoredRecord],
    *,
    active: list[tuple[float, float]] = (),
    idle: list[tuple[float, float]] = (),
    start: float = -60,
    end: float = 0,
    paused_at_start: bool = False,
):
    known = [*active, *idle]
    return capture_coverage(
        records,
        active=[(at(a), at(b)) for a, b in active],
        known=[(at(a), at(b)) for a, b in known],
        start=at(start),
        end=at(end),
        paused_at_start=paused_at_start,
        min_gap_seconds=60,
    )


# --- the coverage rule ---------------------------------------------------------------


def test_heartbeats_while_active_leave_no_gap() -> None:
    result = coverage(heartbeats(-60, 0), active=[(-60, 0)])
    assert result.unobserved == () and result.unjudged == ()


def test_active_with_no_captures_is_unobserved_beyond_the_tolerance() -> None:
    records = heartbeats(-60, -40) + heartbeats(-20, 0)
    result = coverage(records, active=[(-60, 0)])
    tolerance = CAPTURE_TOLERANCE.total_seconds() / 60
    assert result.unobserved == gaps((-40 + tolerance, -20 - tolerance))
    assert result.unjudged == ()


def test_a_short_silence_within_the_tolerance_is_not_a_gap() -> None:
    silence = CAPTURE_TOLERANCE.total_seconds() / 60 * 2
    records = heartbeats(-60, -30) + heartbeats(-30 + silence, 0)
    assert coverage(records, active=[(-60, 0)]).unobserved == ()


def test_silence_while_afk_is_not_a_gap() -> None:
    records = heartbeats(-60, -40) + heartbeats(-20, 0)
    result = coverage(records, active=[(-60, -40), (-20, 0)], idle=[(-40, -20)])
    assert result.unobserved == () and result.unjudged == ()


def test_a_paused_span_explains_active_time_until_the_resume() -> None:
    records = [
        *heartbeats(-60, -40),
        StoredRecord(at(-40), "paused"),
        StoredRecord(at(-20), "resumed"),
        *heartbeats(-20, 0),
    ]
    assert coverage(records, active=[(-60, 0)]).unobserved == ()


def test_a_pause_with_no_resume_explains_the_rest_of_the_range() -> None:
    records = [*heartbeats(-60, -40), StoredRecord(at(-40), "paused")]
    assert coverage(records, active=[(-60, 0)]).unobserved == ()


def test_a_pause_from_before_the_range_explains_its_start() -> None:
    records = [StoredRecord(at(-30), "resumed"), *heartbeats(-30, 0)]
    assert coverage(records, active=[(-60, 0)], paused_at_start=True).unobserved == ()
    unpaused = coverage(records, active=[(-60, 0)]).unobserved
    assert unpaused == gaps((-60, -30 - CAPTURE_TOLERANCE.total_seconds() / 60))


def test_excluded_records_explain_time_like_captures() -> None:
    records = heartbeats(-60, -30) + heartbeats(-30, 0, kind="excluded")
    assert coverage(records, active=[(-60, 0)]).unobserved == ()


def test_records_sharing_a_time_with_an_unknown_kind_do_not_break_the_rule() -> None:
    records = [*heartbeats(-60, -31), StoredRecord(at(-30), None), StoredRecord(at(-30), "paused")]
    assert coverage(records, active=[(-60, 0)]).unobserved == ()


def test_missing_afk_data_cannot_be_judged_and_is_never_called_active() -> None:
    records = heartbeats(-60, -40) + heartbeats(-20, 0)
    result = coverage(records, active=[(-60, -50)])
    tolerance = CAPTURE_TOLERANCE.total_seconds() / 60
    assert result.unobserved == ()
    assert result.unjudged == gaps((-40 + tolerance, -20 - tolerance))


def test_no_afk_data_at_all_leaves_the_silent_stretches_unjudged() -> None:
    records = heartbeats(-60, -50)
    result = coverage(records)
    assert result.unobserved == ()
    assert result.unjudged == gaps((-50 + CAPTURE_TOLERANCE.total_seconds() / 60, 0))


# --- liveness --------------------------------------------------------------------------


def test_a_recent_record_means_alive() -> None:
    last = NOW - AGENT_ALIVE_WITHIN + timedelta(seconds=1)
    assert liveness(last, now=NOW, paused=False, active=[]) == "yes"


def test_silence_while_active_means_not_alive() -> None:
    assert liveness(at(-30), now=NOW, paused=False, active=[(at(-40), NOW)]) == "no"


def test_silence_while_afk_or_without_afk_data_cannot_be_told() -> None:
    assert liveness(at(-30), now=NOW, paused=False, active=[]) == "unknown"
    brief = [(NOW - CAPTURE_TOLERANCE / 2, NOW)]
    assert liveness(at(-30), now=NOW, paused=False, active=brief) == "unknown"


def test_a_paused_agent_is_reported_as_paused() -> None:
    assert liveness(at(-30), now=NOW, paused=True, active=[(at(-40), NOW)]) == "paused"


# --- the spool backlog ---------------------------------------------------------------


def finished_name(when: datetime) -> str:
    return when.strftime("%Y%m%dT%H%M%S.") + f"{when.microsecond // 1000:03d}Z.jsonl"


def touch(path: Path, when: datetime, content: str = "{}\n") -> Path:
    path.write_text(content, encoding="utf-8")
    os.utime(path, (when.timestamp(), when.timestamp()))
    return path


def test_the_backlog_counts_finished_files_and_ignores_open_part_and_agent_lock(
    tmp_path: Path,
) -> None:
    spool = tmp_path / "spool"
    (spool / UNREADABLE_FOLDER).mkdir(parents=True)
    touch(spool / finished_name(at(-3)), at(-3))
    touch(spool / finished_name(at(-2)), at(-2))
    touch(spool / "open.part", at(-0.5))
    touch(spool / "agent.lock", at(0), content="")
    touch(spool / ".hidden.jsonl", at(0))
    touch(spool / UNREADABLE_FOLDER / finished_name(at(-90)), at(-90))
    touch(spool / UNREADABLE_FOLDER / ".DS_Store", at(0))

    backlog = spool_backlog(spool)

    assert backlog.waiting == 2
    assert backlog.oldest_finished_at == at(-3)
    assert backlog.unreadable == 1
    assert backlog.unstored and backlog.newest is None


def test_the_newest_record_is_the_last_usable_line_of_the_newest_file(tmp_path: Path) -> None:
    touch(tmp_path / finished_name(at(-3)), at(-3), spool_line(1, at(-4)) + "\n")
    lines = [spool_line(2, at(-2)), spool_line(3, at(-1), kind="paused"), '{"torn']
    touch(tmp_path / finished_name(at(-1)), at(-1), "\n".join(lines))
    assert spool_backlog(tmp_path).newest == (at(-1), "paused")
    touch(tmp_path / "open.part", at(0), spool_line(4, at(-0.5)) + "\n")
    assert spool_backlog(tmp_path).newest == (at(-0.5), "capture")


def test_a_garbled_open_part_falls_back_to_the_newest_finished_file(tmp_path: Path) -> None:
    touch(tmp_path / finished_name(at(-2)), at(-2), spool_line(1, at(-3), kind="paused") + "\n")
    touch(tmp_path / "open.part", at(-1), '{"torn')
    backlog = spool_backlog(tmp_path)
    assert backlog.newest == (at(-3), "paused")
    assert backlog.unstored


def test_an_empty_open_part_is_not_a_record(tmp_path: Path) -> None:
    touch(tmp_path / "open.part", at(0), content="")
    backlog = spool_backlog(tmp_path)
    assert backlog.waiting == 0 and backlog.newest is None
    assert not backlog.unstored


def test_a_missing_spool_holds_nothing(tmp_path: Path) -> None:
    backlog = spool_backlog(tmp_path / "nowhere")
    assert (backlog.waiting, backlog.oldest_finished_at, backlog.unreadable) == (0, None, 0)
    assert backlog.newest is None


# --- capture_health against a stored database ----------------------------------------


def spool_line(n: int, when: datetime, kind: str = "capture", **fields: Any) -> str:
    content = kind == "capture"
    data = {
        "version": SPOOL_VERSION,
        "id": f"00000000-0000-4000-8000-{n:012x}",
        "captured_at": when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z",
        "kind": kind,
        "trigger": None if kind in ("paused", "resumed") else "heartbeat",
        "app_name": None if kind in ("paused", "resumed") else "Editor",
        "bundle_id": None,
        "window_title": "w" if content else None,
        "text": "t" if content else None,
        "text_sha256": "0" * 64 if content else None,
        "full_text_bytes": 1 if content else None,
        "text_cut_off": False if content else None,
        "timed_out": False if content else None,
    }
    data.update(fields)
    return json.dumps(data, sort_keys=True)


def store_records(conn: sqlite3.Connection, lines: list[str]) -> None:
    observations = []
    for line in lines:
        data = json.loads(line)
        observations.append(
            Observation(AX_TEXT_SOURCE, data["id"], data["captured_at"], data["captured_at"], line)
        )
    latest = max(json.loads(line)["captured_at"] for line in lines)
    progress = ProgressUpdate(AX_TEXT_SOURCE, latest, settled_until=latest)
    insert_observations(conn, observations, project=AW, progress=progress)


def store_afk(conn: sqlite3.Connection, spans: list[tuple[datetime, datetime, str]]) -> None:
    observations = [
        Observation(
            AFK_SOURCE,
            f"{AFK_BUCKET}/{i}",
            start,
            end,
            json.dumps(
                {
                    "id": i,
                    "timestamp": start.isoformat(),
                    "duration": (end - start).total_seconds(),
                    "data": {"status": status},
                }
            ),
        )
        for i, (start, end, status) in enumerate(spans)
    ]
    insert_observations(conn, observations, project=AW)


def health(conn: sqlite3.Connection, spool: Path, client: FakeAW | None = None):
    return capture_health(
        conn,
        source_summary(conn),
        spool,
        client,
        now=NOW,
        window=timedelta(hours=24),
        min_gap_seconds=300,
        day_start=DAY_START,
    )


def test_nothing_stored_has_not_reported_but_shows_the_spool(conn, tmp_path: Path) -> None:
    touch(tmp_path / finished_name(at(-5)), at(-5))
    result = health(conn, tmp_path)
    assert not result.reported
    assert result.spool is not None and result.spool.waiting == 1


def test_counts_today_by_kind_and_flag(conn, tmp_path: Path) -> None:
    yesterday = DAY_START - timedelta(minutes=5)
    store_records(
        conn,
        [
            spool_line(1, yesterday),
            spool_line(2, at(-10)),
            spool_line(3, at(-9), text_cut_off=True),
            spool_line(4, at(-8), timed_out=True),
            spool_line(5, at(-7), text_cut_off=True, timed_out=True),
            spool_line(6, at(-6), kind="excluded"),
            spool_line(7, at(-5), kind="paused"),
            spool_line(8, at(-4), kind="resumed"),
        ],
    )
    today = health(conn, tmp_path).today
    assert (today.captures, today.excluded, today.cut_off, today.timed_out) == (4, 1, 2, 2)


def test_last_capture_ignores_later_records_of_other_kinds(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-10)), spool_line(2, at(-3), kind="excluded")])
    result = health(conn, tmp_path)
    assert result.last_capture == at(-10)
    assert result.last_record == at(-3)


def test_last_capture_does_not_depend_on_signals(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-10)), spool_line(2, at(-3), kind="excluded")])
    conn.execute("DELETE FROM signals")
    conn.commit()
    assert health(conn, tmp_path).last_capture == at(-10)


def test_a_capture_still_in_the_spool_is_the_last_capture(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-10))])
    touch(tmp_path / "open.part", at(-1), spool_line(2, at(-1)) + "\n")
    assert health(conn, tmp_path).last_capture == at(-1)


def test_paused_until_a_later_record(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-20)), spool_line(2, at(-15), kind="paused")])
    paused = health(conn, tmp_path)
    assert paused.paused_since == at(-15)
    assert paused.alive == "paused"
    store_records(conn, [spool_line(3, at(-1), kind="resumed")])
    assert health(conn, tmp_path).paused_since is None


def test_a_capture_after_a_pause_without_a_resume_ends_the_pause(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-200), kind="paused"), spool_line(2, at(-100))])
    store_afk(conn, [(at(-200), NOW, "not-afk")])
    result = health(conn, tmp_path)
    assert result.paused_since is None
    assert result.alive == "no"
    assert result.coverage is not None
    expected = [(at(-100) + CAPTURE_TOLERANCE, NOW)]
    assert [(g.start, g.end) for g in result.coverage.unobserved] == expected


def test_a_pause_still_in_the_spool_counts(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-30))])
    store_afk(conn, [(at(-30), NOW, "not-afk")])
    touch(tmp_path / "open.part", at(-20), spool_line(2, at(-20), kind="paused") + "\n")
    result = health(conn, tmp_path)
    assert result.paused_since == at(-20)
    assert result.alive == "paused"


def test_a_record_still_in_the_spool_counts_as_the_last_record(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-30))])
    touch(tmp_path / "open.part", at(-1), spool_line(2, at(-1)) + "\n")
    result = health(conn, tmp_path)
    assert result.last_record == at(-1)
    assert result.alive == "yes"


def test_silence_while_active_is_unobserved_and_not_alive(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(i, at(-120 + i / 2)) for i in range(60)])
    store_afk(conn, [(at(-120), at(-1), "not-afk")])
    result = health(conn, tmp_path)
    assert result.alive == "no"
    assert result.coverage is not None
    assert result.coverage.end == NOW
    assert [(g.start, g.end) for g in result.coverage.unobserved] == [
        (at(-120 + 59 / 2) + CAPTURE_TOLERANCE, at(-1))
    ]


def test_the_newest_afk_event_from_activitywatch_counts_before_it_is_stored(
    conn, tmp_path: Path
) -> None:
    store_records(conn, [spool_line(1, at(-60))])
    fake = FakeAW({AFK_BUCKET: "afkstatus"}, t0=at(-50))
    fake.add(AFK_BUCKET, 0, 50 * 60, {"status": "not-afk"})
    assert health(conn, tmp_path).alive == "unknown"
    result = health(conn, tmp_path, fake)
    assert result.alive == "no"
    assert result.coverage is not None and result.coverage.unobserved


@pytest.mark.parametrize("unstored", [finished_name(at(-30)), "open.part"])
def test_coverage_stops_at_stored_progress_while_the_spool_holds_records(
    conn, tmp_path: Path, unstored: str
) -> None:
    store_records(conn, [spool_line(1, at(-60)), spool_line(2, at(-40))])
    store_afk(conn, [(at(-60), NOW, "not-afk")])
    touch(tmp_path / unstored, at(-30), spool_line(3, at(-30)) + "\n")
    result = health(conn, tmp_path)
    assert result.coverage is not None
    assert result.coverage.end == at(-40)


# --- the status command ----------------------------------------------------------------


@pytest.fixture
def status_aw(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(SPOOL_ENV_VAR, raising=False)

    def install(fake: FakeAW) -> None:
        monkeypatch.setattr(cli_status, "AWClient", lambda *args, **kwargs: fake)

    return install


def run_status(capsys: pytest.CaptureFixture[str], *argv: str) -> str:
    assert cli.main(["status", *argv]) == 0
    return capsys.readouterr().out


def test_status_before_the_agent_reports(capsys, status_aw, db_path: Path) -> None:
    connect(db_path).close()
    status_aw(FakeAW({}))
    out = run_status(capsys, "--db-path", str(db_path))
    assert "Capture agent: has not reported yet (no ax-text records stored)" in out
    assert re.search(r"spool\s+0 finished files waiting, 0 in unreadable/", out)
    assert "Traceback" not in out


def test_status_reports_every_capture_agent_line(capsys, status_aw, db_path: Path) -> None:
    now = datetime.now(UTC)
    local_midnight = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    times = [max(now - timedelta(seconds=90 - i * 10), local_midnight) for i in range(4)]
    conn = connect(db_path)
    store_records(
        conn,
        [
            spool_line(1, times[0]),
            spool_line(2, times[1], text_cut_off=True),
            spool_line(3, times[2], timed_out=True),
            spool_line(4, times[3], kind="excluded"),
        ],
    )
    conn.close()
    spool = db_path.parent / "spool"
    (spool / UNREADABLE_FOLDER).mkdir(parents=True)
    touch(spool / finished_name(now - timedelta(minutes=3)), now - timedelta(minutes=3))
    touch(spool / finished_name(now - timedelta(minutes=2)), now - timedelta(minutes=2))
    touch(spool / "open.part", now, spool_line(9, now, kind="excluded") + "\n")
    touch(spool / UNREADABLE_FOLDER / "bad.jsonl", now)
    status_aw(FakeAW({}))

    out = run_status(capsys, "--db-path", str(db_path))

    assert re.search(r"last capture\s+\S+ \S+ \(1m( \d+s)? ago\)", out)
    assert re.search(r"alive\s+yes \(last record \S+ \S+ \(\d+s ago\)\)", out)
    assert re.search(
        r"spool\s+2 finished files waiting \(oldest 3m( \d+s)?\), 1 in unreadable/"
        rf"\s+\({re.escape(str(spool))}\)",
        out,
    )
    assert re.search(r"today\s+3 captures stored, 1 excluded, 1 cut off, 1 timed out", out)
    assert re.search(r"paused\s+no\n", out)


def test_status_shows_a_file_named_after_now_as_ahead(capsys, status_aw, db_path: Path) -> None:
    conn = connect(db_path)
    store_records(conn, [spool_line(1, datetime.now(UTC) - timedelta(minutes=1))])
    conn.close()
    spool = db_path.parent / "spool"
    spool.mkdir()
    later = datetime.now(UTC) + timedelta(hours=2)
    touch(spool / finished_name(later), datetime.now(UTC))
    status_aw(FakeAW({}))
    out = run_status(capsys, "--db-path", str(db_path))
    assert re.search(r"1 finished file waiting \(oldest (1h 59m|2h) ahead of now\)", out)


def test_status_reads_the_spool_flag(capsys, status_aw, db_path: Path, tmp_path: Path) -> None:
    connect(db_path).close()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    touch(elsewhere / finished_name(datetime.now(UTC)), datetime.now(UTC))
    status_aw(FakeAW({}))
    out = run_status(capsys, "--db-path", str(db_path), "--spool-path", str(elsewhere))
    assert re.search(rf"1 finished file waiting .*\({re.escape(str(elsewhere))}\)", out)


def test_status_reports_paused_and_unobserved_capture_gaps(
    capsys, status_aw, db_path: Path
) -> None:
    now = datetime.now(UTC)
    conn = connect(db_path)
    store_records(conn, [spool_line(i, now - timedelta(minutes=90 - i / 2)) for i in range(20)])
    store_afk(conn, [(now - timedelta(minutes=90), now - timedelta(minutes=30), "not-afk")])
    store_records(conn, [spool_line(99, now - timedelta(minutes=20), kind="paused")])
    conn.close()
    status_aw(FakeAW({}))

    out = run_status(capsys, "--db-path", str(db_path))

    assert "ax-text from " in out and "unobserved: aw-afk shows you active" in out
    assert re.search(
        r"warning: no ax-text coverage from .+ to .+ \((\d+m)( \d+s)?\), while you were active", out
    )
    assert re.search(r"cannot be judged: no aw-afk data", out)
    assert re.search(r"paused\s+yes, since \S+ \S+ \(20m( \d+s)? ago\)", out)
    assert "alive         paused" in out
    assert "idle" not in out.lower()
