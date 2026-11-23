from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from computer_history.sources.contract import JsonValue

WINDOW_SOURCE = "aw-window"
AFK_SOURCE = "aw-afk"
WEB_SOURCE = "aw-web"
BUCKET_TYPE_SOURCES = {
    "currentwindow": WINDOW_SOURCE,
    "afkstatus": AFK_SOURCE,
    "web.tab.current": WEB_SOURCE,
}


@dataclass(frozen=True)
class AWSource:
    """One source and the buckets that feed it (sorted)."""

    name: str
    bucket_ids: tuple[str, ...]


def discover_sources(buckets: Mapping[str, JsonValue]) -> list[AWSource]:
    """Map a bucket listing to sources by bucket type, ignoring other types."""
    grouped: dict[str, list[str]] = {}
    for bucket_id, meta in buckets.items():
        bucket_type = meta.get("type") if isinstance(meta, Mapping) else None
        source = BUCKET_TYPE_SOURCES.get(bucket_type) if isinstance(bucket_type, str) else None
        if source is not None:
            grouped.setdefault(source, []).append(bucket_id)
    return [AWSource(name, tuple(sorted(ids))) for name, ids in sorted(grouped.items())]
