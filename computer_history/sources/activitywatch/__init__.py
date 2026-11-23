"""The ActivityWatch source adapter: settled window, AFK and web events.

    ActivityWatch HTTP API
          |
      client.py      the HTTP calls, nothing else (AWError: source unavailable)
          |
      discovery.py   buckets -> streams (aw-window, aw-afk, aw-web)
          |
      pull.py        fetch each bucket's events, keep the settled ones as raw observations
          |          (a source's frontier is the earliest bucket frontier), or fetch
          |          each bucket's newest event, for status
      adapter.py     ActivityWatch: the adapter the ingest runner drives, and the
                     only way to pull; it owns the position (the frontier as a
                     timestamp, rewound on resume), which nothing else decodes
                     history.py: where a stream's history begins, for backfill
                     normalize.py: its projectors, stored payload -> signal
                     (app, domain, url, title)
      afk.py         attended time for status: stored aw-afk spans plus each AFK
                     bucket's newest, still-growing event
      frontmost.py   the app in front on this host, for status: its stored aw-window
                     spans plus each of its window buckets' newest, still-growing event
      watchers.py    where this host's AFK and window sources last advanced, by
                     their most recent bucket, for the watchdog

An event that may still be growing is held back for a later poll: delayed,
never lost. Every event starting before a stream's settled-until time is stored.
An event written late that reaches back past where a poll resumes (aw-watcher-afk
dates a new AFK event from the last input, even across a sleep) is refetched whole.
"""

from computer_history.sources.activitywatch.adapter import RESUME_OVERLAP_SECONDS, ActivityWatch
from computer_history.sources.activitywatch.afk import (
    AfkSpan,
    newest_afk_spans,
    stored_afk_spans,
)
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
from computer_history.sources.activitywatch.frontmost import (
    AppSpan,
    newest_app_spans,
    stored_app_spans,
)
from computer_history.sources.activitywatch.normalize import project_signal
from computer_history.sources.activitywatch.pull import STABILITY_MARGIN_SECONDS
from computer_history.sources.activitywatch.watchers import watcher_ends

__all__ = [
    "AFK_SOURCE",
    "DEFAULT_AW_URL",
    "RESUME_OVERLAP_SECONDS",
    "STABILITY_MARGIN_SECONDS",
    "WEB_SOURCE",
    "WINDOW_SOURCE",
    "AWApi",
    "AWClient",
    "AWError",
    "AWSource",
    "ActivityWatch",
    "AfkSpan",
    "AppSpan",
    "discover_sources",
    "newest_afk_spans",
    "newest_app_spans",
    "project_signal",
    "stored_afk_spans",
    "stored_app_spans",
    "watcher_ends",
]
