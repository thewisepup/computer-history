"""Spool records shaped as the capture agent writes them, for tests to write or store."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from computer_history.sources import (
    CAPTURE_KIND,
    PAUSED_KIND,
    RESUMED_KIND,
    SLEPT_KIND,
    SPOOL_VERSION,
    WOKE_KIND,
)

SILENT_EDGES = (PAUSED_KIND, RESUMED_KIND, SLEPT_KIND, WOKE_KIND)


def spool_line(n: int | None, when: datetime, kind: str = CAPTURE_KIND, **fields: Any) -> str:
    """One record of the kind as a spool line, with id n (or a random id) and fields overridden.

    A capture carries a title and text, and only the silent edges leave app and trigger out.
    """
    content = kind == CAPTURE_KIND
    record = {
        "version": SPOOL_VERSION,
        "id": str(uuid.uuid4()) if n is None else f"00000000-0000-4000-8000-{n:012x}",
        "captured_at": when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z",
        "kind": kind,
        "trigger": None if kind in SILENT_EDGES else "heartbeat",
        "app_name": None if kind in SILENT_EDGES else "Editor",
        "bundle_id": None,
        "window_title": "w" if content else None,
        "text": "t" if content else None,
        "text_sha256": "0" * 64 if content else None,
        "full_text_bytes": 1 if content else None,
        "text_cut_off": False if content else None,
        "timed_out": False if content else None,
    }
    record.update(fields)
    return json.dumps(record, sort_keys=True)
