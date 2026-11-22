from __future__ import annotations

import os
import plistlib
from pathlib import Path

import pytest
from cli_output import RunCli
from fake_host import FakeHost, gate_runs, installed_package, write_stopgap_plist

from computer_history.cli.profile import NOT_A_CHECKOUT
from computer_history.host import CheckOutcome, JobState
from computer_history.stable import (
    BACKEND,
    LOAD_ATTEMPTS,
    STABLE_AGENTS,
    STOPGAP_LABEL,
    Layout,
    Schedule,
    stable_layout,
    version_name,
)
from computer_history.store import DATABASE_NAME, INSTALL_MARKER_NAME

NEWEST = "c" * 40
OLDER = "b" * 40


@pytest.fixture
def layout(live: Path) -> Layout:
    found = stable_layout()
    (live / DATABASE_NAME).write_text("real history\n")
    (live / "spool").mkdir()
    (live / "spool" / "1.jsonl").write_text("{}\n")
    (live / "screenshots").mkdir()
    (live / "agent-config.json").write_text("{}\n")
    return found


def data_files(layout: Layout) -> dict[Path, bytes]:
    return {
        path: path.read_bytes()
        for path in layout.live.rglob("*")
        if path.is_file() and layout.versions not in path.parents
    }


def test_install_builds_the_newest_passing_commit_and_starts_the_backend_from_it(
    run: RunCli, layout: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={OLDER: gate_runs()}, loaded=[STOPGAP_LABEL])
    stopgap = write_stopgap_plist(layout)
    data = data_files(layout)

    code, out, err = run(checkout, "install", host=host)

    assert code == 0, err
    assert out[0] == f"Profile dev ({NOT_A_CHECKOUT}), stable install {layout.live}"
    version = layout.versions / version_name(OLDER)
    assert (version / INSTALL_MARKER_NAME).read_text() == ""
    assert OLDER in (version / "packages.txt").read_text()
    assert layout.current.resolve() == version
    assert layout.link.resolve() == layout.command(version)
    plist = plistlib.loads((layout.launch_agents / f"{BACKEND.label}.plist").read_bytes())
    assert plist["ProgramArguments"] == [
        str(layout.command(layout.current)),
        "ingest",
        "--watch",
    ]
    assert plist["KeepAlive"] is True
    assert plist["RunAtLoad"] is True
    assert plist["ThrottleInterval"] > 0
    assert host.jobs[BACKEND.label].pid is not None
    assert STOPGAP_LABEL not in host.jobs
    assert not stopgap.exists()
    assert host.calls.index(("unload", STOPGAP_LABEL)) < host.calls.index(("load", BACKEND.label))
    assert data_files(layout) == data
    assert f"Installed version {version_name(OLDER)} (commit {OLDER})" in out


def test_the_installed_command_runs_as_stable_on_the_live_database(
    run: RunCli, layout: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={OLDER: gate_runs()})
    assert run(checkout, "install", host=host)[0] == 0
    installed = installed_package(layout.link.resolve().parents[1])

    _, out, _ = run(installed, "status", "--aw-url", "http://127.0.0.1:1/api/0", host=host)

    assert out[0] == (
        f"Profile stable (version {version_name(OLDER)}), database {layout.live / DATABASE_NAME}"
    )


@pytest.mark.parametrize(
    "newest",
    [
        {"unit": CheckOutcome.FAILURE},
        {"lint": None},
        {"macos-capture-agent-e2e": CheckOutcome.RUNNING},
        {"secrets": CheckOutcome.CANCELLED},
    ],
    ids=["failed", "missing", "running", "cancelled"],
)
def test_install_skips_commits_the_release_gate_does_not_pass(
    run: RunCli,
    layout: Layout,
    checkout: Path,
    newest: dict[str, CheckOutcome | None],
) -> None:
    host = FakeHost(checks={NEWEST: gate_runs(**newest), OLDER: gate_runs()})

    code, out, err = run(checkout, "install", host=host)

    assert code == 0, err
    assert layout.current.resolve().name == version_name(OLDER)
    ((check, outcome),) = newest.items()
    reason = "missing" if outcome is None else outcome.value
    assert f"  skipped {version_name(NEWEST)}: {check} {reason}" in out


def test_install_ignores_the_checks_outside_the_release_gate(
    run: RunCli, layout: Layout, checkout: Path
) -> None:
    runs = gate_runs(typecheck=CheckOutcome.FAILURE, perf=CheckOutcome.RUNNING)
    host = FakeHost(checks={NEWEST: runs, OLDER: gate_runs()})

    assert run(checkout, "install", host=host)[0] == 0

    assert layout.current.resolve().name == version_name(NEWEST)


def test_install_with_no_passing_commit_changes_nothing(
    run: RunCli, layout: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={NEWEST: gate_runs(unit=CheckOutcome.FAILURE)})
    before = sorted(layout.live.parent.parent.parent.rglob("*"))

    code, _, err = run(checkout, "install", host=host)

    assert code == 1
    assert "no commit among the newest" in err
    assert sorted(layout.live.parent.parent.parent.rglob("*")) == before
    assert not any(call[0] in ("load", "unload", "build") for call in host.calls)


@pytest.mark.parametrize(
    "host",
    [
        FakeHost(offline=True),
        FakeHost(checks={OLDER: gate_runs()}, build_error="uv is not installed"),
        FakeHost(checks={OLDER: gate_runs()}, build_blocks_packages=True),
    ],
    ids=["offline", "uv missing", "package list not written"],
)
def test_install_fails_cleanly_changing_nothing(
    run: RunCli, home: Path, layout: Layout, checkout: Path, host: FakeHost
) -> None:
    before = sorted(home.rglob("*"))

    code, _, err = run(checkout, "install", host=host)

    assert code == 1
    assert err.startswith("install failed: ")
    assert "nothing was changed" in err
    assert sorted(home.rglob("*")) == before
    assert not any(call[0] in ("load", "unload") for call in host.calls)


def test_install_twice_repairs_without_rebuilding_or_reaching_github(
    run: RunCli, layout: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={OLDER: gate_runs()})
    assert run(checkout, "install", host=host)[0] == 0
    layout.link.unlink()
    host.checks = {NEWEST: gate_runs(), **host.checks}
    host.calls.clear()

    code, out, err = run(checkout, "install", host=host)

    assert code == 0, err
    assert layout.current.resolve().name == version_name(OLDER)
    assert layout.link.resolve() == layout.command(layout.current.resolve())
    rerun = [agent for agent in STABLE_AGENTS if agent.schedule is not Schedule.AT_LOAD]
    assert [call for call in host.calls if call[0] != "job"] == [
        (step, agent.label) for agent in rerun for step in ("unload", "load")
    ]
    assert host.jobs[BACKEND.label].pid is not None
    assert [path.name for path in layout.versions.iterdir()] == [version_name(OLDER)]
    assert f"Version {version_name(OLDER)} is already installed and current" in out


def test_install_refuses_to_replace_a_command_it_did_not_link(
    run: RunCli, home: Path, layout: Layout, checkout: Path
) -> None:
    layout.link.parent.mkdir(parents=True)
    layout.link.write_text("#!/bin/sh\n")
    before = sorted(home.rglob("*"))
    host = FakeHost(checks={OLDER: gate_runs()})

    code, _, err = run(checkout, "install", host=host)

    assert code == 1
    assert f"{layout.link} already exists and is not the stable install's link" in err
    assert sorted(home.rglob("*")) == before
    assert host.calls == []


def test_uninstall_removes_the_install_and_keeps_the_data(
    run: RunCli, home: Path, layout: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={OLDER: gate_runs()})
    data = data_files(layout)
    assert run(checkout, "install", host=host)[0] == 0

    code, out, err = run(checkout, "uninstall", host=host)

    assert code == 0, err
    assert out[0] == f"Profile dev ({NOT_A_CHECKOUT}), stable install {layout.live}"
    assert host.jobs == {}
    assert not (layout.launch_agents / f"{BACKEND.label}.plist").exists()
    assert not layout.versions.exists()
    assert not layout.current.is_symlink()
    assert not layout.link.is_symlink()
    assert data_files(layout) == data
    assert run(checkout, "uninstall", host=host)[0] == 0


def test_uninstall_leaves_a_command_it_did_not_link(
    run: RunCli, tmp_path: Path, layout: Layout, checkout: Path
) -> None:
    other = tmp_path / "other-computer-history"
    other.write_text("#!/bin/sh\n")
    layout.link.parent.mkdir(parents=True)
    layout.link.symlink_to(other)

    assert run(checkout, "uninstall", host=FakeHost())[0] == 0

    assert layout.link.resolve() == other


def test_install_with_a_read_only_live_folder_changes_nothing(
    run: RunCli, home: Path, layout: Layout, checkout: Path
) -> None:
    before = sorted(home.rglob("*"))
    layout.live.chmod(0o555)
    try:
        code, _, err = run(checkout, "install", host=FakeHost(checks={OLDER: gate_runs()}))
    finally:
        layout.live.chmod(0o755)

    assert code == 1
    assert err.startswith("install failed: ") and "(nothing was changed)" in err
    assert sorted(home.rglob("*")) == before


def test_reinstalling_waits_for_the_running_backend_to_unload_before_loading_it_again(
    run: RunCli, layout: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={OLDER: gate_runs()})
    assert run(checkout, "install", host=host)[0] == 0
    host.unload_lingers, host.busy_loads = 3, LOAD_ATTEMPTS - 1
    host.calls.clear()

    code, _, err = run(checkout, "install", host=host)

    assert code == 0, err
    assert host.jobs[BACKEND.label].pid is not None
    backend = [call[0] for call in host.calls if call[1] == BACKEND.label]
    assert backend == ["job", "unload", "job", "job", "job", "job", *["load"] * LOAD_ATTEMPTS]


def test_install_boots_out_a_stopgap_whose_plist_was_deleted(
    run: RunCli, layout: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={OLDER: gate_runs()}, loaded=[STOPGAP_LABEL])

    code, out, err = run(checkout, "install", host=host)

    assert code == 0, err
    assert STOPGAP_LABEL not in host.jobs
    assert f"  stopgap       {STOPGAP_LABEL} booted out and removed" in out


def test_install_waits_for_the_stopgap_to_unload_before_starting_its_own_backend(
    run: RunCli, layout: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={OLDER: gate_runs()}, loaded=[STOPGAP_LABEL], unload_lingers=3)

    code, _, err = run(checkout, "install", host=host)

    assert code == 0, err
    stopgap_gone = host.calls.index(("unload", STOPGAP_LABEL)) + 4
    assert host.calls[stopgap_gone] == ("job", STOPGAP_LABEL)
    assert stopgap_gone < host.calls.index(("load", BACKEND.label))


class VersionsWhileLoaded(FakeHost):
    """A host that notes, at each lookup that finds the backend still loaded, whether its
    versions folder is still there."""

    def __init__(self, layout: Layout, **options: object) -> None:
        super().__init__(**options)  # type: ignore[arg-type]
        self.layout = layout
        self.versions_kept: list[bool] = []

    def job(self, label: str) -> JobState:
        state = super().job(label)
        if label == BACKEND.label and state.loaded:
            self.versions_kept.append(self.layout.versions.exists())
        return state


def test_uninstall_waits_for_the_backend_to_unload_before_removing_its_version(
    run: RunCli, layout: Layout, checkout: Path
) -> None:
    host = VersionsWhileLoaded(layout, checks={OLDER: gate_runs()})
    assert run(checkout, "install", host=host)[0] == 0
    host.unload_lingers = 3
    host.versions_kept.clear()

    code, _, err = run(checkout, "uninstall", host=host)

    assert code == 0, err
    assert host.versions_kept == [True] * 4
    assert not layout.versions.exists()


@pytest.mark.parametrize("spelling", ["~/.local/bin/", "{home}/.local/bin/", "{alias}/.local/bin"])
def test_install_finds_its_link_on_path_however_path_spells_the_folder(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    home: Path,
    layout: Layout,
    checkout: Path,
    spelling: str,
) -> None:
    alias = tmp_path / "home-alias"
    alias.symlink_to(home)
    entry = spelling.format(home=home, alias=alias)
    monkeypatch.setenv("PATH", os.pathsep.join(["/usr/bin", entry]))

    code, out, _ = run(checkout, "install", host=FakeHost(checks={OLDER: gate_runs()}))

    assert code == 0
    assert not any("is not on PATH" in line for line in out)


def test_install_notes_when_its_link_is_not_on_path(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    layout: Layout,
    checkout: Path,
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")

    _, out, _ = run(checkout, "install", host=FakeHost(checks={OLDER: gate_runs()}))

    assert out[-1] == f"  note: {layout.link.parent} is not on PATH; add it to run computer-history"
