"""How the watch loop's recent cycles went, kept in a small file beside the database."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from computer_history.sources.runner import CycleSummary

__all__ = [
    "ALERT_AFTER_FAILURES",
    "ALERT_REPEAT",
    "HEALTH_FILE_NAME",
    "HEALTH_STALE_AFTER",
    "FailureStreak",
    "IngestHealth",
    "Recovery",
    "health_path",
    "read_health",
    "write_health",
]

HEALTH_FILE_NAME = "ingest-health.json"
ALERT_AFTER_FAILURES = 5
ALERT_REPEAT = timedelta(hours=1)
HEALTH_STALE_AFTER = timedelta(minutes=5)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestHealth:
    """The watch loop's last cycle, how many cycles in a row failed, since when, and why."""

    updated_at: datetime
    consecutive_failures: int = 0
    failing_since: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None

    def stale(self, now: datetime) -> bool:
        """No cycle has been recorded for longer than a watching loop ever waits."""
        return now - self.updated_at > HEALTH_STALE_AFTER


def health_path(db_path: Path) -> Path:
    """The ingest health file beside the database."""
    return db_path.parent / HEALTH_FILE_NAME


def write_health(path: Path, health: IngestHealth) -> None:
    """Write the health file through a temporary file renamed over it."""
    doc = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in asdict(health).items()}
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_health(path: Path) -> IngestHealth | None:
    """The saved health, or None if no watch loop has saved one yet."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    try:
        return IngestHealth(
            updated_at=datetime.fromisoformat(doc["updated_at"]),
            consecutive_failures=int(doc["consecutive_failures"]),
            failing_since=_time(doc.get("failing_since")),
            last_success_at=_time(doc.get("last_success_at")),
            last_error=doc.get("last_error"),
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"not an ingest health file: {exc!r}") from exc


def _time(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


@dataclass(frozen=True)
class Recovery:
    """A run of failed cycles that a successful one just ended."""

    failed_cycles: int
    down_since: datetime


class FailureStreak:
    """Counts failed cycles in a row, saving the health after each cycle.

    It notifies at the threshold, at most once per repeat while failures last, and when they end.
    """

    def __init__(
        self,
        *,
        save: Callable[[IngestHealth], None],
        notify: Callable[[str], None] | None,
        health: IngestHealth | None = None,
        threshold: int = ALERT_AFTER_FAILURES,
        repeat: timedelta = ALERT_REPEAT,
    ) -> None:
        self.health = health
        self._save = save
        self._notify = notify
        self._threshold = threshold
        self._repeat = repeat
        self._alerted_at: datetime | None = None

    @property
    def failures(self) -> int:
        return 0 if self.health is None else self.health.consecutive_failures

    def record(self, summary: CycleSummary) -> Recovery | None:
        """Count the cycle, save the health, notify if due, and return the streak it ended."""
        before = self.health
        recovery = None
        if summary.ok:
            if before is not None and before.failing_since is not None and self.failures:
                recovery = Recovery(self.failures, before.failing_since)
            self.health = IngestHealth(summary.at, last_success_at=summary.at)
            if self._alerted_at is not None:
                self._send("ingest recovered.")
            self._alerted_at = None
        else:
            since = before.failing_since if before is not None and self.failures else None
            self.health = IngestHealth(
                summary.at,
                self.failures + 1,
                since or summary.at,
                None if before is None else before.last_success_at,
                "; ".join(
                    f"{f.stream}: {f.error}" if f.stream else f.error for f in summary.failures
                ),
            )
            if self.failures >= self._threshold and (
                self._alerted_at is None or summary.at - self._alerted_at >= self._repeat
            ):
                self._alerted_at = summary.at
                self._send(
                    f"ingest failing for {self.failures:,} cycles."
                    " Run `computer-history status`."
                )
        try:
            self._save(self.health)
        except OSError as exc:
            log.warning("ingest health not saved", extra={"error": str(exc)})
        return recovery

    def _send(self, text: str) -> None:
        if self._notify is not None:
            self._notify(text)
