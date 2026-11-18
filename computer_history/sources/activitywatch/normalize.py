"""Turn one raw event payload into a signal."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from computer_history.sources.activitywatch.discovery import AFK_SOURCE, WEB_SOURCE, WINDOW_SOURCE
from computer_history.store import Signal
from computer_history.text import clean_text, clean_url, extract_domain


def project_signal(source: str, payload: Mapping[str, Any] | str) -> Signal | None:
    """The signal for one event payload, or None for AFK.

    Accepts the event as a dict or as the stored JSON text.
    """
    if source == AFK_SOURCE:
        return None
    if source not in (WINDOW_SOURCE, WEB_SOURCE):
        raise ValueError(f"not an ActivityWatch content source: {source!r}")
    if isinstance(payload, str):
        payload = json.loads(payload)
    raw_data = payload.get("data") if isinstance(payload, Mapping) else None
    data = dict(raw_data) if isinstance(raw_data, Mapping) else {}
    if source == WINDOW_SOURCE:
        app = clean_text(_take_str(data, "app"))
        title = clean_text(_take_str(data, "title"))
        return Signal(app=app, title=title, extras=_extras(data))
    url = _take_str(data, "url")
    title = clean_text(_take_str(data, "title"))
    return Signal(
        url=clean_url(url), domain=extract_domain(url), title=title, extras=_extras(data)
    )


def _take_str(data: dict[str, Any], key: str) -> str | None:
    """Pop and return the key if it holds a string."""
    value = data.get(key)
    if isinstance(value, str):
        del data[key]
        return value
    return None


def _extras(leftover: dict[str, Any]) -> str | None:
    return json.dumps(leftover, sort_keys=True) if leftover else None
