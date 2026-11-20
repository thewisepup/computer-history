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
"""

from computer_history.synthetic.build import (
    RENDERERS,
    BuildFailed,
    Dataset,
    backfill_feeds,
    build_dataset,
    build_timeline,
    poll_feeds,
)
from computer_history.synthetic.generate import (
    PERSONAS,
    TIERS,
    DatasetInputs,
    generate_timeline,
)
from computer_history.synthetic.manifest import GENERATOR_VERSION, Captures, Manifest, Totals
from computer_history.synthetic.scenarios import SCENARIOS
from computer_history.synthetic.timeline import Fault, FaultKind, Stretch, StretchKind, Timeline

__all__ = [
    "GENERATOR_VERSION",
    "PERSONAS",
    "RENDERERS",
    "SCENARIOS",
    "TIERS",
    "BuildFailed",
    "Captures",
    "Dataset",
    "DatasetInputs",
    "Fault",
    "FaultKind",
    "Manifest",
    "Stretch",
    "StretchKind",
    "Timeline",
    "Totals",
    "backfill_feeds",
    "build_dataset",
    "build_timeline",
    "generate_timeline",
    "poll_feeds",
]
