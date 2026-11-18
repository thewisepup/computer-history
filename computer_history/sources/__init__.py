"""Event sources: ActivityWatch ingest adapters (Milestone 1).

The public names are defined once, in each module's ``__all__``, and re-exported here.
"""

from computer_history.sources import activitywatch, backfill
from computer_history.sources.activitywatch import *  # noqa: F403  (re-export; see __all__)
from computer_history.sources.backfill import *  # noqa: F403  (re-export; see __all__)

__all__ = [*activitywatch.__all__, *backfill.__all__]
