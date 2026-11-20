from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any

from computer_history.store import to_utc

SPOOL_VERSION = 1
CAPTURE_KIND = "capture"
EXCLUDED_KIND = "excluded"
PAUSED_KIND = "paused"
RESUMED_KIND = "resumed"
SCREENSHOT_KIND = "screenshot"
WINDOW_TEXT_KINDS = (CAPTURE_KIND, EXCLUDED_KIND, PAUSED_KIND, RESUMED_KIND)
KINDS = (*WINDOW_TEXT_KINDS, SCREENSHOT_KIND)
WINDOW_TEXT_SOURCE = "ax-text"
SCREENSHOT_SOURCE = "screenshot"
STREAM_KINDS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {WINDOW_TEXT_SOURCE: WINDOW_TEXT_KINDS, SCREENSHOT_SOURCE: (SCREENSHOT_KIND,)}
)
SPOOL_STREAMS = tuple(STREAM_KINDS)
KEPT_STATUS = "kept"
DUPLICATE_STATUS = "duplicate"
SECURE_FIELD_STATUS = "secure-field"
NO_PERMISSION_STATUS = "no-permission"
FAILED_STATUS = "failed"
SCREENSHOT_STATUSES = (
    KEPT_STATUS,
    DUPLICATE_STATUS,
    SECURE_FIELD_STATUS,
    NO_PERMISSION_STATUS,
    FAILED_STATUS,
)

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


_SCREENSHOT_IMAGE_FIELDS = (
    "image_path",
    "image_bytes",
    "perceptual_hash",
    "text",
    "text_sha256",
    "full_text_bytes",
    "text_cut_off",
)
_WITH_IMAGE = frozenset(_SCREENSHOT_IMAGE_FIELDS) - {"image_bytes"}
_SCREENSHOT_NEEDS: Mapping[str, frozenset[str]] = {
    KEPT_STATUS: frozenset(_SCREENSHOT_IMAGE_FIELDS),
    DUPLICATE_STATUS: _WITH_IMAGE,
    SECURE_FIELD_STATUS: frozenset(),
    NO_PERMISSION_STATUS: frozenset(),
    FAILED_STATUS: frozenset(),
}
WINDOW_TEXT_RECORD_FIELDS = (
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
)
SCREENSHOT_RECORD_FIELDS = (
    "version",
    "id",
    "captured_at",
    "kind",
    "capture_id",
    "status",
    "app_name",
    "bundle_id",
    "window_title",
    *_SCREENSHOT_IMAGE_FIELDS,
)


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
    """The record on one spool line, or InvalidRecord if it is malformed or of another version.

    The error names the line's kind whenever the line names one this backend knows.
    """
    try:
        data = json.loads(line)
    except ValueError as exc:
        raise InvalidRecord(f"not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidRecord("not a JSON object")
    kind = data.get("kind")
    try:
        return _checked(data, kind)
    except InvalidRecord as exc:
        exc.kind = kind if kind in KINDS else None
        raise


def _checked(data: dict[str, Any], kind: Any) -> ParsedRecord:
    version = data.get("version")
    if type(version) is not int or version != SPOOL_VERSION:
        raise InvalidRecord(f"unknown version {version!r}")
    record_id = data.get("id")
    if not isinstance(record_id, str) or not _ID.fullmatch(record_id):
        raise InvalidRecord(f"bad id {record_id!r}")
    if kind not in KINDS:
        raise InvalidRecord(f"unknown kind {kind!r}")
    for key, expected in _TYPED_FIELDS.items():
        value = data.get(key)
        if value is not None and type(value) is not expected:
            raise InvalidRecord(f"{key} is not a {expected.__name__}: {value!r}")
    if kind == SCREENSHOT_KIND:
        _check_screenshot(data)
    return ParsedRecord(record_id, _captured_at(data.get("captured_at")), kind, data)


def _check_screenshot(data: dict[str, Any]) -> None:
    status = data.get("status")
    if status not in SCREENSHOT_STATUSES:
        raise InvalidRecord(f"unknown status {status!r}")
    capture_id = data.get("capture_id")
    if not isinstance(capture_id, str) or not _ID.fullmatch(capture_id):
        raise InvalidRecord(f"bad capture_id {capture_id!r}")
    needed = _SCREENSHOT_NEEDS[status]
    for key in _SCREENSHOT_IMAGE_FIELDS:
        present = data.get(key) is not None
        if key in needed and not present:
            raise InvalidRecord(f"a {status} screenshot needs {key}")
        if key not in needed and present:
            raise InvalidRecord(f"a {status} screenshot has {key}")
    if data.get("image_bytes") is not None and data["image_bytes"] < 0:
        raise InvalidRecord(f"image_bytes is negative: {data['image_bytes']!r}")


def _captured_at(value: Any) -> datetime:
    if not isinstance(value, str):
        raise InvalidRecord(f"bad captured_at {value!r}")
    try:
        return to_utc(value)
    except (ValueError, OverflowError) as exc:
        raise InvalidRecord(f"bad captured_at {value!r}") from exc
