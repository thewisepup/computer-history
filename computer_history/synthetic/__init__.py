"""Synthetic datasets: believable activity built through the real ingest path.

    generate.py         the inputs (persona, scenario, tier, heavy, seed) -> one timeline
          |             persona.py: who the user is, as typed config, and a heavier user
          |             developer.py: the developer persona
          |             content_creator.py: the content-creator persona
          |             days.py: the ordinary days a persona lives through
          |             scenarios.py: what happens, placed on the ordinary timeline
          |             timeline.py: stretches and faults, in fixed UTC time
          |             spans.py: (start, end) spans merged, intersected and complemented
          |             seeds.py: one seeded random generator per part
          |
      renderer.py       what a renderer is: timeline -> one source family's raw data
      activitywatch.py  window, AFK and web buckets as the watchers leave them
          |             afk.py: the AFK spans aw-watcher-afk reports
          |             aw_api.py: the buckets served in process, as the real API
      spool.py          the capture agent's records, in finished one-minute spool files
          |             captures.py: the records the agent writes, by its schedule
          |             screenshots.py: the screenshot each capture takes, kept or a duplicate
          |
      build.py          render, backfill and poll into a new database, at a fixed now
      manifest.py       the true answers, from the timeline and never the database
          |             gaps.py: the stretches each source leaves unobserved, and explained gaps
          |
      cache.py          built datasets per user, keyed by inputs and code, renamed into place
      devdb.py          a cached dataset copied out for local use, never over the live database
          |
      operations.py     what the product does (ingest, rebuild, status reads), on a cached dataset
      meter.py          the statements, VM steps, full scans and pages one operation costs
      gate.py           those costs per operation and dataset against the committed baseline
          |             baseline.py: the committed costs, one file per SQLite version
      bench.py          each operation's median wall-clock time against this machine's baseline
"""

from computer_history.synthetic.baseline import (
    BASELINE_DIR,
    Baseline,
    baseline_file,
    compared_baseline,
    load_baseline,
    save_baseline,
)
from computer_history.synthetic.bench import (
    BENCH_BASELINE_NAME,
    RUNS,
    SLOWDOWN_TOLERANCE,
    BenchReport,
    Timing,
    bench_baseline_path,
    run_bench,
    time_operation,
)
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
    OutputExists,
    OutputNotAFolder,
    live_folders,
    make_dev_database,
)
from computer_history.synthetic.gaps import ExplainedGap
from computer_history.synthetic.gate import (
    EXPECTED_SCALING_FAILURES,
    GATE_DATASETS,
    NIGHTLY_DATASETS,
    PERF_DATASETS,
    SCAN_ALLOWLIST,
    SMALLEST_DATASET,
    UNEXPECTED_PASS_HINT,
    Finding,
    FindingKind,
    GateReport,
    compare,
    perf_datasets,
    run_gate,
    scaling,
)
from computer_history.synthetic.generate import (
    HEAVY,
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
from computer_history.synthetic.meter import Costs, Scan, StatementCost, measure, statement_text
from computer_history.synthetic.operations import (
    OPERATIONS,
    GateDataset,
    Operation,
    gate_dataset,
    measure_operation,
    started,
)
from computer_history.synthetic.scenarios import SCENARIOS
from computer_history.synthetic.timeline import Fault, FaultKind, Stretch, StretchKind, Timeline

__all__ = [
    "BASELINE_DIR",
    "BENCH_BASELINE_NAME",
    "CACHE_ENV_VAR",
    "DATABASE_NAME",
    "EXPECTED_SCALING_FAILURES",
    "UNEXPECTED_PASS_HINT",
    "GATE_DATASETS",
    "GENERATOR_VERSION",
    "HEAVY",
    "MANIFEST_NAME",
    "NIGHTLY_DATASETS",
    "OPERATIONS",
    "PERF_DATASETS",
    "PERSONAS",
    "RENDERERS",
    "RUNS",
    "SCAN_ALLOWLIST",
    "SCENARIOS",
    "SLOWDOWN_TOLERANCE",
    "SMALLEST_DATASET",
    "TIERS",
    "Baseline",
    "BenchReport",
    "BuildFailed",
    "CachedDataset",
    "CaptureCounts",
    "Costs",
    "Dataset",
    "DatasetInputs",
    "DevDatabase",
    "ExplainedGap",
    "Fault",
    "FaultKind",
    "Finding",
    "FindingKind",
    "GateDataset",
    "GateReport",
    "Manifest",
    "Operation",
    "OutputExists",
    "OutputNotAFolder",
    "Scan",
    "StatementCost",
    "Stretch",
    "StretchKind",
    "Timeline",
    "Timing",
    "Totals",
    "backfill_feeds",
    "baseline_file",
    "bench_baseline_path",
    "build_dataset",
    "build_timeline",
    "cache_root",
    "cached_dataset",
    "compare",
    "compared_baseline",
    "copy_dataset",
    "dataset_key",
    "gate_dataset",
    "generate_timeline",
    "live_folders",
    "load_baseline",
    "make_dev_database",
    "measure",
    "measure_operation",
    "perf_datasets",
    "open_cached",
    "poll_feeds",
    "run_bench",
    "run_gate",
    "save_baseline",
    "scaling",
    "started",
    "statement_text",
    "time_operation",
]
