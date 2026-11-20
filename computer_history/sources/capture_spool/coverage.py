from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from computer_history.sources.capture_spool.record import PAUSED_KIND
from computer_history.sources.capture_spool.stored import StoredRecord
from computer_history.store import Gap

HEARTBEAT_SECONDS = 30
CAPTURE_TOLERANCE = timedelta(seconds=2 * HEARTBEAT_SECONDS)
AGENT_ALIVE_WITHIN = timedelta(minutes=5)

Span = tuple[datetime, datetime]


@dataclass(frozen=True)
class Coverage:
    """The checked range, attended stretches no record explains, and those aw-afk cannot judge."""

    start: datetime
    end: datetime
    unobserved: tuple[Gap, ...]
    unjudged: tuple[Gap, ...]


def capture_coverage(
    records: Sequence[StoredRecord],
    *,
    active: Iterable[Span],
    known: Iterable[Span],
    start: datetime,
    end: datetime,
    paused_at_start: bool,
    min_gap_seconds: float = 0,
) -> Coverage:
    """The active stretches no record or pause explains, and the stretches without aw-afk data.

    A record explains the tolerance on either side of it, and a pause lasts until the next record.
    """
    explained = _merge(
        [(r.at - CAPTURE_TOLERANCE, r.at + CAPTURE_TOLERANCE) for r in records]
        + _paused_spans(records, start, end, paused_at_start)
    )
    window = [(start, end)]
    unobserved = _subtract(_clip(_merge(active), start, end), explained)
    unjudged = _subtract(_subtract(window, _merge(known)), explained)
    return Coverage(
        start, end, _gaps(unobserved, min_gap_seconds), _gaps(unjudged, min_gap_seconds)
    )


def liveness(last_seen: datetime, *, now: datetime, paused: bool, active: Iterable[Span]) -> str:
    """Whether the agent appears alive: 'yes', 'no', 'paused' or 'unknown'.

    It is 'no' only when aw-afk shows the user active for longer than the tolerance since the last
    record.
    """
    if paused:
        return "paused"
    if now - last_seen <= AGENT_ALIVE_WITHIN:
        return "yes"
    stretches = _clip(_merge(active), last_seen + CAPTURE_TOLERANCE, now)
    attended = sum((b - a for a, b in stretches), timedelta())
    return "no" if attended > CAPTURE_TOLERANCE else "unknown"


def _paused_spans(
    records: Sequence[StoredRecord], start: datetime, end: datetime, paused_at_start: bool
) -> list[Span]:
    spans = []
    paused_from = start if paused_at_start else None
    for record in sorted(records, key=lambda r: r.at):
        if record.kind == PAUSED_KIND:
            paused_from = record.at if paused_from is None else paused_from
        elif paused_from is not None:
            spans.append((paused_from, record.at))
            paused_from = None
    if paused_from is not None:
        spans.append((paused_from, end))
    return _clip(spans, start, end)


def _merge(spans: Iterable[Span]) -> list[Span]:
    merged: list[Span] = []
    for a, b in sorted(spans):
        if b <= a:
            continue
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _clip(spans: Iterable[Span], start: datetime, end: datetime) -> list[Span]:
    clipped = [(max(a, start), min(b, end)) for a, b in spans]
    return [(a, b) for a, b in clipped if a < b]


def _subtract(spans: Sequence[Span], holes: Sequence[Span]) -> list[Span]:
    result = []
    for a, b in spans:
        cursor = a
        for h0, h1 in holes:
            if h1 <= cursor or h0 >= b:
                continue
            if h0 > cursor:
                result.append((cursor, h0))
            cursor = max(cursor, h1)
            if cursor >= b:
                break
        if cursor < b:
            result.append((cursor, b))
    return result


def _gaps(spans: Iterable[Span], min_gap_seconds: float) -> tuple[Gap, ...]:
    return tuple(g for g in (Gap(a, b) for a, b in spans) if g.seconds >= min_gap_seconds)
