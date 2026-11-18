"""The ActivityWatch source adapter: settled window, AFK and web events.

    ActivityWatch HTTP API
          |
      client.py      the HTTP calls, nothing else (AWError: source unavailable)
          |
      discovery.py   buckets -> streams (aw-window, aw-afk, aw-web)
          |
      pull.py        fetch each bucket's events, keep the settled ones as raw observations
          |          (a source's frontier is the earliest bucket frontier)
      adapter.py     ActivityWatch: the adapter the ingest runner drives
                     position.py: the frontier is the position, rewound on resume
                     history.py: where a stream's history begins, for backfill
                     normalize.py: its projectors, stored payload -> signal
                     (app, domain, url, title)

An event that may still be growing is held back for a later poll: delayed,
never lost. Every event starting before a stream's settled-until time is stored.
"""

from computer_history.sources.activitywatch.adapter import ActivityWatch
from computer_history.sources.activitywatch.client import (
    DEFAULT_AW_URL,
    AWApi,
    AWClient,
    AWError,
)
from computer_history.sources.activitywatch.discovery import (
    AFK_SOURCE,
    WEB_SOURCE,
    WINDOW_SOURCE,
    AWSource,
    discover_sources,
)
from computer_history.sources.activitywatch.normalize import PROJECTORS, project_signal
from computer_history.sources.activitywatch.position import (
    RESUME_OVERLAP_SECONDS,
    position_at,
    resume_start,
)
from computer_history.sources.activitywatch.pull import (
    STABILITY_MARGIN_SECONDS,
    BucketPull,
    SourcePull,
    pull_bucket,
    pull_source,
)
from computer_history.text import (
    MAX_TEXT_LENGTH,
    MAX_URL_LENGTH,
    clean_text,
    clean_url,
    extract_domain,
)

__all__ = [
    "AFK_SOURCE",
    "DEFAULT_AW_URL",
    "MAX_TEXT_LENGTH",
    "MAX_URL_LENGTH",
    "PROJECTORS",
    "RESUME_OVERLAP_SECONDS",
    "STABILITY_MARGIN_SECONDS",
    "WEB_SOURCE",
    "WINDOW_SOURCE",
    "AWApi",
    "AWClient",
    "AWError",
    "AWSource",
    "ActivityWatch",
    "BucketPull",
    "SourcePull",
    "clean_text",
    "clean_url",
    "discover_sources",
    "extract_domain",
    "position_at",
    "project_signal",
    "pull_bucket",
    "pull_source",
    "resume_start",
]
