"""The synthetic datasets keep up with every stream, table, timeline field and store read."""

from __future__ import annotations

import inspect
import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import MISSING, fields, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from types import CodeType

import pytest

import computer_history.store as store
from computer_history.sources import KNOWN_SOURCES, WINDOW_SOURCE
from computer_history.store import table_counts
from computer_history.synthetic import (
    GATE_DATASETS,
    OPERATIONS,
    RENDERERS,
    SMALLEST,
    Fault,
    FaultKind,
    GateDataset,
    Stretch,
    StretchKind,
    Timeline,
    cached_dataset,
    gate_dataset,
    open_cached,
)
from computer_history.synthetic.build import render_sources
from computer_history.synthetic.manifest import true_answers

TABLE_EXEMPTIONS: Mapping[str, str] = {
    "projects": "classification (M5) proposes projects; no generator until M5 defines them",
    "work_types": "classification (M5) picks from the active work types; no generator until M5",
    "blocks": "classification (M5) assembles blocks; no generator until M5",
    "block_tags": "classification (M5) tags blocks; no generator until M5",
    "classification_runs": "classification (M5) records its runs; no generator until M5",
    "reviews": "the weekly review (M7) stores reviews; no generator until M7",
    "suggestions": "the weekly review (M7) stores suggestions; no generator until M7",
}
FIELD_EXEMPTIONS: Mapping[tuple[type, str], str] = {
    (Stretch, "work_type"): "a classifier-eval label the manifest records once M5 needs it",
}
STORE_EXEMPTIONS: Mapping[str, str] = {
    "content_digest": "the build's determinism check, never run by the product",
    "migrate": "runs once as a connection opens, before any operation starts",
    "schema_version": "runs once as a connection opens, before any operation starts",
    "page_counts": "the cost meter's own measurement of database pages",
    "scanned_tables": "the cost meter's own reading of query plans",
    "sqlite_build": "the cost meter's record of the SQLite it ran on",
}
PROBES: Mapping[tuple[type, str], object] = {
    (Fault, "sources"): (WINDOW_SOURCE,),
}
REQUIRED_FIELDS = {"start", "end", "kind"}

T0 = datetime(2026, 1, 5, 17, 0, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


REVIEW = Stretch(
    at(0),
    at(5),
    app="Google Chrome",
    title="Pull request #1",
    url="https://github.com/acme/api/pull/1",
    text="def total(): return 1",
    project="api",
    work_type="review",
)
PROBED_STRETCH = 1
PROBED_FAULT = 0
PROBE_TIMELINE = Timeline(
    T0,
    at(30),
    "UTC",
    (
        REVIEW,
        replace(REVIEW, start=at(5), end=at(10)),
        Stretch(at(10), at(20), app="Cursor", title="main.py", text="print(1)", project="api"),
        Stretch(at(20), at(30), kind=StretchKind.ASLEEP),
    ),
    (Fault(at(12), at(14), FaultKind.AW_DOWN),),
)


@pytest.fixture(scope="module")
def gate_day(tmp_path_factory: pytest.TempPathFactory) -> GateDataset:
    inputs = GATE_DATASETS[SMALLEST]
    return gate_dataset(inputs, cached_dataset(inputs, tmp_path_factory.mktemp("cache")))


def test_every_stream_a_source_projects_has_a_renderer(gate_day: GateDataset) -> None:
    projected = {stream for source in KNOWN_SOURCES for stream in source.projectors}
    rendered = {stream: renderer.name for renderer in RENDERERS for stream in renderer.streams}
    observed = json.loads(gate_day.entry.manifest_path.read_text(encoding="utf-8"))["observations"]

    missing = sorted(projected - rendered.keys())
    assert not missing, (
        f"no renderer feeds {missing}: write one and add it to RENDERERS in synthetic/build.py"
    )
    stale = sorted(rendered.keys() - projected)
    assert not stale, f"renderers feed {stale}, which no source in KNOWN_SOURCES projects"
    empty = sorted(stream for stream in projected if not observed.get(stream))
    assert not empty, (
        f"the {SMALLEST} gate dataset holds no observations of {empty}: "
        f"its renderer ({', '.join(rendered[s] for s in empty)}) renders nothing for it"
    )


def test_every_table_has_a_generator_or_an_exemption(gate_day: GateDataset) -> None:
    conn = open_cached(gate_day.entry)
    try:
        counts = table_counts(conn)
    finally:
        conn.close()

    ungenerated = sorted(t for t, n in counts.items() if not n and t not in TABLE_EXEMPTIONS)
    assert not ungenerated, (
        f"the {SMALLEST} gate dataset leaves {ungenerated} empty: render the data ingest fills "
        "them from, or exempt each in TABLE_EXEMPTIONS with a reason"
    )
    stale = sorted(t for t in TABLE_EXEMPTIONS if counts.get(t, 0) or t not in counts)
    assert not stale, f"remove {stale} from TABLE_EXEMPTIONS: each is generated or gone"


def _default_fields(cls: type) -> list[str]:
    return [
        f.name for f in fields(cls) if f.default is not MISSING or f.default_factory is not MISSING
    ]


@pytest.mark.parametrize("cls", [Stretch, Fault], ids=lambda cls: cls.__name__)
def test_every_timeline_field_beyond_start_end_and_kind_has_a_default(cls: type) -> None:
    required = {f.name for f in fields(cls)} - set(_default_fields(cls))

    assert required <= REQUIRED_FIELDS, (
        f"give {cls.__name__}.{', '.join(sorted(required - REQUIRED_FIELDS))} a default, "
        "so personas and scenarios that never set it keep working"
    )


def _changed(cls: type, name: str, value: object) -> object:
    if (cls, name) in PROBES:
        return PROBES[cls, name]
    if isinstance(value, bool):
        return not value
    if isinstance(value, Enum):
        members = list(type(value))
        return members[(members.index(value) + 1) % len(members)]
    if isinstance(value, int | float):
        return value + 1
    if isinstance(value, str):
        return f"{value} changed"
    if value is None:
        return "changed"
    raise AssertionError(f"no way to change {cls.__name__}.{name}: add a value to PROBES")


def _probe(cls: type, name: str) -> Timeline:
    if cls is Stretch:
        stretches = list(PROBE_TIMELINE.stretches)
        target = stretches[PROBED_STRETCH]
        value = _changed(cls, name, getattr(target, name))
        stretches[PROBED_STRETCH] = replace(target, **{name: value})
        return replace(PROBE_TIMELINE, stretches=tuple(stretches))
    faults = list(PROBE_TIMELINE.faults)
    target = faults[PROBED_FAULT]
    faults[PROBED_FAULT] = replace(target, **{name: _changed(cls, name, getattr(target, name))})
    return replace(PROBE_TIMELINE, faults=tuple(faults))


def _outputs(timeline: Timeline) -> tuple[dict[str, object], object]:
    rendered = render_sources(timeline, seed=1)
    return rendered, true_answers(None, timeline, rendered.values(), content_digest="")


def test_rendering_the_same_timeline_twice_compares_equal() -> None:
    assert _outputs(PROBE_TIMELINE) == _outputs(PROBE_TIMELINE), (
        "a renderer's output must compare by value, or the field check below cannot see changes"
    )


TIMELINE_FIELDS = [(cls, name) for cls in (Stretch, Fault) for name in _default_fields(cls)]


@pytest.mark.parametrize(
    ("cls", "name"), TIMELINE_FIELDS, ids=[f"{c.__name__}.{n}" for c, n in TIMELINE_FIELDS]
)
def test_changing_a_timeline_field_changes_a_renderer_or_the_manifest(cls: type, name: str) -> None:
    rendered, manifest = _outputs(PROBE_TIMELINE)
    probed_rendered, probed_manifest = _outputs(_probe(cls, name))
    moved = probed_rendered != rendered or probed_manifest != manifest
    reason = FIELD_EXEMPTIONS.get((cls, name))

    if reason is not None:
        assert not moved, f"{cls.__name__}.{name} is now rendered: remove it from FIELD_EXEMPTIONS"
        return
    assert moved, (
        f"changing {cls.__name__}.{name} changes no renderer's output and not the manifest: "
        "render it, record its truth in the manifest, or exempt it in FIELD_EXEMPTIONS"
    )


def _on_a_connection() -> dict[CodeType, str]:
    found = {}
    for name in store.__all__:
        function = inspect.unwrap(getattr(store, name))
        if not inspect.isfunction(function):
            continue
        first = next(iter(inspect.signature(function).parameters.values()), None)
        if first is not None and (first.name == "conn" or "Connection" in str(first.annotation)):
            found[function.__code__] = name
    return found


def _calls(action: Callable[[], object], watched: Mapping[CodeType, str]) -> set[str]:
    called: set[str] = set()

    def profile(frame, event: str, arg: object) -> None:
        if event == "call" and frame.f_code in watched:
            called.add(watched[frame.f_code])

    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        action()
    finally:
        sys.setprofile(previous)
    return called


def test_every_public_store_read_and_write_runs_in_a_gate_operation(
    gate_day: GateDataset, tmp_path: Path
) -> None:
    reads = _on_a_connection()
    measured: dict[str, set[str]] = {}
    for operation in OPERATIONS.values():
        session = operation.start(gate_day, tmp_path / operation.name)
        try:
            for read in _calls(session.action, reads):
                measured.setdefault(read, set()).add(operation.name)
        finally:
            session.conn.close()

    unmeasured = sorted(set(reads.values()) - measured.keys() - STORE_EXEMPTIONS.keys())
    assert not unmeasured, (
        f"no gate operation runs store.{', store.'.join(unmeasured)}: add an Operation to "
        "OPERATIONS in synthetic/operations.py, or exempt it in STORE_EXEMPTIONS with a reason"
    )
    stale = sorted(r for r in STORE_EXEMPTIONS if r in measured or r not in reads.values())
    assert not stale, f"remove {stale} from STORE_EXEMPTIONS: each is measured or gone"
