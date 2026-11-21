"""Each ingest cycle's one log record, counted toward the failure streak when there is one."""

from __future__ import annotations

import logging
from collections.abc import Callable

from computer_history.logs import SHOWN_FIELD
from computer_history.sources.commit import FailureKind
from computer_history.sources.ingest_health import FailureStreak
from computer_history.sources.runner import CycleSummary, IngestOutcome

__all__ = ["CycleReporter"]

log = logging.getLogger(__name__)

Cause = tuple[FailureKind, str, str]


class CycleReporter:
    """Writes each cycle's record, INFO if every stream committed and ERROR if not.

    A cause's first failure in a streak carries its traceback; a streak's end has its own record.
    """

    def __init__(
        self,
        describe: Callable[[CycleSummary], str],
        *,
        streak: FailureStreak | None = None,
        shown: bool = False,
    ) -> None:
        self._describe = describe
        self._streak = streak
        self._shown = shown
        self._seen: set[Cause] = set()

    def __call__(self, summary: CycleSummary, delay: float | None = None) -> None:
        recovery = None if self._streak is None else self._streak.record(summary)
        fields: dict[str, object] = {
            "duration_ms": round(summary.duration_s * 1000),
            "streams": {name: _counts(o) for name, o in summary.outcomes.items()},
        }
        if self._shown:
            fields[SHOWN_FIELD] = True
        if summary.ok:
            self._seen.clear()
            log.info("cycle ok: %s", self._describe(summary) or "no streams", extra=fields)
        else:
            fields["failures"] = [
                {"stream": f.stream, "kind": f.kind.value, "error": f.error}
                for f in summary.failures
            ]
            if delay is not None:
                fields["retry_s"] = round(delay)
            if self._streak is not None:
                fields["streak"] = self._streak.failures
            log.error(
                "cycle failed: %s",
                self._describe(summary),
                extra=fields,
                exc_info=self._new_cause(summary),
            )
        if recovery is not None:
            log.info(
                "ingest recovered",
                extra={
                    "failed_cycles": recovery.failed_cycles,
                    "failing_since": recovery.failing_since.isoformat(),
                },
            )

    def _new_cause(self, summary: CycleSummary) -> BaseException | None:
        for failure in summary.failures:
            if failure.kind is FailureKind.SOURCE or failure.exc is None:
                continue
            cause = (failure.kind, type(failure.exc).__name__, failure.error)
            if cause not in self._seen:
                self._seen.add(cause)
                return failure.exc
        return None


def _counts(outcome: IngestOutcome) -> dict[str, int]:
    return {
        "inserted": outcome.inserted,
        "skipped": outcome.skipped,
        "held_back": outcome.held_back,
        "rejected": outcome.rejected,
    }
