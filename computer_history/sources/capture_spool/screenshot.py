from __future__ import annotations

import json

from computer_history.sources.capture_spool.record import parse_record
from computer_history.store import Signal
from computer_history.text import clean_text

SCREENSHOT_SOURCE = "screenshot"
MAX_RECOGNIZED_TEXT_LENGTH = 10_000
EXTRA_KEYS = ("image_path", "image_bytes", "status", "capture_id", "perceptual_hash")


def project_screenshot(payload: str) -> Signal:
    """The signal for a screenshot record: app, title, capped recognized text, and extras."""
    data = parse_record(payload).fields
    extras = {key: data[key] for key in EXTRA_KEYS if data.get(key) is not None}
    return Signal(
        app=clean_text(data.get("app_name")),
        title=clean_text(data.get("window_title")),
        text=clean_text(data.get("text"), MAX_RECOGNIZED_TEXT_LENGTH),
        extras=json.dumps(extras, sort_keys=True),
    )
