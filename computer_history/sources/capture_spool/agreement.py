"""Judge the app each capture recorded against the app aw-window shows in front at that moment."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from computer_history.sources.capture_spool.record import CAPTURE_KIND
from computer_history.sources.capture_spool.window_text import StoredRecord

APP_TOLERANCE = timedelta(seconds=2)

WindowSpan = tuple[datetime, datetime, str]


@dataclass(frozen=True)
class AppAgreement:
    """Captures whose app matches aw-window, differs from it, or has no aw-window span near it.

    It counts the aw-window spans in the range too, and lists differing app pairs most common first.
    """

    matched: int
    differ: int
    unjudged: int
    pairs: tuple[tuple[str | None, str, int], ...]
    spans: int = 0


def app_agreement(
    records: Iterable[StoredRecord],
    spans: Iterable[WindowSpan],
    *,
    start: datetime,
    end: datetime,
) -> AppAgreement:
    """Compare each capture in the range with the aw-window spans within the tolerance of it.

    Any span with the same app, ignoring case, is a match; otherwise the nearest span's app differs.
    """
    captures = sorted(
        (r for r in records if r.kind == CAPTURE_KIND and start <= r.at <= end),
        key=lambda r: r.at,
    )
    pending = deque(
        sorted(s for s in spans if s[0] <= end + APP_TOLERANCE and s[1] >= start - APP_TOLERANCE)
    )
    in_range = len(pending)
    near: list[WindowSpan] = []
    matched = unjudged = 0
    pairs: Counter[tuple[str | None, str]] = Counter()
    for capture in captures:
        at = capture.at
        while pending and pending[0][0] <= at + APP_TOLERANCE:
            near.append(pending.popleft())
        near = [span for span in near if span[1] >= at - APP_TOLERANCE]
        if not near:
            unjudged += 1
        elif any(_same(capture.app, span[2]) for span in near):
            matched += 1
        else:
            pairs[(capture.app, min(near, key=lambda span: _distance(at, span))[2])] += 1
    ranked = sorted(pairs.items(), key=lambda item: (-item[1], str(item[0])))
    return AppAgreement(
        matched,
        sum(pairs.values()),
        unjudged,
        tuple((captured, seen, n) for (captured, seen), n in ranked),
        in_range,
    )


def _same(captured: str | None, seen: str) -> bool:
    return captured is not None and captured.casefold() == seen.casefold()


def _distance(at: datetime, span: WindowSpan) -> timedelta:
    return max(span[0] - at, at - span[1], timedelta())
