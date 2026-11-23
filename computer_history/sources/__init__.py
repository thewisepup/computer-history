"""Sources and the ingest runner that reads them into the store.

activitywatch/   an adapter: names its streams, pulls settled raw observations,
      |          says where each stream's progress now stands, and supplies
      |          a projector (stored payload -> signal) for each stream
capture_spool/   the same for the capture spool's ax-text and screenshot streams:
      |          one finished file per pull, removed once both streams committed it
  contract.py    what an adapter implements: Source (projectors, streams + pull
      |          after a position), HistorySource (adds history facts + range pulls)
      |
  runner.py      poll every stream of every source, once or in the watch loop,
      |          pulling again while a pull says there is more; a source that
      |          fails, expectedly or not, skips only its own streams
  ingest_health.py  the watch loop's last cycle and failure streak, in one file
      |          beside the database rewritten after every cycle, with an alert
      |          through the host adapter when a streak lasts and when it ends
  cycle_report.py   each cycle's one log record, counted toward that streak
      |
  backfill.py    plan a stream's history in chunks, then ingest them oldest first
      |
  projection.py  routes each observation to the projector of the source that
      |          claims its stream: ingest and rebuild-signals both use it
  commit.py      shared by poll and backfill: one pull, its signals and its
      |          progress in one commit, then the pull's after-commit step,
      |          and which failures stop a run
  store/         insert_observations, rebuild_signals (each projects through
                 the projector it is given)

agent_health.py  for status, the watchdog and update's agent check: the capture
                 agent's stored records and spool, judged against aw-afk and
                 aw-window, drawing on both adapters; update reads them afresh
                 through StoredAndSpooled
"""

from computer_history.sources.activitywatch import ActivityWatch, AWClient
from computer_history.sources.agent_health import (
    CaptureHealth,
    CaptureLiveness,
    DatabaseRead,
    StoredAndSpooled,
    active_spans,
    capture_health,
    capture_liveness,
)
from computer_history.sources.backfill import (
    BACKFILL_CHUNK,
    BackfillPlan,
    BackfillProgress,
    BackfillResult,
    Chunk,
    ChunkDone,
    plan_all_backfills,
    plan_backfill,
    run_backfill,
)
from computer_history.sources.capture_spool import CaptureSpool, resolve_spool_path
from computer_history.sources.commit import FailureKind, StreamFailure, commit_pull, failure_of
from computer_history.sources.contract import (
    HistorySource,
    Pull,
    Source,
    SourceUnavailable,
    StreamProjector,
)
from computer_history.sources.cycle_report import CycleReporter
from computer_history.sources.ingest_health import (
    ALERT_AFTER_FAILURES,
    FailureStreak,
    IngestHealth,
    Recovery,
    StreakAlert,
    health_path,
    read_health,
    write_health,
)
from computer_history.sources.projection import KNOWN_SOURCES, projector_for, reproject_signals
from computer_history.sources.runner import (
    POLL_INTERVAL_SECONDS,
    CycleSummary,
    IngestOutcome,
    poll,
    watch,
)

__all__ = [
    "ALERT_AFTER_FAILURES",
    "BACKFILL_CHUNK",
    "KNOWN_SOURCES",
    "POLL_INTERVAL_SECONDS",
    "AWClient",
    "ActivityWatch",
    "BackfillPlan",
    "BackfillProgress",
    "BackfillResult",
    "CaptureHealth",
    "CaptureLiveness",
    "CaptureSpool",
    "Chunk",
    "ChunkDone",
    "CycleReporter",
    "CycleSummary",
    "DatabaseRead",
    "FailureKind",
    "FailureStreak",
    "HistorySource",
    "IngestHealth",
    "IngestOutcome",
    "Pull",
    "Recovery",
    "Source",
    "SourceUnavailable",
    "StoredAndSpooled",
    "StreakAlert",
    "StreamFailure",
    "StreamProjector",
    "active_spans",
    "capture_health",
    "capture_liveness",
    "commit_pull",
    "failure_of",
    "health_path",
    "plan_all_backfills",
    "plan_backfill",
    "poll",
    "projector_for",
    "read_health",
    "reproject_signals",
    "resolve_spool_path",
    "run_backfill",
    "watch",
    "write_health",
]
