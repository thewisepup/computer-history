"""The spool fixture shared with the capture agent parses and has the documented keys."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "spool" / "records.jsonl"
KEYS = {
    "version",
    "id",
    "captured_at",
    "kind",
    "trigger",
    "app_name",
    "bundle_id",
    "window_title",
    "text",
    "text_sha256",
    "full_text_bytes",
    "text_cut_off",
    "timed_out",
}


def test_every_fixture_line_parses_with_the_documented_keys() -> None:
    records = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    assert records
    for record in records:
        assert set(record) == KEYS
    assert {r["kind"] for r in records} == {"capture", "excluded", "paused", "resumed"}
    assert {r["trigger"] for r in records} - {None} == {"app", "window", "title", "heartbeat"}
