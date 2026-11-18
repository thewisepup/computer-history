"""Event sources: the ActivityWatch adapter and backfill, re-exported here."""

from computer_history.sources import activitywatch, backfill
from computer_history.sources.activitywatch import *  # noqa: F403  (re-export; see __all__)
from computer_history.sources.backfill import *  # noqa: F403  (re-export; see __all__)

__all__ = [*activitywatch.__all__, *backfill.__all__]
