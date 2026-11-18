"""Event sources: ActivityWatch ingest adapters (Milestone 1).

The public names are defined once, in ``activitywatch.__all__``, and re-exported here.
"""

from computer_history.sources import activitywatch
from computer_history.sources.activitywatch import *  # noqa: F403  (re-export; see __all__)

__all__ = list(activitywatch.__all__)
