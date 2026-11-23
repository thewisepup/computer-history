"""How the watch loop's cycles went, kept in one file beside the database, and its streak alerts."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from computer_history.host import ALERT_REPEAT
from computer_history.sources.commit import FailureKind
from computer_history.sources.runner import CycleSummary
from computer_history.store import replace_atomically, to_utc

__all__ = [
    "ALERT_AFTER_FAILURES",
    "FailureStreak",
    "IngestHealth",
    "Recovery",
    "StreakAlert",
    "health_path",
    "read_health",
    "write_health",
]

HEALTH_FILE_NAME = "ingest-health.json"
ALERT_AFTER_FAILURES = 5

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestHealth:
    """The watch loop's last cycle, how many cycles in a row failed, since when, and why.

    alerted_at is when the current failure streak last notified; sources_unavailable marks a
    failed last cycle whose every failure was a source it could not read.
    """

    cycle_at: datetime
    consecutive_failures: int = 0
    failing_since: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    alerted_at: datetime | None = None
    sources_unavailable: bool = False

    @property
    def ok(self) -> bool:
        return self.consecutive_failures == 0


def health_path(db_path: Path) -> Path:
    """The ingest health file beside the database."""
    return db_path.parent / HEALTH_FILE_NAME


def write_health(path: Path, health: IngestHealth) -> None:
    """Replace the health file in one step."""
    doc = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in asdict(health).items()}
    text = json.dumps(doc, indent=2) + "\n"
    replace_atomically(path, lambda staged: staged.write_text(text, encoding="utf-8"))


def read_health(path: Path) -> IngestHealth | None:
    """The saved health, or None if no watch loop has saved one yet."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except RecursionError as exc:
        raise ValueError(f"not an ingest health file: {exc!r}") from exc
    try:
        unavailable = doc.get("sources_unavailable", False)
        if not isinstance(unavailable, bool):
            raise TypeError(f"sources_unavailable is {unavailable!r}, not true or false")
        return IngestHealth(
            cycle_at=to_utc(doc["cycle_at"]),
            consecutive_failures=int(doc["consecutive_failures"]),
            failing_since=_time(doc.get("failing_since")),
            last_success_at=_time(doc.get("last_success_at")),
            last_error=doc.get("last_error"),
            alerted_at=_time(doc.get("alerted_at")),
            sources_unavailable=unavailable,
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"not an ingest health file: {exc!r}") from exc


def _time(value: str | None) -> datetime | None:
    return None if value is None else to_utc(value)


@dataclass(frozen=True)
class Recovery:
    """A run of failed cycles that a successful one just ended."""

    failed_cycles: int
    failing_since: datetime


@dataclass(frozen=True)
class StreakAlert:
    """A failure streak to tell someone about: how many cycles it has lasted, and if it ended."""

    failures: int
    ended: bool = False

    @property
    def message(self) -> str:
        """The notification text, which names the streak and never its error."""
        if self.ended:
            return "ingest recovered."
        return f"ingest failing for {self.failures:,} cycles. Run `computer-history status`."


class FailureStreak:
    """Counts failed cycles in a row, saving the health after each cycle.

    It alerts at ALERT_AFTER_FAILURES, at most once per ALERT_REPEAT while failures last, and
    when they end.
    """

    def __init__(
        self,
        *,
        save: Callable[[IngestHealth], None],
        notify: Callable[[StreakAlert], None] | None,
        health: IngestHealth | None = None,
    ) -> None:
        self.health = health
        self._save = save
        self._notify = notify

    @property
    def failures(self) -> int:
        return 0 if self.health is None else self.health.consecutive_failures

    def record(self, summary: CycleSummary) -> Recovery | None:
        """Count the cycle, save the health, alert if due, and return the streak it ended."""
        before, failures = self.health, self.failures
        alerted = None if before is None else before.alerted_at
        recovery = None
        if summary.ok:
            if before is not None and before.failing_since is not None and failures:
                recovery = Recovery(failures, before.failing_since)
            self.health = IngestHealth(summary.at, last_success_at=summary.at)
            if alerted is not None:
                self._send(StreakAlert(failures, ended=True))
        else:
            since = before.failing_since if before is not None and failures else None
            due = failures + 1 >= ALERT_AFTER_FAILURES and (
                alerted is None or summary.at - alerted >= ALERT_REPEAT
            )
            self.health = IngestHealth(
                summary.at,
                failures + 1,
                since or summary.at,
                None if before is None else before.last_success_at,
                "; ".join(
                    f"{f.stream}: {f.error}" if f.stream else f.error for f in summary.failures
                ),
                summary.at if due else alerted,
                all(f.kind is FailureKind.SOURCE for f in summary.failures),
            )
            if due:
                self._send(StreakAlert(failures + 1))
        try:
            self._save(self.health)
        except OSError as exc:
            log.warning("ingest health not saved", extra={"error": str(exc)})
        return recovery

    def _send(self, alert: StreakAlert) -> None:
        if self._notify is not None:
            self._notify(alert)
