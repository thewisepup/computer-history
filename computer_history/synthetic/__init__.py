"""Synthetic datasets: believable activity built through the real ingest path.

    generate.py         the inputs (persona, scenario, tier, seed) -> one timeline
          |             persona.py: who the user is, as typed config
          |             developer.py: the developer persona
          |             days.py: the ordinary days a persona lives through
          |             scenarios.py: what happens, placed on the ordinary timeline
          |             timeline.py: stretches and faults, in fixed UTC time
          |             seeds.py: one seeded random generator per part
          |
      renderer.py       what a renderer is: timeline -> one source family's raw data
      activitywatch.py  window, AFK and web buckets as the watchers leave them
          |             afk.py: the AFK spans aw-watcher-afk reports
          |             aw_api.py: the buckets served in process, as the real API
      spool.py          the capture agent's records, in finished one-minute spool files
          |             captures.py: when the agent captures, by its schedule
          |
      build.py          render, backfill and poll into a new database, at a fixed now
      manifest.py       the true answers, from the timeline and never the database
          |
      cache.py          built datasets per user, keyed by inputs and code, renamed into place
      devdb.py          a cached dataset copied out for local use, never over the live database
"""

from computer_history.synthetic.build import (
    DATABASE_NAME,
    MANIFEST_NAME,
    RENDERERS,
    BuildFailed,
    Dataset,
    backfill_feeds,
    build_dataset,
    build_timeline,
    poll_feeds,
)
from computer_history.synthetic.cache import (
    CACHE_ENV_VAR,
    CachedDataset,
    cache_root,
    cached_dataset,
    copy_dataset,
    dataset_key,
    open_cached,
)
from computer_history.synthetic.devdb import (
    DevDatabase,
    LiveDatabaseRefused,
    OutputExists,
    live_folders,
    make_dev_database,
)
from computer_history.synthetic.generate import (
    PERSONAS,
    TIERS,
    DatasetInputs,
    generate_timeline,
)
from computer_history.synthetic.manifest import (
    GENERATOR_VERSION,
    CaptureCounts,
    Manifest,
    Totals,
)
from computer_history.synthetic.scenarios import SCENARIOS
from computer_history.synthetic.timeline import Fault, FaultKind, Stretch, StretchKind, Timeline

__all__ = [
    "CACHE_ENV_VAR",
    "DATABASE_NAME",
    "GENERATOR_VERSION",
    "MANIFEST_NAME",
    "PERSONAS",
    "RENDERERS",
    "SCENARIOS",
    "TIERS",
    "BuildFailed",
    "CachedDataset",
    "CaptureCounts",
    "Dataset",
    "DatasetInputs",
    "DevDatabase",
    "Fault",
    "FaultKind",
    "LiveDatabaseRefused",
    "Manifest",
    "OutputExists",
    "Stretch",
    "StretchKind",
    "Timeline",
    "Totals",
    "backfill_feeds",
    "build_dataset",
    "build_timeline",
    "cache_root",
    "cached_dataset",
    "copy_dataset",
    "dataset_key",
    "generate_timeline",
    "live_folders",
    "make_dev_database",
    "open_cached",
    "poll_feeds",
]
