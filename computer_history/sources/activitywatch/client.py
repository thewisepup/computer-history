"""The HTTP client for the ActivityWatch API. Read-only."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from computer_history.sources.contract import SourceUnavailable
from computer_history.store import to_utc

DEFAULT_AW_URL = "http://127.0.0.1:5600/api/0"
REQUEST_TIMEOUT_SECONDS = 30


class AWError(SourceUnavailable):
    """ActivityWatch was unreachable or answered with something unusable."""


class _NotFound(AWError):
    pass


class AWApi(Protocol):
    """The part of the ActivityWatch API this package uses."""

    def get_buckets(self) -> dict[str, dict[str, Any]]: ...

    def get_events(
        self,
        bucket_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = -1,
    ) -> list[dict[str, Any]]: ...

    def get_event(self, bucket_id: str, event_id: Any) -> dict[str, Any] | None: ...


class AWClient:
    """Small read-only client for the ActivityWatch REST API."""

    def __init__(
        self, base_url: str = DEFAULT_AW_URL, timeout: float = REQUEST_TIMEOUT_SECONDS
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_buckets(self) -> dict[str, dict[str, Any]]:
        buckets = self._get("/buckets/")
        if not isinstance(buckets, dict):
            raise AWError("ActivityWatch /buckets/ did not return an object")
        return buckets

    def get_events(
        self,
        bucket_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = -1,
    ) -> list[dict[str, Any]]:
        """Events overlapping the range, newest first, clipped to the range.

        A limit keeps the newest events, so pass limit=-1 for all of them.
        """
        params: dict[str, Any] = {"limit": limit}
        if start is not None:
            params["start"] = to_utc(start).isoformat()
        if end is not None:
            params["end"] = to_utc(end).isoformat()
        events = self._get(f"{self._bucket_path(bucket_id)}/events?{urlencode(params)}")
        if not isinstance(events, list):
            raise AWError(f"ActivityWatch events for {bucket_id!r} were not a list")
        return events

    def get_event(self, bucket_id: str, event_id: Any) -> dict[str, Any] | None:
        """One event, unclipped, or None if it no longer exists."""
        try:
            event = self._get(f"{self._bucket_path(bucket_id)}/events/{quote(str(event_id))}")
        except _NotFound:
            return None
        if not isinstance(event, dict):
            raise AWError(f"ActivityWatch event {bucket_id}/{event_id} was not an object")
        return event

    @staticmethod
    def _bucket_path(bucket_id: str) -> str:
        return "/buckets/" + quote(bucket_id, safe="")

    def _get(self, path: str) -> Any:
        url = self.base_url + path
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code == 404:
                raise _NotFound(f"ActivityWatch 404 for {url}") from exc
            raise AWError(f"ActivityWatch HTTP {exc.code} for {url}") from exc
        except (URLError, OSError) as exc:
            raise AWError(f"ActivityWatch unreachable at {self.base_url}: {exc}") from exc
        except ValueError as exc:
            raise AWError(f"ActivityWatch returned invalid JSON for {url}") from exc
