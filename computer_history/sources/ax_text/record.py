from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from computer_history.store import to_utc

SPOOL_VERSION = 1
CAPTURE_KIND = "capture"
EXCLUDED_KIND = "excluded"
PAUSED_KIND = "paused"
RESUMED_KIND = "resumed"
SCREENSHOT_KIND = "screenshot"
AX_TEXT_KINDS = (CAPTURE_KIND, EXCLUDED_KIND, PAUSED_KIND, RESUMED_KIND)
KINDS = (*AX_TEXT_KINDS, SCREENSHOT_KIND)
SCREENSHOT_STATUSES = ("kept", "duplicate", "secure-field", "no-permission", "failed")

_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TYPED_FIELDS: Mapping[str, type] = {
    "trigger": str,
    "app_name": str,
    "bundle_id": str,
    "window_title": str,
    "text": str,
    "text_sha256": str,
    "full_text_bytes": int,
    "text_cut_off": bool,
    "timed_out": bool,
    "image_path": str,
    "image_bytes": int,
    "perceptual_hash": str,
}


class InvalidRecord(ValueError):
    """A spool line that is not a record this backend can use, and the kind it names if known."""

    def __init__(self, message: str, kind: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class ParsedRecord:
    """A checked spool record: its id, capture time and kind, plus every field as written."""

    id: str
    captured_at: datetime
    kind: str
    fields: Mapping[str, Any]


def parse_record(line: str) -> ParsedRecord:
    """The record on one spool line, or InvalidRecord if it is malformed or of another version."""
    try:
        data = json.loads(line)
    except ValueError as exc:
        raise InvalidRecord(f"not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidRecord("not a JSON object")
    version = data.get("version")
    if type(version) is not int or version != SPOOL_VERSION:
        raise InvalidRecord(f"unknown version {version!r}")
    record_id = data.get("id")
    if not isinstance(record_id, str) or not _ID.fullmatch(record_id):
        raise InvalidRecord(f"bad id {record_id!r}")
    kind = data.get("kind")
    if kind not in KINDS:
        raise InvalidRecord(f"unknown kind {kind!r}")
    try:
        return _checked(data, record_id, kind)
    except InvalidRecord as exc:
        exc.kind = kind
        raise


def _checked(data: dict[str, Any], record_id: str, kind: str) -> ParsedRecord:
    for key, expected in _TYPED_FIELDS.items():
        value = data.get(key)
        if value is not None and type(value) is not expected:
            raise InvalidRecord(f"{key} is not a {expected.__name__}: {value!r}")
    if kind == SCREENSHOT_KIND:
        status = data.get("status")
        if status not in SCREENSHOT_STATUSES:
            raise InvalidRecord(f"unknown status {status!r}")
        capture_id = data.get("capture_id")
        if not isinstance(capture_id, str) or not _ID.fullmatch(capture_id):
            raise InvalidRecord(f"bad capture_id {capture_id!r}")
    return ParsedRecord(record_id, _captured_at(data.get("captured_at")), kind, data)


def _captured_at(value: Any) -> datetime:
    if not isinstance(value, str):
        raise InvalidRecord(f"bad captured_at {value!r}")
    try:
        return to_utc(value)
    except (ValueError, OverflowError) as exc:
        raise InvalidRecord(f"bad captured_at {value!r}") from exc
