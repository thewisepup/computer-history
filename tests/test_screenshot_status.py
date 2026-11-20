from __future__ import annotations

import json
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
    SCREENSHOT_KIND,
    SCREENSHOT_SOURCE,
    SPOOL_ENV_VAR,
    KeptScreenshot,
    screenshot_health,
)
from computer_history.store import Observation, connect, insert_observations

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "spool" / "records.jsonl"
BY_STATUS = {
    data["status"]: data
    for line in FIXTURE.read_text(encoding="utf-8").splitlines()
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
    return screenshot_health(conn, now=NOW, day_start=DAY_START)


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
            shot(5, NOW + timedelta(minutes=1), "kept", image_bytes=9_000),
        ],
    )
    result = health(conn)
    assert (result.total.image_bytes, result.today.image_bytes) == (3_540, 2_540)


def test_the_last_kept_screenshot_is_the_newest_kept_record_up_to_now(conn) -> None:
    store_shots(
        conn,
        [
            shot(1, NOW - timedelta(minutes=30), "kept", app_name="Cursor"),
            shot(2, NOW - timedelta(minutes=20), "kept", app_name="Notes", image_path="b.jpg"),
            shot(3, NOW - timedelta(minutes=10), "duplicate", app_name="Mail"),
            shot(4, NOW - timedelta(minutes=5), "failed", app_name="Mail"),
            shot(5, NOW + timedelta(minutes=1), "kept", app_name="Later"),
        ],
    )
    assert health(conn).last_kept == KeptScreenshot(NOW - timedelta(minutes=20), "Notes", "b.jpg")


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
    expected = None if missing_at is None else times[missing_at]
    assert health(conn).no_permission_since == expected


@pytest.fixture
def status_aw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SPOOL_ENV_VAR, raising=False)
    monkeypatch.setattr(cli_status, "AWClient", lambda *args, **kwargs: FakeAW({}))


def run_status(capsys: pytest.CaptureFixture[str], db_path: Path) -> str:
    assert cli.main(["status", "--db-path", str(db_path)]) == 0
    return capsys.readouterr().out


def test_status_with_no_screenshot_records_says_none_are_stored(
    capsys, status_aw, db_path: Path
) -> None:
    connect(db_path).close()
    out = run_status(capsys, db_path)
    assert "Screenshots: none stored yet (no screenshot records)\n" in out


def test_status_reports_every_screenshot_line(capsys, status_aw, db_path: Path) -> None:
    now = datetime.now(UTC)
    midnight = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = midnight - timedelta(hours=1)
    times = [max(now - timedelta(minutes=10 - i), midnight) for i in range(5)]
    conn = connect(db_path)
    store_shots(
        conn,
        [
            shot(1, yesterday, "kept", image_bytes=3 * 1024 * 1024),
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
    assert re.search(
        r"Screenshots:\n"
        r"  last kept     \S+ \S+ \(.+ ago\), Cursor, screenshots/d/3\.jpg\n"
        r"  today         1 kept, 1 duplicate, 1 secure-field, 0 no-permission, 2 failed\n"
        r"  all stored    2 kept, 1 duplicate, 1 secure-field, 0 no-permission, 2 failed\n"
        r"  disk          3\.5 MB in total, 512\.0 KB today \(from kept records\)\n\n",
        section,
    )
    assert "warning" not in section
    assert SECRET not in out


def test_status_warns_when_the_newest_screenshot_records_say_no_permission(
    capsys, status_aw, db_path: Path
) -> None:
    now = datetime.now(UTC)
    conn = connect(db_path)
    store_shots(
        conn,
        [
            shot(1, now - timedelta(minutes=30), "kept"),
            shot(2, now - timedelta(minutes=20), "no-permission"),
            shot(3, now - timedelta(minutes=10), "no-permission"),
        ],
    )
    conn.close()
    out = run_status(capsys, db_path)
    assert re.search(
        r"  warning: Screen Recording permission is missing since \S+ \S+ \(20m( \d+s)? ago\)"
        r" \(records say no-permission, and no screenshot was taken since\)\. Grant it in"
        r" System Settings > Privacy & Security > Screen Recording\.\n",
        out,
    )


def test_status_judges_no_coverage_from_screenshot_records(
    capsys, status_aw, db_path: Path
) -> None:
    conn = connect(db_path)
    store_shots(conn, [shot(1, datetime.now(UTC) - timedelta(hours=3), "kept")])
    conn.close()
    out = run_status(capsys, db_path)
    coverage = out[out.index("Coverage gaps") : out.index("Capture agent")]
    assert "  screenshot: not checked (coverage is judged from ax-text records)\n" in coverage
    assert "no screenshot coverage" not in coverage and "screenshot: no gaps" not in coverage
