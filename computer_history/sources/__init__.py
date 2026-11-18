"""Sources and the ingest runner that reads them into the store.

    activitywatch/   an adapter: names its streams, pulls settled raw observations,
          |          says where each stream's progress now stands, and supplies
          |          a projector (stored payload -> signal) for each stream
      contract.py    what an adapter implements: Source (projectors, streams + pull
          |          after a position), HistorySource (adds history facts + range pulls)
          |
      runner.py      poll every stream of every source, once or in the watch loop
      backfill.py    plan a stream's history in chunks, then ingest them oldest first
          |
      projection.py  routes each observation to the projector of the source that
          |          claims its stream: ingest and rebuild-signals both use it
      commit.py      shared by poll and backfill: one pull, its signals and its
          |          progress in one commit, and which failures stop a run
      store/         insert_observations, rebuild_signals (each projects through
                     the projector it is given)
"""

from computer_history.sources import activitywatch, backfill, commit, contract, projection, runner
from computer_history.sources.activitywatch import *  # noqa: F403  (re-export; see __all__)
from computer_history.sources.backfill import *  # noqa: F403  (re-export; see __all__)
from computer_history.sources.commit import *  # noqa: F403  (re-export; see __all__)
from computer_history.sources.contract import *  # noqa: F403  (re-export; see __all__)
from computer_history.sources.projection import *  # noqa: F403  (re-export; see __all__)
from computer_history.sources.runner import *  # noqa: F403  (re-export; see __all__)

__all__ = [
    *contract.__all__,
    *commit.__all__,
    *projection.__all__,
    *runner.__all__,
    *backfill.__all__,
    *activitywatch.__all__,
]
