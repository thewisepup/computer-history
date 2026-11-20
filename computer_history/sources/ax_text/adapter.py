"""The capture spool adapter: one pull per finished file, removed once it is stored."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path

from computer_history.sources.ax_text.normalize import AX_TEXT_SOURCE, PROJECTORS
from computer_history.sources.ax_text.record import InvalidRecord, parse_record
from computer_history.sources.ax_text.spool import (
    SpoolError,
    finished_files,
    read_lines,
    remove_finished,
    set_aside,
)
from computer_history.sources.contract import Pull, StreamProjector
from computer_history.store import Observation, utc_iso

log = logging.getLogger(__name__)

Finish = Callable[[Path], object]


class CaptureSpool:
    """Reads the capture agent's finished spool files for the ingest runner, oldest first."""

    projectors: Mapping[str, StreamProjector] = PROJECTORS

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._listed: deque[Path] = deque()
        self._stuck: set[Path] = set()

    def streams(self) -> list[str]:
        return [AX_TEXT_SOURCE]

    def pull_after(self, stream: str, position: str | None, *, now: datetime) -> Pull:
        """The oldest finished file's records, and the latest capture time they reach by now."""
        if stream != AX_TEXT_SOURCE:
            raise SpoolError(f"the spool feeds {AX_TEXT_SOURCE!r}, not {stream!r}")
        if not self._listed:
            self._listed.extend(p for p in finished_files(self.folder) if p not in self._stuck)
        if not self._listed:
            return Pull((), 0, None, None)
        path = self._listed[0]
        more = len(self._listed) > 1
        try:
            lines = read_lines(path)
        except FileNotFoundError:
            return self._empty(path, _gone, more)
        except OSError as exc:
            return self._empty(path, partial(_move_aside, reason=f"cannot read it: {exc}"), more)
        read = _read_records(lines, now)
        if read.rejected:
            log.warning(
                "skipped %d unusable record(s) in spool file %s (first, line %d: %s)",
                read.rejected,
                path.name,
                *read.first_problem,
            )
        finish: Finish = remove_finished
        if read.rejected:
            kept = "its usable lines are stored" if read.observations else "no line is usable"
            finish = partial(_move_aside, reason=f"it has unusable lines ({kept})")
        newest = None if read.latest is None else utc_iso(read.latest)
        moved = newest is not None and (
            position is None or newest > position or position > utc_iso(now)
        )
        return Pull(
            read.observations,
            0,
            newest if moved else None,
            read.latest if moved else None,
            rejected=read.rejected,
            more=more,
            after_commit=partial(self._drop_and_finish, path, finish),
        )

    def _empty(self, path: Path, finish: Finish, more: bool) -> Pull:
        after_commit = partial(self._drop_and_finish, path, finish)
        return Pull((), 0, None, None, more=more, after_commit=after_commit)

    def _drop_and_finish(self, path: Path, finish: Finish) -> None:
        if path in self._listed:
            self._listed.remove(path)
        try:
            finish(path)
        except SpoolError:
            self._stuck.add(path)
            raise


@dataclass(frozen=True)
class _Read:
    observations: tuple[Observation, ...]
    rejected: int
    latest: datetime | None
    first_problem: tuple[int, str]


def _read_records(lines: list[bytes], now: datetime) -> _Read:
    observations: list[Observation] = []
    rejected = 0
    latest: datetime | None = None
    first_problem = (0, "")
    for number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            line = raw.decode("utf-8")
            record = parse_record(line)
        except (UnicodeDecodeError, InvalidRecord) as exc:
            rejected += 1
            if rejected == 1:
                first_problem = (number, str(exc))
            continue
        observations.append(
            Observation(AX_TEXT_SOURCE, record.id, record.captured_at, record.captured_at, line)
        )
        if record.captured_at <= now and (latest is None or record.captured_at > latest):
            latest = record.captured_at
    return _Read(tuple(observations), rejected, latest, first_problem)


def _move_aside(path: Path, *, reason: str) -> None:
    target = set_aside(path)
    if target is not None:
        log.warning("moved spool file %s to %s: %s", path.name, target, reason)


def _gone(path: Path) -> None:
    return None
