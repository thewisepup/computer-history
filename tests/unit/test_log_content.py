from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fake_aw import FakeAW

from computer_history import cli
from computer_history.cli import ingest as cli_ingest
from computer_history.logs import LOG_FILE_NAME

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "spool" / "records.jsonl"
FIXTURE_LINES = FIXTURE.read_text(encoding="utf-8").splitlines()
WINDOW_BUCKET = "aw-watcher-window_test-host.local"
WEB_BUCKET = "aw-watcher-web-chrome"
HELD_TITLE = "Draft: offer letter for Jordan"
AW_TITLES = ["Q3 salaries.xlsx", "Inbox (3) - private@example.com", HELD_TITLE]
SECRET_URL = "https://bank.example.com/accounts/4417"


def captured_text() -> set[str]:
    found = set(AW_TITLES) | {SECRET_URL}
    for line in FIXTURE_LINES:
        record = json.loads(line)
        found |= {record[k] for k in ("window_title", "text") if isinstance(record.get(k), str)}
    return {text for text in found if len(text) >= 4}


def aw_with_titles(now: datetime) -> FakeAW:
    fake = FakeAW({WINDOW_BUCKET: "currentwindow", WEB_BUCKET: "web.tab.current"}, t0=now)
    fake.add(WINDOW_BUCKET, -30, 60, {"app": "Excel", "title": AW_TITLES[0]})
    fake.add(WINDOW_BUCKET, -20, 60, {"app": "Mail", "title": AW_TITLES[1]})
    fake.add(WINDOW_BUCKET, -1, 120, {"app": "Pages", "title": HELD_TITLE})
    fake.add(WEB_BUCKET, -10, 30, {"url": SECRET_URL, "title": "Accounts", "audible": False})
    fake.events[WEB_BUCKET].append({"id": 99, "timestamp": "never", "data": {"url": SECRET_URL}})
    return fake


def ingest_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *flags: str) -> None:
    spool = tmp_path / "spool"
    spool.mkdir(exist_ok=True)
    bad = json.loads(FIXTURE_LINES[1]) | {"text": [AW_TITLES[0]]}
    (spool / "20261118T090000.000Z.jsonl").write_text(
        "\n".join([*FIXTURE_LINES, json.dumps(bad), "{broken"]) + "\n", encoding="utf-8"
    )
    fake = aw_with_titles(datetime.now(UTC))
    monkeypatch.setattr(cli_ingest, "AWClient", lambda *args, **kwargs: fake)
    db = tmp_path / "history.db"
    cli.main([*flags, "--db-path", str(db), "ingest", "--spool-path", str(spool)])


def leaks(records: list[dict[str, object]]) -> list[tuple[str, str]]:
    secrets = captured_text()
    return [
        (str(record["msg"]), secret)
        for record in records
        for secret in secrets
        if secret in json.dumps(record, ensure_ascii=False)
    ]


def test_an_ingest_at_info_logs_no_captured_title_url_or_text(
    tmp_path: Path,
    log_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.INFO)

    ingest_once(tmp_path, monkeypatch)

    written = [json.loads(line) for line in (log_dir / LOG_FILE_NAME).read_text().splitlines()]
    levels = {record["level"] for record in written}
    assert "info" in levels and "warning" in levels and "debug" not in levels
    assert leaks(written) == []
    captured = [vars(r) | {"msg": r.getMessage()} for r in caplog.records]
    assert leaks([{k: str(v) for k, v in r.items()} for r in captured]) == []
    assert not any(secret in capsys.readouterr().err for secret in captured_text())


def test_the_same_ingest_at_debug_shows_what_was_held_back_and_why_lines_were_refused(
    tmp_path: Path, log_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ingest_once(tmp_path, monkeypatch, "--log-level", "debug")

    written = [json.loads(line) for line in (log_dir / LOG_FILE_NAME).read_text().splitlines()]
    held = [r for r in written if r["msg"] == "event held back: still growing"]
    assert [(r["bucket"], r["title"]) for r in held if r["bucket"] == WINDOW_BUCKET] == [
        (WINDOW_BUCKET, HELD_TITLE)
    ]
    assert {r["level"] for r in written if leaks([r])} == {"debug"}
    refused = [r for r in written if r["msg"] == "unusable spool record"]
    assert any(AW_TITLES[0] in str(r["error"]) for r in refused)
