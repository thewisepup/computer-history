"""The capture spool adapter: one pull per finished file and stream, removed once both stored it."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from pathlib import Path

from computer_history.sources.capture_spool.normalize import PROJECTORS
from computer_history.sources.capture_spool.record import (
    STREAM_KINDS,
    InvalidRecord,
    parse_record,
)
from computer_history.sources.capture_spool.spool import (
    FileIdentity,
    SpoolError,
    finished_files,
    read_file,
    remove_finished,
    set_aside,
)
from computer_history.sources.contract import Pull
from computer_history.store import Observation, SpoolHold, utc_iso

log = logging.getLogger(__name__)

Finish = Callable[[Path], object]


class CaptureSpool:
    """Reads the capture agent's finished spool files for the ingest runner, oldest first."""

    projectors = PROJECTORS

    def __init__(self, folder: Path, *, hold: SpoolHold | None = None) -> None:
        self.folder = folder
        self.hold = hold
        self._listed: dict[str, deque[Path]] = {stream: deque() for stream in STREAM_KINDS}
        self._stored: dict[tuple[Path, FileIdentity], set[str]] = {}
        self._unreadable: dict[Path, set[str]] = {}
        self._stuck: set[Path] = set()

    def streams(self) -> list[str]:
        return list(STREAM_KINDS)

    def pull_after(self, stream: str, position: str | None, *, now: datetime) -> Pull:
        """The oldest finished file's records for the stream, and the latest capture time by now."""
        listed = self._listed.get(stream)
        if listed is None:
            raise SpoolError(
                f"the spool feeds {', '.join(map(repr, STREAM_KINDS))}, not {stream!r}"
            )
        if not listed:
            found = finished_files(self.folder)
            self._forget_all_but(found)
            listed.extend(p for p in found if p not in self._stuck)
        if not listed:
            return Pull((), 0, None, None)
        path = listed[0]
        more = len(listed) > 1
        try:
            lines, identity = read_file(path)
        except FileNotFoundError:
            return self._empty(partial(self._drop, stream, path), more)
        except OSError as exc:
            return self._empty(partial(self._unreadable_by, stream, path, str(exc)), more)
        read = _read_records(lines, now, stream, path.name)
        if read.rejected:
            log.warning(
                "unusable spool records skipped",
                extra={
                    "file": path.name,
                    "stream": stream,
                    "rejected": read.rejected,
                    "line": read.first_problem[0],
                    "error": read.first_problem[1],
                },
            )
        finish: Finish = remove_finished
        if read.file_unusable:
            kept = "its usable lines are stored" if read.file_usable else "no line is usable"
            finish = partial(
                _move_aside,
                error=f"it has {read.file_unusable} unusable line(s),"
                f" {read.file_kindless} of no readable kind ({kept})",
            )
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
            after_commit=partial(self._stored_by, stream, path, identity, finish),
        )

    def _empty(self, after_commit: Callable[[], None], more: bool) -> Pull:
        return Pull((), 0, None, None, more=more, after_commit=after_commit)

    def _stored_by(self, stream: str, path: Path, identity: FileIdentity, finish: Finish) -> None:
        self._unreadable.get(path, set()).discard(stream)
        streams = self._stored.setdefault((path, identity), set())
        streams.add(stream)
        if len(streams) < len(STREAM_KINDS):
            self._drop(stream, path)
            return
        del self._stored[(path, identity)]
        self._finish(stream, path, finish)

    def _unreadable_by(self, stream: str, path: Path, problem: str) -> None:
        failed = self._unreadable.setdefault(path, set())
        failed.add(stream)
        stored_by_any = any(key[0] == path for key in self._stored)
        if stored_by_any or len(failed) < len(STREAM_KINDS):
            log.warning(
                "spool file unreadable, will retry",
                extra={"file": path.name, "stream": stream, "error": problem},
            )
            self._drop(stream, path)
            return
        del self._unreadable[path]
        self._finish(stream, path, partial(_move_aside, error=f"cannot read it: {problem}"))

    def _finish(self, stream: str, path: Path, finish: Finish) -> None:
        self._drop(stream, path)
        if self.hold is not None and self.hold.active:
            return
        try:
            finish(path)
        except SpoolError:
            self._stuck.add(path)
            raise

    def _drop(self, stream: str, path: Path) -> None:
        listed = self._listed[stream]
        if path in listed:
            listed.remove(path)

    def _forget_all_but(self, present: list[Path]) -> None:
        names = set(present)
        for key in [key for key in self._stored if key[0] not in names]:
            del self._stored[key]
        for path in [path for path in self._unreadable if path not in names]:
            del self._unreadable[path]


@dataclass(frozen=True)
class _Read:
    observations: tuple[Observation, ...]
    rejected: int
    latest: datetime | None
    first_problem: tuple[int, str]
    file_usable: int
    file_unusable: int
    file_kindless: int


def _read_records(lines: list[bytes], now: datetime, stream: str, name: str) -> _Read:
    kinds = STREAM_KINDS[stream]
    observations: list[Observation] = []
    rejected = usable = unusable = kindless = 0
    latest: datetime | None = None
    first_problem = (0, "")
    for number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            line = raw.decode("utf-8")
            record = parse_record(line)
        except (UnicodeDecodeError, InvalidRecord) as exc:
            unusable += 1
            kind = exc.kind if isinstance(exc, InvalidRecord) else None
            kindless += kind is None
            if kind in kinds:
                rejected += 1
                if not first_problem[0]:
                    first_problem = (number, _problem(exc))
            log.debug(
                "unusable spool record",
                extra={"file": name, "stream": stream, "line": number, "error": str(exc)},
            )
            continue
        usable += 1
        if record.kind not in kinds:
            continue
        observations.append(
            Observation(stream, record.id, record.captured_at, record.captured_at, line)
        )
        if record.captured_at <= now and (latest is None or record.captured_at > latest):
            latest = record.captured_at
    return _Read(tuple(observations), rejected, latest, first_problem, usable, unusable, kindless)


def _problem(exc: UnicodeDecodeError | InvalidRecord) -> str:
    return exc.problem if isinstance(exc, InvalidRecord) else "not UTF-8"


def _move_aside(path: Path, *, error: str) -> None:
    target = set_aside(path)
    if target is not None:
        log.warning(
            "spool file set aside",
            extra={"file": path.name, "target": str(target), "error": error},
        )
