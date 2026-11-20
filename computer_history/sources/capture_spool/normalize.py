from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType

from computer_history.sources.capture_spool.record import (
    AX_TEXT_SOURCE,
    CAPTURE_KIND,
    SCREENSHOT_SOURCE,
    parse_record,
)
from computer_history.sources.contract import StreamProjector
from computer_history.store import Signal
from computer_history.text import clean_text

MAX_AX_TEXT_LENGTH = 10_000
MAX_RECOGNIZED_TEXT_LENGTH = 10_000
CAPTURE_EXTRA_KEYS = (
    "bundle_id",
    "trigger",
    "text_sha256",
    "full_text_bytes",
    "text_cut_off",
    "timed_out",
)
SCREENSHOT_EXTRA_KEYS = ("image_path", "image_bytes", "status", "capture_id", "perceptual_hash")


def project_capture(payload: str) -> Signal | None:
    """The signal for a capture record, or None for excluded, paused and resumed records."""
    record = parse_record(payload)
    if record.kind != CAPTURE_KIND:
        return None
    data = record.fields
    extras = {key: data[key] for key in CAPTURE_EXTRA_KEYS if data.get(key) is not None}
    return Signal(
        app=clean_text(data.get("app_name")),
        title=clean_text(data.get("window_title")),
        text=clean_text(data.get("text"), MAX_AX_TEXT_LENGTH),
        extras=json.dumps(extras, sort_keys=True) if extras else None,
    )


def project_screenshot(payload: str) -> Signal:
    """The signal for a screenshot record: app, title, capped recognized text, and extras."""
    data = parse_record(payload).fields
    extras = {key: data[key] for key in SCREENSHOT_EXTRA_KEYS if data.get(key) is not None}
    return Signal(
        app=clean_text(data.get("app_name")),
        title=clean_text(data.get("window_title")),
        text=clean_text(data.get("text"), MAX_RECOGNIZED_TEXT_LENGTH),
        extras=json.dumps(extras, sort_keys=True),
    )


PROJECTORS: Mapping[str, StreamProjector] = MappingProxyType(
    {AX_TEXT_SOURCE: project_capture, SCREENSHOT_SOURCE: project_screenshot}
)
