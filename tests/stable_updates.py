"""A stable install to update: the commits it moves between and the state a test compares."""

from __future__ import annotations

import json
from pathlib import Path

from cli_output import RunCli
from db_states import writer
from fake_host import BackendStart, FakeHost, gate_runs, installed_package

from computer_history.sources import health_path
from computer_history.stable import BACKEND, Layout, stable_layout
from computer_history.store import DATABASE_NAME, sidecars

OLDEST = "a" * 40
OLDER = "b" * 40
NEWER = "c" * 40
NEWEST = "d" * 40


def install_older(run: RunCli, live: Path, checkout: Path) -> Layout:
    """A stable install of OLDER over a live database holding two windows."""
    with writer(live / DATABASE_NAME, "a", "b"):
        pass
    assert run(checkout, "install", host=FakeHost(checks={OLDER: gate_runs()}))[0] == 0
    return stable_layout()


def stable_code(layout: Layout) -> Path:
    return installed_package(layout.current.resolve() / "venv")


def health(layout: Layout) -> Path:
    return health_path(layout.database)


def updating(layout: Layout, *starts: BackendStart, **options: object) -> FakeHost:
    """main with NEWER passing over the installed OLDER, the backend's starts scripted."""
    return FakeHost(
        checks={NEWER: gate_runs(), OLDER: gate_runs()},
        loaded=[BACKEND.label],
        backend_starts=starts,
        **options,  # type: ignore[arg-type]
    )


def install_state(layout: Layout) -> dict[Path, bytes | str]:
    """Every file and link of the live folder and the LaunchAgents, links by where they point.

    The live database's journal files are left out: reading the database for a backup opens them.
    """
    found: dict[Path, bytes | str] = {}
    journals = set(sidecars(layout.database))
    for folder in (layout.live, layout.launch_agents):
        for path in folder.rglob("*"):
            if path in journals:
                continue
            if path.is_symlink():
                found[path] = str(path.readlink())
            elif path.is_file():
                found[path] = path.read_bytes()
    return found


def log_lines(layout: Layout) -> list[dict[str, object]]:
    return [json.loads(line) for line in layout.update_log.read_text().splitlines()]


def changes(host: FakeHost) -> list[tuple[str, str]]:
    return [(call, label) for call, label in host.calls if call in ("build", "load", "unload")]
