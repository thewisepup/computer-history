from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fake_aw import FakeAW
from projectors import AW

from computer_history import cli
from computer_history.cli import status as cli_status
from computer_history.sources import (
    AGENT_ALIVE_WITHIN,
    SCREENSHOT_KIND,
    SCREENSHOT_SOURCE,
    SPOOL_ENV_VAR,
    WINDOW_TEXT_SOURCE,
    KeptScreenshot,
    MissingPermission,
    screenshot_health,
)
from computer_history.store import (
    SCREENSHOT_STATUS_INDEX,
    Observation,
    connect,
    insert_observations,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "spool" / "records.jsonl"
FIXTURE_LINES = FIXTURE.read_text(encoding="utf-8").splitlines()
BY_STATUS = {
    data["status"]: data
    for line in FIXTURE_LINES
    if (data := json.loads(line))["kind"] == SCREENSHOT_KIND
}
NOW = datetime(2026, 11, 18, 18, 0, tzinfo=UTC)
DAY_START = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)
SECRET = "SECRET-TEXT"


def shot(n: int, when: datetime, status: str, **fields: Any) -> str:
    data = dict(BY_STATUS[status])
    at = when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"
    data.update(id=f"00000000-0000-4000-8000-{n:012x}", captured_at=at, **fields)
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


def store_shots(conn: sqlite3.Connection, lines: list[str]) -> None:
    observations = []
    for line in lines:
        data = json.loads(line)
        at = data["captured_at"]
        observations.append(Observation(SCREENSHOT_SOURCE, data["id"], at, at, line))
    insert_observations(conn, observations, project=AW)


def health(conn: sqlite3.Connection):
    return screenshot_health(conn, day_start=DAY_START, now=NOW)


def test_counts_records_by_status_in_total_and_since_the_day_began(conn) -> None:
    yesterday, today = DAY_START - timedelta(hours=1), DAY_START + timedelta(hours=1)
    store_shots(
        conn,
        [
            shot(1, yesterday, "kept"),
            shot(2, yesterday, "failed"),
            shot(3, today, "kept"),
            shot(4, today, "duplicate"),
            shot(5, today, "duplicate"),
            shot(6, today, "secure-field"),
            shot(7, today, "no-permission"),
        ],
    )
    result = health(conn)
    assert result.reported
    assert result.total.statuses == {
        "kept": 2,
        "duplicate": 2,
        "secure-field": 1,
        "no-permission": 1,
        "failed": 1,
    }
    assert result.today.statuses == {
        "kept": 1,
        "duplicate": 2,
        "secure-field": 1,
        "no-permission": 1,
        "failed": 0,
    }


def test_disk_use_sums_the_image_bytes_of_kept_records_in_total_and_today(conn) -> None:
    yesterday, today = DAY_START - timedelta(minutes=1), DAY_START + timedelta(minutes=1)
    store_shots(
        conn,
        [
            shot(1, yesterday, "kept", image_bytes=1_000),
            shot(2, today, "kept", image_bytes=2_500),
            shot(3, today, "kept", image_bytes=40),
            shot(4, today, "duplicate"),
        ],
    )
    result = health(conn)
    assert (result.total.image_bytes, result.today.image_bytes) == (3_540, 2_540)


def test_the_last_kept_screenshot_is_the_newest_kept_record(conn) -> None:
    store_shots(
        conn,
        [
            shot(1, NOW - timedelta(minutes=30), "kept", app_name="Cursor"),
            shot(2, NOW - timedelta(minutes=20), "kept", app_name="Notes", image_path="b.jpg"),
            shot(3, NOW - timedelta(minutes=10), "duplicate", app_name="Mail"),
            shot(4, NOW - timedelta(minutes=5), "failed", app_name="Mail"),
        ],
    )
    assert health(conn).last_kept == KeptScreenshot(NOW - timedelta(minutes=20), "Notes", "b.jpg")


def test_records_dated_after_now_still_count_as_stored(conn) -> None:
    ahead = NOW + timedelta(hours=2)
    store_shots(conn, [shot(1, ahead, "kept", image_bytes=500), shot(2, ahead, "failed")])
    result = health(conn)
    assert result.reported
    assert result.last_kept is not None and result.last_kept.at == ahead
    assert result.total.statuses["kept"] == result.today.statuses["failed"] == 1
    assert result.total.image_bytes == result.today.image_bytes == 500


def test_a_kept_record_dated_after_now_still_clears_the_permission_warning(conn) -> None:
    store_shots(
        conn,
        [
            shot(1, NOW - timedelta(minutes=5), "no-permission"),
            shot(2, NOW + timedelta(minutes=5), "kept"),
        ],
    )
    assert health(conn).no_permission is None


def test_with_nothing_kept_there_is_no_last_kept_screenshot(conn) -> None:
    store_shots(conn, [shot(1, NOW, "secure-field")])
    result = health(conn)
    assert result.reported and result.last_kept is None


@pytest.mark.parametrize(
    ("statuses", "missing_at"),
    [
        (["no-permission"], 0),
        (["kept", "no-permission"], 1),
        (["duplicate", "no-permission", "no-permission"], 1),
        (["kept", "no-permission", "secure-field", "failed"], 1),
        (["no-permission", "kept"], None),
        (["no-permission", "duplicate"], None),
        (["kept", "failed", "secure-field"], None),
    ],
)
def test_permission_is_missing_while_no_kept_or_duplicate_record_follows_a_no_permission_one(
    conn, statuses: list[str], missing_at: int | None
) -> None:
    times = [NOW - timedelta(minutes=10 - i) for i in range(len(statuses))]
    store_shots(conn, [shot(i, t, s) for i, (t, s) in enumerate(zip(times, statuses, strict=True))])
    missing = health(conn).no_permission
    assert (None if missing is None else missing.since) == (
        None if missing_at is None else times[missing_at]
    )


@pytest.mark.parametrize(
    ("age", "current"),
    [
        (timedelta(0), True),
        (AGENT_ALIVE_WITHIN, True),
        (AGENT_ALIVE_WITHIN + timedelta(seconds=1), False),
        (timedelta(days=1), False),
    ],
)
def test_a_missing_permission_is_current_only_while_its_newest_record_is_recent(
    conn, age: timedelta, current: bool
) -> None:
    first, last = NOW - age - timedelta(minutes=1), NOW - age
    store_shots(conn, [shot(1, first, "no-permission"), shot(2, last, "no-permission")])
    assert health(conn).no_permission == MissingPermission(first, last, current)


def test_every_screenshot_query_reads_only_the_screenshot_status_index(conn) -> None:
    store_shots(conn, [shot(1, NOW, "kept"), shot(2, NOW, "no-permission"), shot(3, NOW, "failed")])
    executed: list[str] = []
    conn.set_trace_callback(executed.append)
    health(conn)
    conn.set_trace_callback(None)
    plans = {sql: [row[3] for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}")] for sql in executed}
    allowed = (f"INDEX {SCREENSHOT_STATUS_INDEX} ", "INTEGER PRIMARY KEY (rowid=?)")
    unindexed = {
        sql: steps
        for sql, steps in plans.items()
        if any("observations" in step and not any(a in step for a in allowed) for step in steps)
    }
    assert executed and unindexed == {}


ZONE = "America/Los_Angeles"
CLI_NOW = datetime(2026, 11, 18, 20, 0, tzinfo=UTC)
CLI_MIDNIGHT = datetime(2026, 11, 18, 8, 0, tzinfo=UTC)


@pytest.fixture
def local_zone() -> Iterator[Callable[[str], None]]:
    saved = os.environ.get("TZ")

    def use(name: str) -> None:
        os.environ["TZ"] = name
        time.tzset()

    yield use
    if saved is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = saved
    time.tzset()


@pytest.fixture
def status_at(
    monkeypatch: pytest.MonkeyPatch, local_zone: Callable[[str], None]
) -> Callable[[datetime], None]:
    monkeypatch.delenv(SPOOL_ENV_VAR, raising=False)
    monkeypatch.setattr(cli_status, "AWClient", lambda *args, **kwargs: FakeAW({}))
    local_zone(ZONE)

    def at(now: datetime) -> None:
        monkeypatch.setattr(cli_status, "utc_now", lambda: now)

    at(CLI_NOW)
    return at


def run_status(capsys: pytest.CaptureFixture[str], db_path: Path) -> str:
    assert cli.main(["status", "--db-path", str(db_path)]) == 0
    return capsys.readouterr().out


def store_captures(conn: sqlite3.Connection, times: list[datetime]) -> None:
    capture = next(json.loads(line) for line in FIXTURE_LINES if '"kind":"capture"' in line)
    observations = []
    for n, when in enumerate(times, start=100):
        at = when.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        data = {**capture, "id": f"00000000-0000-4000-8000-{n:012x}", "captured_at": at}
        observations.append(Observation(WINDOW_TEXT_SOURCE, data["id"], at, at, json.dumps(data)))
    insert_observations(conn, observations, project=AW)


def test_status_with_no_screenshot_records_says_none_are_stored(
    capsys, status_at, db_path: Path
) -> None:
    connect(db_path).close()
    out = run_status(capsys, db_path)
    assert "Screenshots: none stored yet (no screenshot records)\n" in out


def test_status_reports_every_screenshot_line(capsys, status_at, db_path: Path) -> None:
    times = [CLI_NOW - timedelta(minutes=10 - i) for i in range(5)]
    conn = connect(db_path)
    store_shots(
        conn,
        [
            shot(1, CLI_MIDNIGHT - timedelta(seconds=1), "kept", image_bytes=3 * 1024 * 1024),
            shot(2, times[0], "secure-field"),
            shot(
                3,
                times[1],
                "kept",
                app_name="Cursor",
                image_path="screenshots/d/3.jpg",
                image_bytes=512 * 1024,
                window_title=SECRET,
            ),
            shot(4, times[2], "duplicate", text=SECRET),
            shot(5, times[3], "failed"),
            shot(6, times[4], "failed"),
        ],
    )
    conn.close()

    out = run_status(capsys, db_path)

    section = out[out.index("Screenshots:") :]
    assert section.startswith(
        "Screenshots:\n"
        "  last kept     2026-11-18 11:51 (9m ago), Cursor, screenshots/d/3.jpg\n"
        "  today         1 kept, 1 duplicate, 1 secure-field, 0 no-permission, 2 failed\n"
        "  all stored    2 kept, 1 duplicate, 1 secure-field, 0 no-permission, 2 failed\n"
        "  disk          3.5 MB in total, 512.0 KB today (from kept records)\n\n"
    )
    assert "warning" not in section
    assert SECRET not in out


def test_status_warns_when_the_newest_screenshot_records_say_no_permission(
    capsys, status_at, db_path: Path
) -> None:
    conn = connect(db_path)
    store_shots(
        conn,
        [
            shot(1, CLI_NOW - timedelta(minutes=30), "kept"),
            shot(2, CLI_NOW - timedelta(minutes=20), "no-permission"),
            shot(3, CLI_NOW - timedelta(minutes=2), "no-permission"),
        ],
    )
    conn.close()
    out = run_status(capsys, db_path)
    assert (
        "  warning: Screen Recording permission is missing since 2026-11-18 11:40 (20m ago)"
        " (records say no-permission, and no screenshot was taken since). Grant it in"
        " System Settings > Privacy & Security > Screen Recording.\n"
    ) in out


def test_status_only_mentions_a_missing_permission_once_no_screenshot_record_is_recent(
    capsys, status_at, db_path: Path
) -> None:
    conn = connect(db_path)
    store_shots(
        conn,
        [
            shot(1, CLI_NOW - timedelta(minutes=30), "kept"),
            shot(2, CLI_NOW - timedelta(minutes=20), "no-permission"),
            shot(3, CLI_NOW - timedelta(minutes=10), "no-permission"),
        ],
    )
    conn.close()
    out = run_status(capsys, db_path)
    section = out[out.index("Screenshots:") :]
    assert "warning" not in section
    assert (
        "  permission    last recorded missing 2026-11-18 11:50 (10m ago), missing since"
        " 2026-11-18 11:40 (20m ago); no screenshot record since says whether it is held\n"
    ) in section


@pytest.mark.parametrize(
    ("now", "last_hour_of_yesterday", "first_hour_of_today"),
    [
        (
            datetime(2026, 3, 8, 19, 0, tzinfo=UTC),
            datetime(2026, 3, 8, 7, 30, tzinfo=UTC),
            datetime(2026, 3, 8, 8, 30, tzinfo=UTC),
        ),
        (
            datetime(2026, 11, 1, 20, 0, tzinfo=UTC),
            datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
            datetime(2026, 11, 1, 7, 30, tzinfo=UTC),
        ),
    ],
    ids=["clocks-go-forward", "clocks-go-back"],
)
def test_today_starts_at_local_midnight_on_a_daylight_saving_changeover_day(
    capsys,
    status_at,
    db_path: Path,
    now: datetime,
    last_hour_of_yesterday: datetime,
    first_hour_of_today: datetime,
) -> None:
    status_at(now)
    conn = connect(db_path)
    store_shots(
        conn, [shot(1, last_hour_of_yesterday, "kept"), shot(2, first_hour_of_today, "kept")]
    )
    store_captures(conn, [last_hour_of_yesterday, first_hour_of_today])
    conn.close()

    out = run_status(capsys, db_path)

    assert "  today         1 kept, 0 duplicate," in out
    assert "  today         1 captures stored," in out


def test_status_judges_no_coverage_from_screenshot_records(
    capsys, status_at, db_path: Path
) -> None:
    conn = connect(db_path)
    store_shots(conn, [shot(1, CLI_NOW - timedelta(hours=3), "kept")])
    store_captures(conn, [CLI_NOW - timedelta(hours=3), CLI_NOW - timedelta(hours=2)])
    conn.close()
    out = run_status(capsys, db_path)
    coverage = out[out.index("Coverage gaps") : out.index("Capture agent")]
    assert "  screenshot: not checked (coverage is judged from ax-text records)\n" in coverage
    assert "no screenshot coverage" not in coverage and "screenshot: no gaps" not in coverage


def test_without_an_ax_text_coverage_check_the_screenshot_source_is_not_mentioned_in_coverage(
    capsys, status_at, db_path: Path
) -> None:
    conn = connect(db_path)
    store_shots(conn, [shot(1, CLI_NOW - timedelta(hours=3), "kept")])
    conn.close()
    out = run_status(capsys, db_path)
    coverage = out[out.index("Coverage gaps") : out.index("Capture agent")]
    assert "screenshot" not in coverage
