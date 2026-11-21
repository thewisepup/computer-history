from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_history.sources import SCREENSHOT_KIND, InvalidRecord, parse_record

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "spool" / "records.jsonl"
FIXTURE_LINES = FIXTURE.read_text(encoding="utf-8").splitlines()
CAPTURE_KEYS = {
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
SCREENSHOT_KEYS = {
    "version",
    "id",
    "capture_id",
    "captured_at",
    "kind",
    "status",
    "app_name",
    "bundle_id",
    "window_title",
    "image_path",
    "image_bytes",
    "perceptual_hash",
    "text",
    "text_sha256",
    "full_text_bytes",
    "text_cut_off",
}


def fixture_records(kind: str | None = None) -> list[dict]:
    records = [json.loads(line) for line in FIXTURE_LINES]
    if kind is None:
        return [r for r in records if r["kind"] != SCREENSHOT_KIND]
    return [r for r in records if r["kind"] == kind]


def test_every_capture_agent_line_parses_with_the_documented_keys() -> None:
    records = fixture_records()
    assert records
    for record in records:
        assert set(record) == CAPTURE_KEYS
    assert {r["kind"] for r in records} == {
        "capture",
        "excluded",
        "paused",
        "resumed",
        "slept",
        "woke",
    }
    assert {r["trigger"] for r in records} - {None} == {"app", "window", "title", "heartbeat"}


def test_every_screenshot_line_has_the_documented_keys_and_every_status() -> None:
    records = fixture_records(SCREENSHOT_KIND)
    for record in records:
        assert set(record) == SCREENSHOT_KEYS
    assert sorted(r["status"] for r in records) == sorted(
        ["kept", "duplicate", "secure-field", "no-permission", "failed"]
    )


def test_only_kept_and_duplicate_screenshots_carry_an_image_and_text() -> None:
    for record in fixture_records(SCREENSHOT_KIND):
        with_image = record["status"] in ("kept", "duplicate")
        for key in ("image_path", "perceptual_hash", "text", "text_sha256", "full_text_bytes"):
            assert (record[key] is not None) == with_image, (record["status"], key)
        assert (record["image_bytes"] is not None) == (record["status"] == "kept")


def test_every_fixture_line_is_a_record_the_backend_reads() -> None:
    parsed = [parse_record(line) for line in FIXTURE_LINES]

    assert [p.id for p in parsed] == [json.loads(line)["id"] for line in FIXTURE_LINES]
    assert {p.kind for p in parsed} == {
        "capture",
        "excluded",
        "paused",
        "resumed",
        "slept",
        "woke",
        SCREENSHOT_KIND,
    }


def screenshot_line(**fields: object) -> str:
    data = fixture_records(SCREENSHOT_KIND)[1] | fields
    return json.dumps(data, sort_keys=True, ensure_ascii=False)


@pytest.mark.parametrize(
    ("line", "problem"),
    [
        (screenshot_line(status="blurry"), "unknown status 'blurry'"),
        (screenshot_line(status=None), "unknown status None"),
        (screenshot_line(capture_id="NOT-A-UUID"), "bad capture_id"),
        (screenshot_line(capture_id=None), "bad capture_id"),
        (screenshot_line(image_bytes="183442"), "image_bytes is not a int"),
        (screenshot_line(image_path=7), "image_path is not a str"),
        (screenshot_line(perceptual_hash=12), "perceptual_hash is not a str"),
    ],
)
def test_a_screenshot_record_failing_validation_says_why_and_names_its_kind(
    line: str, problem: str
) -> None:
    with pytest.raises(InvalidRecord, match=problem) as raised:
        parse_record(line)
    assert raised.value.kind == SCREENSHOT_KIND


def test_a_line_naming_no_known_kind_is_invalid_without_a_kind() -> None:
    for line in ("{", json.dumps(fixture_records()[0] | {"kind": "snapshot"})):
        with pytest.raises(InvalidRecord) as raised:
            parse_record(line)
        assert raised.value.kind is None


def screenshot_with(status: str, **fields: object) -> str:
    data = next(r for r in fixture_records(SCREENSHOT_KIND) if r["status"] == status) | fields
    return json.dumps({k: v for k, v in data.items() if v is not ...}, sort_keys=True)


@pytest.mark.parametrize(
    ("line", "problem"),
    [
        (screenshot_with("kept", image_bytes=None), "a kept screenshot needs image_bytes"),
        (screenshot_with("kept", image_bytes=...), "a kept screenshot needs image_bytes"),
        (screenshot_with("kept", image_path=None), "a kept screenshot needs image_path"),
        (screenshot_with("kept", image_path=...), "a kept screenshot needs image_path"),
        (screenshot_with("kept", perceptual_hash=None), "a kept screenshot needs perceptual_hash"),
        (screenshot_with("kept", text=None), "a kept screenshot needs text"),
        (screenshot_with("kept", text_cut_off=None), "a kept screenshot needs text_cut_off"),
        (screenshot_with("kept", image_bytes=-1), "image_bytes is negative"),
        (screenshot_with("duplicate", image_path=None), "a duplicate screenshot needs image_path"),
        (screenshot_with("duplicate", text=...), "a duplicate screenshot needs text"),
        (screenshot_with("duplicate", image_bytes=10), "a duplicate screenshot has image_bytes"),
        (screenshot_with("failed", image_path="shots/x.jpg"), "a failed screenshot has image_path"),
        (screenshot_with("secure-field", text="hunter2"), "a secure-field screenshot has text"),
        (screenshot_with("no-permission", perceptual_hash="00"), "has perceptual_hash"),
    ],
)
def test_a_screenshot_record_breaking_its_status_rules_is_invalid(line: str, problem: str) -> None:
    with pytest.raises(InvalidRecord, match=problem) as raised:
        parse_record(line)
    assert raised.value.kind == SCREENSHOT_KIND


@pytest.mark.parametrize(
    ("fields", "kind"),
    [
        ({"version": 2}, SCREENSHOT_KIND),
        ({"id": "NOT-A-UUID"}, SCREENSHOT_KIND),
        ({"captured_at": "yesterday"}, SCREENSHOT_KIND),
        ({"kind": "capture", "version": 2}, "capture"),
        ({"kind": "capture", "id": 7}, "capture"),
        ({"kind": "snapshot"}, None),
        ({"kind": None}, None),
    ],
)
def test_a_record_that_fails_names_its_kind_whenever_the_kind_is_readable(
    fields: dict, kind: str | None
) -> None:
    with pytest.raises(InvalidRecord) as raised:
        parse_record(screenshot_with("kept", **fields))
    assert raised.value.kind == kind
