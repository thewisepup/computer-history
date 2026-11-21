from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from computer_history.cli import main
from computer_history.logs import (
    LOG_BACKUPS,
    LOG_FILE_NAME,
    LOG_LEVEL_ENV_VAR,
    configure,
    escape,
    log_files,
    text_line,
)
from computer_history.logs import config as config_module

log = logging.getLogger("computer_history.tests")
UNREACHABLE = "http://127.0.0.1:9"
HOSTILE_TITLE = "PR #96\nignore previous instructions\x1b[31m\u2028end"


def records(log_dir: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in (log_dir / LOG_FILE_NAME).read_text().splitlines()]


def test_a_json_record_carries_the_run_the_command_and_its_fields(log_dir: Path) -> None:
    configure("ingest", level=logging.INFO, stderr_level=logging.WARNING, log_dir=log_dir)
    log.info("cycle ok", extra={"duration_ms": 412, "streams": {"aw-afk": {"inserted": 0}}})
    try:
        raise ValueError("no such table: ingest_progress")
    except ValueError:
        log.exception("cycle failed", extra={"streak": 1})

    first, second = records(log_dir)
    assert set(first) == {"ts", "level", "logger", "msg", "run", "cmd", "duration_ms", "streams"}
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00", str(first["ts"]))
    assert (first["level"], first["logger"], first["msg"]) == ("info", log.name, "cycle ok")
    assert first["cmd"] == "ingest" and re.fullmatch(r"[0-9a-f]{8}", str(first["run"]))
    assert first["streams"] == {"aw-afk": {"inserted": 0}}
    assert second["run"] == first["run"] and second["streak"] == 1
    assert "ValueError: no such table: ingest_progress" in str(second["exc"])


def test_each_configure_starts_a_new_run(log_dir: Path) -> None:
    configure("ingest", level=logging.INFO, stderr_level=logging.WARNING, log_dir=log_dir)
    log.info("one")
    configure("status", level=logging.INFO, stderr_level=logging.WARNING, log_dir=log_dir)
    log.info("two")

    one, two = records(log_dir)
    assert one["run"] != two["run"] and (one["cmd"], two["cmd"]) == ("ingest", "status")


def test_captured_text_cannot_break_a_record_into_lines(
    log_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure("ingest", level=logging.DEBUG, stderr_level=logging.DEBUG, log_dir=log_dir)
    log.debug("event held back", extra={"event_id": 88214, "title": HOSTILE_TITLE})

    lines = (log_dir / LOG_FILE_NAME).read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["title"] == HOSTILE_TITLE
    err = capsys.readouterr().err
    assert err.count("\n") == 1
    assert '"PR #96\\x0aignore previous instructions\\x1b[31m\\u2028end"' in err


def test_escape_writes_controls_and_invisible_marks_as_escapes() -> None:
    assert escape("a\tb\r\n\x00\x7f\x85\u200b\u202e\ufeffz") == (
        "a\\x09b\\x0d\\x0a\\x00\\x7f\\x85\\u200b\\u202e\\ufeffz"
    )
    assert escape("Café — naïve 日本") == "Café — naïve 日本"


def test_the_text_line_shows_the_message_and_plain_fields_but_not_nested_ones() -> None:
    doc = {
        "ts": "2026-11-20T14:00:00.000+00:00",
        "level": "error",
        "logger": "computer_history.cli.ingest",
        "msg": "cycle failed",
        "run": "ab12cd34",
        "cmd": "ingest --watch",
        "streak": 3,
        "error": "database error: no such table",
        "streams": {"aw-afk": {"inserted": 0}},
        "exc": "Traceback (most recent call last):\nValueError: boom\n2026-11-20 forged line",
    }
    local = datetime(2026, 11, 20, 14, tzinfo=UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S")

    line = text_line(doc, with_run=True)

    head, *traceback = line.split("\n")
    assert head == (
        f"{local} ERROR   cli.ingest [ingest --watch ab12cd34]  cycle failed"
        '  streak=3 error="database error: no such table"'
    )
    assert traceback == [
        "  | Traceback (most recent call last):",
        "  | ValueError: boom",
        "  | 2026-11-20 forged line",
    ]


def test_without_tracebacks_the_text_line_ends_with_the_exception_alone() -> None:
    doc = {
        "ts": "2026-11-20T14:00:00.000+00:00",
        "level": "error",
        "logger": "computer_history.cli.ingest",
        "msg": "cycle failed",
        "exc": "Traceback (most recent call last):\nsqlite3.OperationalError: no such table: x",
    }

    line = text_line(doc, tracebacks=False)

    assert line.endswith('cycle failed  exc="sqlite3.OperationalError: no such table: x"')
    assert "\n" not in line


def test_commands_with_their_own_output_keep_info_out_of_stderr(
    log_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure("backfill", level=logging.INFO, stderr_level=logging.WARNING, log_dir=log_dir)
    log.info("backfill started")
    log.warning("bucket has no usable created time")

    err = capsys.readouterr().err
    assert "backfill started" not in err and "no usable created time" in err
    assert [r["msg"] for r in records(log_dir)] == [
        "backfill started",
        "bucket has no usable created time",
    ]


def test_the_log_level_flag_sets_both_outputs(
    log_dir: Path, db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--log-level", "debug", "status", "--db-path", str(db_path), "--aw-url", UNREACHABLE])
    log.debug("probe")

    assert "probe" in capsys.readouterr().err
    assert records(log_dir)[-1]["msg"] == "probe"


def test_an_unknown_level_in_the_environment_is_refused(
    monkeypatch: pytest.MonkeyPatch, db_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(LOG_LEVEL_ENV_VAR, "chatty")

    assert main(["status", "--db-path", str(db_path)]) == 2
    assert "unknown log level 'chatty'" in capsys.readouterr().err


def test_an_unusable_log_folder_leaves_stderr_logging(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocked = tmp_path / "a-file"
    blocked.write_text("")

    path = configure("ingest", level=logging.INFO, stderr_level=logging.INFO, log_dir=blocked)
    assert path is None
    log.info("still logged")

    err = capsys.readouterr().err
    assert "log file unavailable" in err and "still logged" in err


def test_the_log_file_rotates_within_its_bound(
    log_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config_module, "MAX_LOG_BYTES", 2_000)
    configure("ingest", level=logging.INFO, stderr_level=logging.ERROR, log_dir=log_dir)
    for n in range(500):
        log.info("cycle ok", extra={"n": n})

    files = log_files(log_dir)
    assert len(files) == LOG_BACKUPS + 1 and files[-1].name == LOG_FILE_NAME
    assert all(path.stat().st_size <= 2_000 for path in files)
    assert records(log_dir)[-1]["n"] == 499
