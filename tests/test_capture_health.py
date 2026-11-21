from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Sequence
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
    APP_TOLERANCE,
    CAPTURE_KIND,
    CAPTURE_TOLERANCE,
    EXCLUDED_KIND,
    HEARTBEAT_SECONDS,
    PAUSED_KIND,
    RESUMED_KIND,
    SLEPT_KIND,
    SPOOL_ENV_VAR,
    SPOOL_VERSION,
    UNREADABLE_FOLDER,
    WINDOW_SOURCE,
    WINDOW_TEXT_SOURCE,
    WOKE_KIND,
    StoredRecord,
    app_agreement,
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
HOST = "test-host.local"
AFK_BUCKET = f"aw-watcher-afk_{HOST}"
SECRET_TITLE = "SECRET-TITLE"
SECRET_TEXT = "SECRET-TEXT"
WINDOW_BUCKET = f"aw-watcher-window_{HOST}"
OTHER_WINDOW_BUCKET = "aw-watcher-window_other-host.local"


def at(minutes: float, base: datetime = NOW) -> datetime:
    return base + timedelta(minutes=minutes)


def heartbeats(start: float, end: float, kind: str = CAPTURE_KIND) -> list[StoredRecord]:
    step = HEARTBEAT_SECONDS / 60
    return [StoredRecord(at(start + i * step), kind) for i in range(int((end - start) / step) + 1)]


def gaps(*spans: tuple[float, float]) -> tuple[Gap, ...]:
    return tuple(Gap(at(a), at(b)) for a, b in spans)


def coverage(
    records: list[StoredRecord],
    *,
    active: Sequence[tuple[float, float]] = (),
    idle: Sequence[tuple[float, float]] = (),
    start: float = -60,
    end: float = 0,
    before: StoredRecord | None = None,
):
    known = [*active, *idle]
    return capture_coverage(
        records,
        active=[(at(a), at(b)) for a, b in active],
        known=[(at(a), at(b)) for a, b in known],
        start=at(start),
        end=at(end),
        before=before,
        min_gap_seconds=60,
    )


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
        StoredRecord(at(-40), PAUSED_KIND),
        StoredRecord(at(-20), RESUMED_KIND),
        *heartbeats(-20, 0),
    ]
    assert coverage(records, active=[(-60, 0)]).unobserved == ()


def test_a_pause_with_no_resume_explains_the_rest_of_the_range() -> None:
    records = [*heartbeats(-60, -40), StoredRecord(at(-40), PAUSED_KIND)]
    assert coverage(records, active=[(-60, 0)]).unobserved == ()


def test_a_pause_from_before_the_range_explains_its_start() -> None:
    records = [StoredRecord(at(-30), RESUMED_KIND), *heartbeats(-30, 0)]
    paused = StoredRecord(at(-90), PAUSED_KIND)
    assert coverage(records, active=[(-60, 0)], before=paused).unobserved == ()
    unpaused = coverage(records, active=[(-60, 0)]).unobserved
    assert unpaused == gaps((-60, -30 - CAPTURE_TOLERANCE.total_seconds() / 60))


def test_a_sleep_explains_the_stretch_until_the_wake() -> None:
    records = [
        *heartbeats(-60, -40),
        StoredRecord(at(-40), SLEPT_KIND),
        StoredRecord(at(-20), WOKE_KIND),
        *heartbeats(-20, 0),
    ]
    result = coverage(records, active=[(-60, -40), (-20, 0)])
    assert result.unobserved == () and result.unjudged == ()


def test_a_sleep_explains_active_time_aw_afk_reports_inside_it() -> None:
    records = [*heartbeats(-60, -40), StoredRecord(at(-40), SLEPT_KIND)]
    records += [StoredRecord(at(-20), WOKE_KIND), *heartbeats(-20, 0)]
    assert coverage(records, active=[(-60, 0)]).unobserved == ()


def test_a_sleep_whose_woke_was_lost_ends_at_the_next_record() -> None:
    records = [*heartbeats(-60, -50), StoredRecord(at(-50), SLEPT_KIND), *heartbeats(-30, -25)]
    result = coverage(records, active=[(-60, -50), (-30, 0)])
    tolerance = CAPTURE_TOLERANCE.total_seconds() / 60
    assert result.unjudged == ()
    assert result.unobserved == gaps((-25 + tolerance, 0))


def test_a_sleep_from_before_the_range_explains_its_start() -> None:
    records = [StoredRecord(at(-30), WOKE_KIND), *heartbeats(-30, 0)]
    asleep = StoredRecord(at(-90), SLEPT_KIND)
    assert coverage(records, active=[(-30, 0)], before=asleep).unjudged == ()
    awake = coverage(records, active=[(-30, 0)]).unjudged
    assert awake == gaps((-60, -30 - CAPTURE_TOLERANCE.total_seconds() / 60))


def test_a_sleep_whose_woke_was_lost_ends_where_aw_afk_shows_you_active() -> None:
    slept, morning = datetime(2026, 11, 17, 18, 0, tzinfo=UTC), DAY_START
    result = capture_coverage(
        [StoredRecord(slept, SLEPT_KIND)],
        active=[(morning, morning + timedelta(hours=3))],
        known=[(morning, morning + timedelta(hours=3))],
        start=slept - timedelta(hours=1),
        end=morning + timedelta(hours=4),
        before=None,
        min_gap_seconds=60,
    )
    assert result.unobserved == (Gap(morning, morning + timedelta(hours=3)),)


def test_a_sleep_from_before_the_range_ends_where_aw_afk_shows_you_active() -> None:
    before = StoredRecord(at(-120), SLEPT_KIND)
    result = coverage([], active=[(-40, -20)], before=before)
    assert result.unobserved == gaps((-40, -20))
    assert result.unjudged == gaps((-20, 0))


def test_a_pause_from_before_the_range_explains_active_time() -> None:
    before = StoredRecord(at(-120), PAUSED_KIND)
    assert coverage([], active=[(-40, -20)], before=before).unobserved == ()


def test_excluded_records_explain_time_like_captures() -> None:
    records = heartbeats(-60, -30) + heartbeats(-30, 0, kind=EXCLUDED_KIND)
    assert coverage(records, active=[(-60, 0)]).unobserved == ()


def test_records_sharing_a_time_with_an_unknown_kind_do_not_break_the_rule() -> None:
    unknown, paused = StoredRecord(at(-30), None), StoredRecord(at(-30), PAUSED_KIND)
    records = [*heartbeats(-60, -31), unknown, paused]
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


def capture(minutes: float, app: str | None, kind: str = "capture") -> StoredRecord:
    return StoredRecord(at(minutes), kind, app=app)


def agreement(records: list[StoredRecord], spans: list[tuple[float, float, str]]):
    return app_agreement(
        records, [(at(a), at(b), app) for a, b, app in spans], start=at(-60), end=at(0)
    )


def test_a_capture_inside_a_span_of_its_app_matches_ignoring_case() -> None:
    result = agreement([capture(-30, "Cursor"), capture(-10, "google chrome")], [
        (-40, -20, "Cursor"),
        (-20, 0, "Google Chrome"),
    ])
    assert (result.matched, result.differ, result.unjudged, result.pairs) == (2, 0, 0, ())


def test_a_capture_reading_another_app_differs_and_names_the_pair() -> None:
    result = agreement([capture(-30, "Notes")], [(-40, -20, "Cursor")])
    assert (result.matched, result.differ, result.unjudged) == (0, 1, 0)
    assert result.pairs == (("Notes", "Cursor", 1),)


def test_a_switch_within_the_tolerance_still_matches() -> None:
    lag = APP_TOLERANCE.total_seconds() / 60 / 2
    records = [capture(-30, "Cursor"), capture(-30 - lag, "Notes")]
    result = agreement(records, [(-40, -30, "Notes"), (-30 + lag, -20, "Cursor")])
    assert (result.matched, result.differ) == (2, 0)


def test_a_switch_noticed_late_differs() -> None:
    late = APP_TOLERANCE.total_seconds() / 60 * 3
    result = agreement([capture(-30 + late, "Notes")], [(-40, -30, "Notes"), (-30, -20, "Cursor")])
    assert result.pairs == (("Notes", "Cursor", 1),)


def test_a_capture_with_no_span_near_it_is_unjudged_never_matched() -> None:
    away = APP_TOLERANCE.total_seconds() / 60 * 2
    result = agreement([capture(-30, "Cursor")], [(-40, -30 - away, "Cursor")])
    assert (result.matched, result.differ, result.unjudged) == (0, 0, 1)
    assert agreement([capture(-30, "Cursor")], []).unjudged == 1


def test_a_gap_between_spans_within_the_tolerance_is_judged_by_the_nearest() -> None:
    edge = APP_TOLERANCE.total_seconds() / 60 / 4
    result = agreement(
        [capture(-30, "Notes")], [(-40, -30 - edge, "Cursor"), (-30 + 3 * edge, -20, "Mail")]
    )
    assert result.pairs == (("Notes", "Cursor", 1),)


def test_only_captures_in_the_range_count() -> None:
    records = [
        capture(-61, "Cursor"),
        capture(-30, "Cursor", kind=EXCLUDED_KIND),
        StoredRecord(at(-29), PAUSED_KIND),
        StoredRecord(at(-28), RESUMED_KIND),
        capture(1, "Cursor"),
    ]
    result = agreement(records, [(-90, 10, "Notes")])
    assert (result.matched, result.differ, result.unjudged) == (0, 0, 0)


def test_the_pairs_come_most_common_first() -> None:
    records = [capture(-50, "A"), capture(-40, "B"), capture(-39, "B"), capture(-30, None)]
    result = agreement(records, [(-60, 0, "Cursor")])
    assert result.differ == 4
    assert result.pairs == (("B", "Cursor", 2), ("A", "Cursor", 1), (None, "Cursor", 1))


def test_the_spans_in_range_are_counted() -> None:
    result = agreement([capture(-30, "Cursor")], [(-90, -70, "Cursor"), (-50, -40, "Cursor")])
    assert (result.unjudged, result.spans) == (1, 1)


def test_overlapping_spans_from_two_buckets_match_either_app() -> None:
    records = [capture(-30, "Cursor"), capture(-25, "Notes")]
    result = agreement(records, [(-40, -20, "Cursor"), (-35, -20, "Notes")])
    assert (result.matched, result.differ) == (2, 0)


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
    lines = [spool_line(2, at(-2)), spool_line(3, at(-1), kind=PAUSED_KIND), '{"torn']
    touch(tmp_path / finished_name(at(-1)), at(-1), "\n".join(lines))
    assert spool_backlog(tmp_path).newest == (at(-1), "paused")
    touch(tmp_path / "open.part", at(0), spool_line(4, at(-0.5)) + "\n")
    assert spool_backlog(tmp_path).newest == (at(-0.5), "capture")


def test_a_garbled_open_part_falls_back_to_the_newest_finished_file(tmp_path: Path) -> None:
    touch(tmp_path / finished_name(at(-2)), at(-2), spool_line(1, at(-3), kind=PAUSED_KIND) + "\n")
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


SILENT_EDGES = (PAUSED_KIND, RESUMED_KIND, SLEPT_KIND, WOKE_KIND)


def spool_line(n: int, when: datetime, kind: str = CAPTURE_KIND, **fields: Any) -> str:
    content = kind == CAPTURE_KIND
    data = {
        "version": SPOOL_VERSION,
        "id": f"00000000-0000-4000-8000-{n:012x}",
        "captured_at": when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z",
        "kind": kind,
        "trigger": None if kind in SILENT_EDGES else "heartbeat",
        "app_name": None if kind in SILENT_EDGES else "Editor",
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
            Observation(
                WINDOW_TEXT_SOURCE, data["id"], data["captured_at"], data["captured_at"], line
            )
        )
    latest = max(json.loads(line)["captured_at"] for line in lines)
    progress = ProgressUpdate(WINDOW_TEXT_SOURCE, latest, settled_until=latest)
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


def store_window(
    conn: sqlite3.Connection,
    spans: list[tuple[datetime, datetime, str]],
    bucket: str = WINDOW_BUCKET,
) -> None:
    observations = [
        Observation(
            WINDOW_SOURCE,
            f"{bucket}/{i}",
            start,
            end,
            json.dumps(
                {
                    "id": i,
                    "timestamp": start.isoformat(),
                    "duration": (end - start).total_seconds(),
                    "data": {"app": app, "title": SECRET_TITLE},
                }
            ),
        )
        for i, (start, end, app) in enumerate(spans)
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
        hostname=HOST,
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
            spool_line(6, at(-6), kind=EXCLUDED_KIND),
            spool_line(7, at(-5), kind=PAUSED_KIND),
            spool_line(8, at(-4), kind=RESUMED_KIND),
            spool_line(9, at(-3), kind=SLEPT_KIND),
            spool_line(10, at(-2), kind=WOKE_KIND),
            spool_line(11, yesterday, kind=SLEPT_KIND),
        ],
    )
    today = health(conn, tmp_path).today
    assert (today.captures, today.excluded, today.cut_off, today.timed_out) == (4, 1, 2, 2)
    assert (today.slept, today.woke) == (1, 1)


def test_last_capture_ignores_later_records_of_other_kinds(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-10)), spool_line(2, at(-3), kind=EXCLUDED_KIND)])
    result = health(conn, tmp_path)
    assert result.last_capture == at(-10)
    assert result.last_record == at(-3)


def test_last_capture_does_not_depend_on_signals(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-10)), spool_line(2, at(-3), kind=EXCLUDED_KIND)])
    conn.execute("DELETE FROM signals")
    conn.commit()
    assert health(conn, tmp_path).last_capture == at(-10)


def test_a_capture_still_in_the_spool_is_the_last_capture(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-10))])
    touch(tmp_path / "open.part", at(-1), spool_line(2, at(-1)) + "\n")
    assert health(conn, tmp_path).last_capture == at(-1)


def test_paused_until_a_later_record(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-20)), spool_line(2, at(-15), kind=PAUSED_KIND)])
    paused = health(conn, tmp_path)
    assert paused.paused_since == at(-15)
    assert paused.alive == "paused"
    store_records(conn, [spool_line(3, at(-1), kind=RESUMED_KIND)])
    assert health(conn, tmp_path).paused_since is None


def test_a_capture_after_a_pause_without_a_resume_ends_the_pause(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-200), kind=PAUSED_KIND), spool_line(2, at(-100))])
    store_afk(conn, [(at(-200), NOW, "not-afk")])
    result = health(conn, tmp_path)
    assert result.paused_since is None
    assert result.alive == "no"
    assert result.coverage is not None
    expected = [(at(-100) + CAPTURE_TOLERANCE, NOW)]
    assert [(g.start, g.end) for g in result.coverage.unobserved] == expected


def test_a_sleep_before_the_window_explains_the_window_start(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-30 * 60)), spool_line(2, at(-25 * 60), kind=SLEPT_KIND)])
    store_records(conn, [spool_line(3, at(-10), kind=WOKE_KIND), spool_line(4, at(-9))])
    store_afk(conn, [(at(-10), NOW, "not-afk")])
    result = health(conn, tmp_path)
    assert result.coverage is not None and result.coverage.start == at(-24 * 60)
    assert result.coverage.unjudged == () and result.coverage.unobserved != ()
    assert result.paused_since is None


def test_a_sleep_long_before_the_window_ends_where_aw_afk_shows_you_active(
    conn, tmp_path: Path
) -> None:
    store_records(conn, [spool_line(1, at(-30 * 60), kind=SLEPT_KIND), spool_line(2, at(-1))])
    store_afk(conn, [(at(-27 * 60), at(-26 * 60), "not-afk")])
    result = health(conn, tmp_path)
    assert result.coverage is not None and result.coverage.start == at(-24 * 60)
    unjudged = [(g.start, g.end) for g in result.coverage.unjudged]
    assert unjudged == [(at(-24 * 60), at(-1) - CAPTURE_TOLERANCE)]


def test_a_pause_still_in_the_spool_counts(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-30))])
    store_afk(conn, [(at(-30), NOW, "not-afk")])
    touch(tmp_path / "open.part", at(-20), spool_line(2, at(-20), kind=PAUSED_KIND) + "\n")
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


def test_app_agreement_reads_stored_and_newest_window_spans(conn, tmp_path: Path) -> None:
    store_records(
        conn,
        [
            spool_line(1, at(-50), app_name="  Cursor "),
            spool_line(2, at(-40), app_name="Notes"),
            spool_line(3, at(-30), kind=EXCLUDED_KIND, app_name="1Password"),
            spool_line(4, at(-20), app_name="Mail"),
            spool_line(5, at(-5), app_name="Mail"),
        ],
    )
    store_window(conn, [(at(-55), at(-35), "cursor"), (at(-35), at(-25), "Safari")])
    stored_only = health(conn, tmp_path).agreement
    assert stored_only is not None
    assert (stored_only.matched, stored_only.differ, stored_only.unjudged) == (1, 1, 2)
    assert stored_only.pairs == (("Notes", "cursor", 1),)

    fake = FakeAW({WINDOW_BUCKET: "currentwindow"}, t0=at(-25))
    fake.add(WINDOW_BUCKET, 0, 25 * 60, {"app": "Mail", "title": SECRET_TITLE})
    result = health(conn, tmp_path, fake).agreement
    assert result is not None
    assert (result.matched, result.differ, result.unjudged) == (3, 1, 0)


def test_app_agreement_counts_only_this_hosts_window_buckets(conn, tmp_path: Path) -> None:
    store_records(
        conn,
        [spool_line(1, at(-50), app_name="Notes"), spool_line(2, at(-5), app_name="Notes")],
    )
    store_window(conn, [(at(-55), at(-45), "Cursor")])
    store_window(conn, [(at(-55), at(-45), "Notes")], bucket=OTHER_WINDOW_BUCKET)
    buckets = {WINDOW_BUCKET: "currentwindow", OTHER_WINDOW_BUCKET: "currentwindow"}
    fake = FakeAW(buckets, t0=at(-10))
    fake.add(OTHER_WINDOW_BUCKET, 0, 10 * 60, {"app": "Notes"})
    result = health(conn, tmp_path, fake).agreement
    assert result is not None
    assert (result.matched, result.differ, result.unjudged) == (0, 1, 1)
    assert result.pairs == (("Notes", "Cursor", 1),)


def test_one_health_check_lists_the_buckets_once(conn, tmp_path: Path) -> None:
    store_records(conn, [spool_line(1, at(-5))])
    fake = FakeAW({WINDOW_BUCKET: "currentwindow", AFK_BUCKET: "afkstatus"}, t0=at(-10))
    listings = []
    listing = fake.get_buckets

    def counted() -> dict[str, dict[str, Any]]:
        listings.append(1)
        return listing()

    fake.get_buckets = counted
    health(conn, tmp_path, fake)
    assert len(listings) == 1


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


@pytest.fixture
def status_aw(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv(SPOOL_ENV_VAR, raising=False)

    def install(fake: FakeAW) -> None:
        monkeypatch.setattr(cli_status, "AWClient", lambda *args, **kwargs: fake)
        monkeypatch.setattr(cli_status, "gethostname", lambda: HOST)

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
            spool_line(4, times[3], kind=EXCLUDED_KIND),
        ],
    )
    conn.close()
    spool = db_path.parent / "spool"
    (spool / UNREADABLE_FOLDER).mkdir(parents=True)
    touch(spool / finished_name(now - timedelta(minutes=3)), now - timedelta(minutes=3))
    touch(spool / finished_name(now - timedelta(minutes=2)), now - timedelta(minutes=2))
    touch(spool / "open.part", now, spool_line(9, now, kind=EXCLUDED_KIND) + "\n")
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
    assert re.search(
        r"today\s+3 captures stored, 1 excluded, 1 cut off, 1 timed out, 0 slept, 0 woke\n", out
    )
    assert re.search(r"paused\s+no\n", out)
    assert "still-growing" not in out


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
    store_records(conn, [spool_line(99, now - timedelta(minutes=20), kind=PAUSED_KIND)])
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


def test_status_counts_a_sleep_and_reports_no_gap_for_it(capsys, status_aw, db_path: Path) -> None:
    now = datetime.now(UTC)

    def ago(minutes: float) -> datetime:
        return now - timedelta(minutes=minutes)

    awake = [ago(60 - i / 2) for i in range(20)] + [ago(20 - i / 2) for i in range(39)]
    conn = connect(db_path)
    store_records(conn, [spool_line(i, when) for i, when in enumerate(awake)])
    store_records(conn, [spool_line(98, ago(50), kind=SLEPT_KIND)])
    store_records(conn, [spool_line(99, ago(20), kind=WOKE_KIND)])
    store_afk(conn, [(ago(60), ago(50), "not-afk"), (ago(20), now, "not-afk")])
    conn.close()
    status_aw(FakeAW({}))

    out = run_status(capsys, "--db-path", str(db_path))

    assert "not paused or asleep):\n  ax-text: no gaps since " in out
    assert re.search(r"today\s+59 captures stored, .*, 1 slept, 1 woke\n", out)
    assert re.search(r"paused\s+no\n", out)


def test_status_reports_app_agreement_with_names_only(capsys, status_aw, db_path: Path) -> None:
    now = datetime.now(UTC)
    minutes = [now - timedelta(minutes=50 - i) for i in range(10)]
    apps = ["Cursor"] * 5 + ["Notes"] * 3 + ["Mail", "Slack"]
    conn = connect(db_path)
    store_records(
        conn,
        [
            spool_line(i, when, app_name=app, window_title=SECRET_TITLE, text=SECRET_TEXT)
            for i, (when, app) in enumerate(zip(minutes, apps, strict=True))
        ],
    )
    store_window(conn, [(minutes[0], minutes[8] - timedelta(seconds=30), "Cursor")])
    conn.close()
    status_aw(FakeAW({}))

    out = run_status(capsys, "--db-path", str(db_path))

    assert re.search(
        r"app agreement 5 of 8 captures match aw-window \(3 differ, 2 without aw-window data\)\n"
        r" +3 x Notes -> Cursor\n",
        out,
    )
    leaked = [secret for secret in (SECRET_TITLE, SECRET_TEXT) if secret in out]
    assert leaked == []


def test_status_without_window_data_cannot_judge_app_agreement(
    capsys, status_aw, db_path: Path
) -> None:
    conn = connect(db_path)
    store_records(conn, [spool_line(1, datetime.now(UTC) - timedelta(minutes=5))])
    store_records(conn, [spool_line(2, datetime.now(UTC) - timedelta(minutes=4))])
    conn.close()
    status_aw(FakeAW({}))
    out = run_status(capsys, "--db-path", str(db_path))
    assert "app agreement cannot be judged: no aw-window data from this machine\n" in out


def test_status_tells_window_data_far_from_every_capture_apart(
    capsys, status_aw, db_path: Path
) -> None:
    now = datetime.now(UTC)
    conn = connect(db_path)
    store_records(conn, [spool_line(1, now - timedelta(minutes=50))])
    store_records(conn, [spool_line(2, now - timedelta(minutes=5))])
    store_window(conn, [(now - timedelta(minutes=40), now - timedelta(minutes=30), "Cursor")])
    conn.close()
    status_aw(FakeAW({}))
    out = run_status(capsys, "--db-path", str(db_path))
    assert "app agreement cannot be judged: no aw-window data near any capture\n" in out
