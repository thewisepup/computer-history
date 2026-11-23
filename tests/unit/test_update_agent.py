"""How update readies the capture agent: built when its source changed, copied when not."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cli_output import RunCli
from fake_host import agent_built_from, completes_a_cycle, lay_out_agent
from stable_updates import (
    NEWER,
    OLDER,
    OLDEST,
    health,
    install_older,
    install_state,
    stable_code,
    updating,
)

from computer_history.host import SpoolReads
from computer_history.sources.capture_spool import RECORD_KINDS, SPOOL_VERSION
from computer_history.stable import (
    BACKEND,
    BACKUPS_FOLDER_NAME,
    PRE_UPDATE_FOLDER_NAME,
    Layout,
    record_installed_agent,
    version_name,
)
from computer_history.stable.updates import waiting


@pytest.fixture(autouse=True)
def quick_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(waiting, "FIRST_CYCLE_POLL_SECONDS", 0.001)


@pytest.fixture
def layout(run: RunCli, live: Path, checkout: Path) -> Layout:
    return install_older(run, live, checkout)


def new_version(layout: Layout) -> Path:
    return layout.versions / version_name(NEWER)


def old_version(layout: Layout) -> Path:
    return layout.versions / version_name(OLDER)


def agent_installed(layout: Layout, built_from: str, *, in_old_version: bool = True) -> None:
    """The app built from a commit at the fixed path, recorded, and carried by the old version."""
    lay_out_agent(layout.capture_agent_app, built_from)
    record_installed_agent(layout, built_from, datetime(2026, 11, 20, tzinfo=UTC))
    if in_old_version:
        lay_out_agent(layout.agent_app(old_version(layout)), built_from)
        layout.agent_commit(old_version(layout)).write_text(f"{built_from}\n")


def tree(path: Path) -> dict[Path, bytes]:
    return {p.relative_to(path): p.read_bytes() for p in sorted(path.rglob("*")) if p.is_file()}


def test_an_unknown_installed_agent_counts_as_changed_and_is_built_into_the_new_version(
    run: RunCli, layout: Layout
) -> None:
    host = updating(layout, completes_a_cycle(health(layout)))

    code, _, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_built_from(layout.agent_app(new_version(layout))) == NEWER
    assert layout.agent_commit(new_version(layout)).read_text() == f"{NEWER}\n"
    toolchain = host.calls.index(("check_agent_toolchain", ""))
    assert toolchain < host.calls.index(("build", NEWER))
    assert host.calls.index(("build_agent", NEWER)) < host.calls.index(("unload", BACKEND.label))
    assert not any(call == "agent_tree" for call, _ in host.calls)
    assert agent_built_from(layout.capture_agent_app) == NEWER


@pytest.mark.parametrize("in_old_version", [True, False], ids=["old version", "installed app"])
def test_an_unchanged_agent_source_copies_the_installed_agents_app_and_leaves_it_alone(
    run: RunCli, layout: Layout, in_old_version: bool
) -> None:
    agent_installed(layout, OLDEST, in_old_version=in_old_version)
    installed = tree(layout.capture_agent_app)
    record = layout.installed_agent.read_bytes()
    host = updating(layout, completes_a_cycle(health(layout)))

    code, _, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_built_from(layout.agent_app(new_version(layout))) == OLDEST
    assert layout.agent_commit(new_version(layout)).read_text() == f"{OLDEST}\n"
    assert tree(layout.capture_agent_app) == installed
    assert layout.installed_agent.read_bytes() == record
    assert ("agent_tree", NEWER) in host.calls
    assert ("agent_tree", OLDEST) in host.calls
    assert not any(
        call in ("check_agent_toolchain", "build_agent", "install_agent") for call, _ in host.calls
    )


def test_a_changed_agent_source_is_built_from_the_new_commit(run: RunCli, layout: Layout) -> None:
    agent_installed(layout, OLDER)
    host = updating(layout, completes_a_cycle(health(layout)), agent_trees={NEWER: "f" * 40})

    code, _, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert agent_built_from(layout.agent_app(new_version(layout))) == NEWER
    assert layout.agent_commit(new_version(layout)).read_text() == f"{NEWER}\n"
    assert agent_built_from(layout.agent_app(old_version(layout))) == OLDER
    assert agent_built_from(layout.capture_agent_app) == NEWER


@pytest.mark.parametrize(
    ("installed", "host_options", "error"),
    [
        (
            None,
            {"agent_toolchain_missing": "Swift is not installed (run xcode-select --install)"},
            "cannot build the capture agent: Swift is not installed (run xcode-select --install)",
        ),
        (
            None,
            {
                "agent_toolchain_missing": 'the signing identity "Computer History Code Signing"'
                " is not in the keychain"
            },
            'cannot build the capture agent: the signing identity "Computer History Code Signing"'
            " is not in the keychain",
        ),
        (
            OLDER,
            {"agent_tree_error": "could not read the source tree of cccc from GitHub: offline"},
            "could not tell whether the capture agent changed: could not read the source tree of"
            " cccc from GitHub: offline",
        ),
        (
            None,
            {"agent_build_error": "could not build the agent: error: no such module 'Testing'"},
            f"could not build the capture agent for version {version_name(NEWER)}: could not"
            " build the agent: error: no such module 'Testing'",
        ),
    ],
    ids=["no swift", "no identity", "tree unreadable", "build fails"],
)
def test_an_agent_that_cannot_be_built_stops_the_update_before_anything_changes(
    run: RunCli,
    layout: Layout,
    installed: str | None,
    host_options: dict[str, object],
    error: str,
) -> None:
    if installed is not None:
        agent_installed(layout, installed)
    host = updating(layout, **host_options)
    before = install_state(layout)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 1
    assert out[1:] == []
    assert err == f"update failed: {error} (nothing was changed)\n"
    assert install_state(layout) == before
    assert host.jobs[BACKEND.label].loaded
    assert not any(call in ("unload", "load") for call, _ in host.calls)


def test_the_toolchain_is_checked_before_the_backend_is_built(run: RunCli, layout: Layout) -> None:
    host = updating(layout, agent_toolchain_missing="Swift is not installed")

    assert run(stable_code(layout), "update", host=host)[0] == 1

    assert not any(call == "build" for call, _ in host.calls)


def test_an_interrupt_during_the_agent_build_removes_the_new_version_and_changes_nothing(
    run: RunCli, layout: Layout
) -> None:
    host = updating(layout, agent_build_interrupted=True)
    before = install_state(layout)

    code, out, err = run(stable_code(layout), "update", host=host)

    assert code == 130
    assert out[1:] == []
    assert err == "update interrupted before switching versions (nothing was changed)\n"
    assert install_state(layout) == before
    assert host.jobs[BACKEND.label].loaded
    assert not any(call in ("unload", "load") for call, _ in host.calls)


def test_every_new_version_notes_what_its_built_backend_reads(run: RunCli, layout: Layout) -> None:
    reads = SpoolReads(SPOOL_VERSION + 1, ("capture", "heartbeat"))
    host = updating(layout, completes_a_cycle(health(layout)), spool_reads={NEWER: reads})

    code, _, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert json.loads(layout.spool_reads(new_version(layout)).read_text()) == {
        "spool_version": SPOOL_VERSION + 1,
        "kinds": ["capture", "heartbeat"],
    }
    assert json.loads(layout.spool_reads(old_version(layout)).read_text()) == {
        "spool_version": SPOOL_VERSION,
        "kinds": list(RECORD_KINDS),
    }


def test_an_update_back_to_a_version_still_on_disk_keeps_the_app_it_carries(
    run: RunCli, layout: Layout
) -> None:
    assert (
        run(
            stable_code(layout), "update", host=updating(layout, completes_a_cycle(health(layout)))
        )[0]
        == 0
    )
    assert run(stable_code(layout), "rollback", host=updating(layout))[0] == 0
    carried = tree(layout.agent_app(new_version(layout)))
    for backup in (layout.live / BACKUPS_FOLDER_NAME / PRE_UPDATE_FOLDER_NAME).iterdir():
        backup.unlink()
    host = updating(layout, completes_a_cycle(health(layout)))

    code, _, err = run(stable_code(layout), "update", host=host)

    assert code == 0, err
    assert layout.current.resolve() == new_version(layout)
    assert tree(layout.agent_app(new_version(layout))) == carried
    assert not any(
        call in ("check_agent_toolchain", "build_agent", "build") for call, _ in host.calls
    )
