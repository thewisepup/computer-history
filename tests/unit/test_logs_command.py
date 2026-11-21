from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cli_output import STATUS, RunCli, after_profile_line
from fake_host import FakeHost, gate_runs, installed_package

from computer_history import cli
from computer_history.logs import (
    DEV_LOG_FOLDER_NAME,
    LOG_DIR_ENV_VAR,
    LOG_FILE_NAME,
    LOG_FOLDER_NAME,
)
from computer_history.stable import stable_layout

NOW = datetime.now(UTC)


def doc(
    minutes_ago: float, level: str, logger: str, msg: str, run: str, **fields: object
) -> dict[str, object]:
    return {
        "ts": (NOW - timedelta(minutes=minutes_ago)).isoformat(timespec="milliseconds"),
        "level": level,
        "logger": f"computer_history.{logger}",
        "msg": msg,
        "run": run,
        "cmd": "ingest --watch",
        **fields,
    }


OLD = [doc(300, "info", "cli.ingest", "cycle ok: aw-afk +1", "aaaa1111")]
RECENT = [
    doc(90, "error", "cli.ingest", "cycle failed: no such table", "bbbb2222", streak=1),
    doc(30, "debug", "sources.activitywatch.pull", "event held back: still growing", "bbbb2222"),
    doc(20, "warning", "sources.capture_spool.adapter", "spool file set aside", "cccc3333"),
    doc(10, "info", "cli.ingest", "ingest recovered", "cccc3333", failed_cycles=4),
]


@pytest.fixture
def written(log_dir: Path) -> Path:
    rotated = log_dir / f"{LOG_FILE_NAME}.1"
    rotated.write_text("\n".join(json.dumps(d) for d in OLD) + "\n")
    stamp = (NOW - timedelta(hours=5)).timestamp()
    os.utime(rotated, (stamp, stamp))
    lines = [json.dumps(d) for d in RECENT]
    lines.insert(2, "{torn line")
    (log_dir / LOG_FILE_NAME).write_text("\n".join(lines) + "\n")
    return log_dir


def shown(capsys: pytest.CaptureFixture[str], *argv: str) -> list[str]:
    assert cli.main(["logs", *argv]) == 0
    return capsys.readouterr().out.splitlines()


def messages(lines: list[str]) -> list[str]:
    return [json.loads(line)["msg"] for line in lines]


def test_logs_prints_every_record_oldest_first_across_rotated_files(
    written: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = shown(capsys, "--json")

    assert messages(lines) == [d["msg"] for d in OLD + RECENT]


def test_logs_as_text_shows_the_command_run_and_plain_fields(
    written: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = shown(capsys, "--level", "error")

    [line] = lines
    assert line.endswith(
        " ERROR   cli.ingest [ingest --watch bbbb2222]  cycle failed: no such table  streak=1"
    )


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--since", "2h"], [d["msg"] for d in RECENT]),
        (["--since", "45m"], [d["msg"] for d in RECENT[1:]]),
        (["--since", (NOW - timedelta(minutes=15)).isoformat()], [RECENT[3]["msg"]]),
        (["--level", "warning"], [RECENT[0]["msg"], RECENT[2]["msg"]]),
        (["--run", "cccc3333"], [d["msg"] for d in RECENT[2:]]),
        (["--logger", "sources"], [RECENT[1]["msg"], RECENT[2]["msg"]]),
        (["--logger", "computer_history.cli"], [d["msg"] for d in OLD + RECENT[::3]]),
        (["--logger", "cli.ing"], []),
        (["--since", "1d", "--level", "error", "--run", "bbbb2222"], [RECENT[0]["msg"]]),
    ],
    ids=["2h", "45m", "iso", "level", "run", "logger", "full-logger", "no-partial-name", "all"],
)
def test_logs_filters(
    written: Path, capsys: pytest.CaptureFixture[str], argv: list[str], expected: list[str]
) -> None:
    assert messages(shown(capsys, "--json", *argv)) == expected


def test_logs_without_a_log_says_where_it_looked(
    log_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["logs"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert after_profile_line(captured.err) == f"no log records yet in {log_dir}\n"


def test_logs_rejects_an_unreadable_since(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(["logs", "--since", "yesterday"])
    assert "not an ISO date or datetime: 'yesterday'" in capsys.readouterr().err


def test_logs_skips_lines_without_a_usable_time(
    log_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = doc(5, "info", "cli.ingest", "cycle ok", "dddd4444")
    lines = [{**good, "ts": None}, {**good, "ts": "yesterday"}, {**good, "ts": "2026-11-20T10:00"}]
    rows = [json.dumps(row) for row in [*lines, good]]
    (log_dir / LOG_FILE_NAME).write_text("\n".join(rows) + "\n")

    assert len(shown(capsys)) == 1
    assert messages(shown(capsys, "--json", "--since", "1h")) == ["cycle ok"]


def test_dev_and_stable_runs_log_to_their_own_folders(
    run: RunCli, home: Path, live: Path, checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(LOG_DIR_ENV_VAR)
    host = FakeHost(checks={"b" * 40: gate_runs()})
    logs = home / "Library" / "Logs"
    assert run(checkout, "install", host=host)[0] == 0
    stable_code = installed_package(stable_layout().link.resolve().parents[1])

    assert (logs / DEV_LOG_FOLDER_NAME / LOG_FILE_NAME).is_file()
    assert not (logs / LOG_FOLDER_NAME / LOG_FILE_NAME).exists()

    assert run(stable_code, *STATUS, host=host)[0] == 0
    assert (logs / LOG_FOLDER_NAME / LOG_FILE_NAME).is_file()
    (logs / DEV_LOG_FOLDER_NAME / LOG_FILE_NAME).unlink()
    _, _, err = run(checkout, "logs", host=host)
    assert err.endswith(f"no log records yet in {logs / DEV_LOG_FOLDER_NAME}\n")
