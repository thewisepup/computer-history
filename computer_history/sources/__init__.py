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
          |          pulling again while a pull says there is more
      backfill.py    plan a stream's history in chunks, then ingest them oldest first
          |
      projection.py  routes each observation to the projector of the source that
          |          claims its stream: ingest and rebuild-signals both use it
      commit.py      shared by poll and backfill: one pull, its signals and its
          |          progress in one commit, then the pull's after-commit step,
          |          and which failures stop a run
      store/         insert_observations, rebuild_signals (each projects through
                     the projector it is given)

    agent_health.py  for status: the capture agent's stored records and spool,
                     judged against aw-afk and aw-window, drawing on both adapters
"""

from computer_history.sources import (
    activitywatch,
    agent_health,
    backfill,
    capture_spool,
    commit,
    contract,
    projection,
    runner,
)
from computer_history.sources.activitywatch import *  # noqa: F403
from computer_history.sources.agent_health import *  # noqa: F403
from computer_history.sources.backfill import *  # noqa: F403
from computer_history.sources.capture_spool import *  # noqa: F403
from computer_history.sources.commit import *  # noqa: F403
from computer_history.sources.contract import *  # noqa: F403
from computer_history.sources.projection import *  # noqa: F403
from computer_history.sources.runner import *  # noqa: F403

__all__ = [
    *contract.__all__,
    *commit.__all__,
    *projection.__all__,
    *runner.__all__,
    *backfill.__all__,
    *activitywatch.__all__,
    *capture_spool.__all__,
    *agent_health.__all__,
]
