"""Sources and the ingest runner that reads them into the store.

    activitywatch/   an adapter: names its streams, pulls settled observations
          |          and says where each stream's progress now stands
      contract.py    what an adapter implements: Source (streams + pull after a
          |          position), HistorySource (adds history facts + range pulls)
          |
      runner.py      poll every stream of every source, once or in the watch loop
      backfill.py    plan a stream's history in chunks, then ingest them oldest first
          |
      commit.py      shared by both: one pull and its progress in one commit, and
          |          which failures stop a run (source unavailable, database)
      store/         insert_observations
"""

from computer_history.sources import activitywatch, backfill, commit, contract, runner
from computer_history.sources.activitywatch import *  # noqa: F403  (re-export; see __all__)
from computer_history.sources.backfill import *  # noqa: F403  (re-export; see __all__)
from computer_history.sources.commit import *  # noqa: F403  (re-export; see __all__)
from computer_history.sources.contract import *  # noqa: F403  (re-export; see __all__)
from computer_history.sources.runner import *  # noqa: F403  (re-export; see __all__)

__all__ = [
    *contract.__all__,
    *commit.__all__,
    *runner.__all__,
    *backfill.__all__,
    *activitywatch.__all__,
]
