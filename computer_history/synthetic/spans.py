"""Spans of time as (start, end) pairs: merged, intersected and their complement in a range."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

Span = tuple[datetime, datetime]


def merge(spans: Iterable[Span]) -> list[Span]:
    """The spans in order, with overlapping and touching ones joined."""
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def intersect(spans: Iterable[Span], within: Sequence[Span]) -> list[Span]:
    """The parts of the spans that lie within the others, merged."""
    return merge(
        (max(start, lo), min(end, hi))
        for start, end in spans
        for lo, hi in within
        if max(start, lo) < min(end, hi)
    )


def outside(covered: Iterable[Span], start: datetime, end: datetime) -> list[Span]:
    """The parts of the range from start to end that no span covers."""
    found: list[Span] = []
    edge = start
    for lo, hi in merge(covered):
        if lo > edge:
            found.append((edge, min(lo, end)))
        edge = max(edge, hi)
    if edge < end:
        found.append((edge, end))
    return [(lo, hi) for lo, hi in found if lo < hi]
