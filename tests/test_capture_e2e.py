from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from computer_history.cli.formatting import human_size
from computer_history.sources.capture_spool import (
    MAX_AX_TEXT_LENGTH,
    SPOOL_ENV_VAR,
    resolve_spool_path,
)
from computer_history.store import DB_ENV_VAR, resolve_db_path
from computer_history.store.timefmt import to_utc

AGENT_ENV_VAR = "CAPTURE_AGENT_BINARY"
REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "capture-agent" / "e2e"
CONTRACT = REPO / "fixtures" / "spool" / "records.jsonl"
CLI = Path(sys.executable).with_name("computer-history")

pytestmark = pytest.mark.skipif(
    not os.environ.get(AGENT_ENV_VAR),
    reason=f"needs the built capture agent in ${AGENT_ENV_VAR}; run capture-agent/scripts/e2e.sh",
)

TORN_TAIL = b'{"version":1,"id":"torn'

EXPECTED = [
    ("capture", "heartbeat", "TextEdit"),
    ("capture", "heartbeat", "TextEdit"),
    ("capture", "heartbeat", "TextEdit"),
    ("capture", "heartbeat", "TextEdit"),
    ("capture", "app", "Google Chrome"),
    ("capture", "title", "Google Chrome"),
    ("capture", "window", "Google Chrome"),
    ("capture", "app", "Cursor"),
    ("capture", "app", "Calculator"),
    ("excluded", "app", "1Password"),
    ("excluded", "heartbeat", "1Password"),
    ("capture", "app", "TextEdit"),
    ("paused", None, None),
    ("resumed", None, None),
    ("capture", "app", "Google Chrome"),
    ("capture", "heartbeat", "Google Chrome"),
]


@dataclass(frozen=True)
class Session:
    folder: Path
    spool: Path
    db: Path
    crash_run: subprocess.CompletedProcess[str]
    run: subprocess.CompletedProcess[str]
    spool_lines: list[str]
    modes: dict[str, int]
    ingests: list[subprocess.CompletedProcess[str]]
    row_counts: list[int]
    status: subprocess.CompletedProcess[str]

    def records(self) -> list[dict]:
        with sqlite3.connect(self.db) as conn:
            rows = conn.execute(
                "SELECT payload FROM observations WHERE source = 'ax-text' ORDER BY started_at"
            ).fetchall()
        return [json.loads(payload) for (payload,) in rows]

    def screenshots(self) -> list[dict]:
        with sqlite3.connect(self.db) as conn:
            rows = conn.execute(
                "SELECT payload FROM observations WHERE source = 'screenshot' ORDER BY started_at"
            ).fetchall()
        return [json.loads(payload) for (payload,) in rows]

    def payloads(self) -> list[str]:
        with sqlite3.connect(self.db) as conn:
            return [p for (p,) in conn.execute("SELECT payload FROM observations")]

    def signals(self) -> dict[str, tuple]:
        with sqlite3.connect(self.db) as conn:
            rows = conn.execute(
                "SELECT o.source_id, s.app, s.title, s.text, s.extras"
                " FROM signals s JOIN observations o ON o.id = s.observation_id"
                " WHERE s.source = 'ax-text'"
            ).fetchall()
        return {row[0]: row[1:] for row in rows}


class EmptyActivityWatch(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"{}" if self.path.startswith("/api/0/buckets/") else b""
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return None


def _agent(script: str, folder: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("COMPUTER_HISTORY_")}
    env["COMPUTER_HISTORY_DB"] = str(folder / "history.db")
    run = subprocess.run(
        [os.environ[AGENT_ENV_VAR], "scripted-session", str(SCRIPTS / script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, f"{script}: {run.stdout}{run.stderr}"
    return run


def _cli(*args: str, db: Path, aw_url: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("COMPUTER_HISTORY_")}
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO), env.get("PYTHONPATH")]))
    return subprocess.run(
        [str(CLI), *args, "--db-path", str(db), "--aw-url", aw_url],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _row_count(db: Path) -> int:
    with sqlite3.connect(db) as conn:
        observations = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        return observations + conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]


@pytest.fixture(scope="module")
def session(tmp_path_factory: pytest.TempPathFactory):
    folder = tmp_path_factory.mktemp("capture-e2e")
    spool = folder / "spool"
    db = folder / "history.db"
    server = ThreadingHTTPServer(("127.0.0.1", 0), EmptyActivityWatch)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    aw_url = f"http://127.0.0.1:{server.server_port}/api/0"
    try:
        crash_run = _agent("crash.json", folder)
        with (spool / "open.part").open("ab") as open_file:
            open_file.write(TORN_TAIL)
        run = _agent("session.json", folder)
        finished = sorted(spool.glob("*.jsonl"))
        spool_lines = [line for path in finished for line in path.read_text("utf-8").splitlines()]
        modes = {
            path.name: stat.S_IMODE(path.stat().st_mode)
            for path in (spool, spool / "agent.lock", *finished)
        }
        kept = folder / "finished-copy"
        kept.mkdir()
        for path in finished:
            shutil.copy(path, kept / path.name)
        ingests = [_cli("ingest", db=db, aw_url=aw_url)]
        row_counts = [_row_count(db)]
        ingests.append(_cli("ingest", db=db, aw_url=aw_url))
        row_counts.append(_row_count(db))
        for path in kept.iterdir():
            shutil.copy(path, spool / path.name)
        ingests.append(_cli("ingest", db=db, aw_url=aw_url))
        row_counts.append(_row_count(db))
        status = _cli("status", db=db, aw_url=aw_url)
    finally:
        server.shutdown()
    yield Session(
        folder, spool, db, crash_run, run, spool_lines, modes, ingests, row_counts, status
    )


def test_the_agent_writes_every_kind_and_trigger_the_scripts_call_for(session: Session) -> None:
    stored = [(r["kind"], r["trigger"], r["app_name"]) for r in session.records()]
    assert stored == EXPECTED


def test_every_record_has_exactly_the_contract_fixtures_keys_and_version(session: Session) -> None:
    contract = [json.loads(line) for line in CONTRACT.read_text("utf-8").splitlines()]
    keys = {record["kind"]: set(record) for record in contract}
    versions = {record["version"] for record in contract}
    for record in session.records():
        assert set(record) == keys[record["kind"]]
        assert {record["version"]} == versions


def test_raw_payloads_are_the_spool_lines_verbatim(session: Session) -> None:
    captures = sum(kind == "capture" for kind, _, _ in EXPECTED)
    assert len(session.spool_lines) == len(EXPECTED) + captures
    assert sorted(session.payloads()) == sorted(session.spool_lines)


def test_the_spool_and_its_files_are_readable_by_their_owner_only(session: Session) -> None:
    files = dict(session.modes)
    assert files.pop("spool") == 0o700
    assert files
    assert set(files.values()) == {0o600}


def test_captures_become_signals_with_the_scripted_text(session: Session) -> None:
    records = session.records()
    signals = session.signals()
    captures = [r for r in records if r["kind"] == "capture"]
    assert set(signals) == {r["id"] for r in captures}
    notes = next(r for r in captures if r["window_title"] == "Notes")
    app, title, text, extras = signals[notes["id"]]
    assert (app, title, text) == ("TextEdit", "Notes", "hello from the scripted session")
    assert json.loads(extras)["trigger"] == "heartbeat"
    chrome_title = next(r for r in captures if r["trigger"] == "title")
    assert chrome_title["text"] == "Inbox\nhttps://github.com/thewisepup/computer-history/pulls"
    assert signals[chrome_title["id"]][:3] == (
        "Google Chrome",
        "Pull requests",
        "Inbox https://github.com/thewisepup/computer-history/pulls",
    )
    chrome_window = next(r for r in captures if r["trigger"] == "window")
    assert signals[chrome_window["id"]][1:3] == ("Docs", "the design doc")


def test_a_long_capture_is_cut_off_in_raw_and_capped_in_its_signal(session: Session) -> None:
    scripted = json.loads((SCRIPTS / "session.json").read_text("utf-8"))
    (node,) = scripted["apps"]["cursor"]["windows"]["long"]["children"]
    full = node["value"] * node["repeat"]
    long = next(r for r in session.records() if r["app_name"] == "Cursor")
    assert long["text_cut_off"] is True
    assert long["full_text_bytes"] == len(full)
    assert long["text"] == full[:50_000]
    _, _, text, extras = session.signals()[long["id"]]
    assert text == full[:MAX_AX_TEXT_LENGTH]
    assert json.loads(extras)["text_cut_off"] is True


def test_a_hung_element_marks_the_capture_timed_out_with_the_text_so_far(session: Session) -> None:
    hung = next(r for r in session.records() if r["app_name"] == "Calculator")
    assert hung["timed_out"] is True
    assert hung["text"] == "42"
    assert json.loads(session.signals()[hung["id"]][3])["timed_out"] is True


def test_an_excluded_app_has_no_title_or_text_and_got_no_accessibility_calls(
    session: Session,
) -> None:
    excluded = [r for r in session.records() if r["kind"] == "excluded"]
    assert excluded
    for record in excluded:
        assert record["bundle_id"] == "com.1password.1password"
        assert record["window_title"] is None
        assert record["text"] is None
    assert "onepassword 0," in session.run.stdout


def test_nothing_is_recorded_between_paused_and_resumed(session: Session) -> None:
    kinds = [r["kind"] for r in session.records()]
    assert kinds.count("paused") == 1
    assert kinds.count("resumed") == 1
    assert kinds.index("resumed") == kinds.index("paused") + 1


def test_a_crashed_runs_open_file_is_recovered_without_its_torn_line(session: Session) -> None:
    assert "crashed at" in session.crash_run.stdout
    assert "spool finished leftover file" in session.run.stdout
    crash_records = [r for r in session.records() if r["window_title"] == "Crash notes"]
    assert len(crash_records) == 3
    assert "rejected" not in session.ingests[0].stdout
    assert not (session.spool / "unreadable").exists()


def test_ingest_empties_the_spool_and_a_second_ingest_adds_nothing(session: Session) -> None:
    first, second, again = session.ingests
    assert first.returncode == 0, first.stderr
    assert f"inserted {len(EXPECTED):>6}" in first.stdout
    assert second.returncode == 0, second.stderr
    assert again.returncode == 0, again.stderr
    assert f"inserted {0:>6}  skipped {len(EXPECTED):>6}" in again.stdout
    assert session.row_counts[0] == session.row_counts[1] == session.row_counts[2]
    assert not list(session.spool.glob("*.jsonl"))


def test_status_reports_the_capture_agent(session: Session) -> None:
    assert session.status.returncode == 0, session.status.stderr
    assert "Capture agent:" in session.status.stdout
    assert "last capture" in session.status.stdout


def _by_status(shots: list[dict], status: str) -> list[dict]:
    return [s for s in shots if s["status"] == status]


def test_every_capture_gets_one_screenshot_kept_beside_the_database_or_marked_duplicate(
    session: Session,
) -> None:
    captures = [r for r in session.records() if r["kind"] == "capture"]
    screenshots = session.screenshots()
    assert sorted(s["capture_id"] for s in screenshots) == sorted(r["id"] for r in captures)
    kept, duplicates = _by_status(screenshots, "kept"), _by_status(screenshots, "duplicate")
    assert kept and duplicates
    assert len(kept) + len(duplicates) == len(screenshots)
    for shot in kept:
        image = session.folder / shot["image_path"]
        assert shot["image_path"] == f"screenshots/{image.parent.name}/{shot['id']}.jpg"
        assert image.stat().st_size == shot["image_bytes"]
        assert image.read_bytes()[:3] == b"\xff\xd8\xff"
        assert stat.S_IMODE(image.stat().st_mode) == 0o600
    on_disk = {p.name for p in (session.folder / "screenshots").rglob("*.jpg")}
    assert on_disk == {f"{s['id']}.jpg" for s in kept}


def _keep_after_seconds(folder: Path) -> int:
    env = {k: v for k, v in os.environ.items() if not k.startswith("COMPUTER_HISTORY_")}
    env["COMPUTER_HISTORY_DB"] = str(folder / "history.db")
    run = subprocess.run(
        [os.environ[AGENT_ENV_VAR], "check-config"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    found = re.search(r"a new kept image after (\d+) min", run.stdout + run.stderr)
    assert found, run.stdout + run.stderr
    return int(found.group(1)) * 60


def test_a_duplicate_points_at_its_windows_recent_kept_image_and_copies_its_text(
    session: Session,
) -> None:
    screenshots = session.screenshots()
    keep_after = _keep_after_seconds(session.folder)
    kept = {s["image_path"]: s for s in _by_status(screenshots, "kept")}
    for shot in _by_status(screenshots, "duplicate"):
        original = kept[shot["image_path"]]
        window = ("app_name", "bundle_id", "window_title")
        assert [shot[k] for k in window] == [original[k] for k in window]
        age = to_utc(shot["captured_at"]) - to_utc(original["captured_at"])
        assert 0 < age.total_seconds() <= keep_after
        assert shot["image_bytes"] is None
        assert re.fullmatch(r"[0-9a-f]{16}", shot["perceptual_hash"])
        copied = ("text", "text_sha256", "full_text_bytes", "text_cut_off")
        assert [shot[k] for k in copied] == [original[k] for k in copied]


def test_status_reports_the_kept_and_duplicate_screenshots_and_their_size(session: Session) -> None:
    shots = session.screenshots()
    kept, duplicates = _by_status(shots, "kept"), _by_status(shots, "duplicate")
    out = session.status.stdout
    assert f"  all stored    {len(kept)} kept, {len(duplicates)} duplicate, 0 secure-field," in out
    total = human_size(sum(s["image_bytes"] for s in kept))
    assert f"  disk          {total} in total," in out


def test_the_agent_and_the_backend_default_to_the_same_folder_and_spool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("COMPUTER_HISTORY_")}
    env["HOME"] = str(home)
    run = subprocess.run(
        [os.environ[AGENT_ENV_VAR], "check-config"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    agent = dict(line.split(": ", 1) for line in run.stdout.splitlines() if ": " in line)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv(DB_ENV_VAR, raising=False)
    monkeypatch.delenv(SPOOL_ENV_VAR, raising=False)
    db = resolve_db_path()
    assert Path(agent["folder"]) == db.parent
    assert Path(agent["spool"]) == resolve_spool_path(None, db)
    assert not (home / "Library").exists()
