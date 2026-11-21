from __future__ import annotations

import plistlib
from pathlib import Path

import pytest
from fake_host import FakeHost, gate_runs, installed_package

from computer_history import cli
from computer_history.cli.profile import NOT_A_CHECKOUT
from computer_history.host import CheckOutcome
from computer_history.stable import (
    BACKEND,
    STOPGAP_LABEL,
    Layout,
    stable_layout,
)
from computer_history.store import DATABASE_NAME, INSTALL_MARKER_NAME, SHORT_COMMIT_LENGTH

NEWEST = "c" * 40
OLDER = "b" * 40
OLDEST = "a" * 40


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    monkeypatch.setenv("HOME", str(folder))
    return folder


@pytest.fixture
def layout(home: Path) -> Layout:
    found = stable_layout()
    found.live.mkdir(parents=True)
    (found.live / DATABASE_NAME).write_text("real history\n")
    (found.live / "spool").mkdir()
    (found.live / "spool" / "1.jsonl").write_text("{}\n")
    (found.live / "screenshots").mkdir()
    (found.live / "agent-config.json").write_text("{}\n")
    return found


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    code = tmp_path / "checkout" / "computer_history"
    code.mkdir(parents=True)
    return code


def run(
    capsys: pytest.CaptureFixture[str], code: Path, host: FakeHost, *argv: str
) -> tuple[int, list[str], str]:
    exit_code = cli.main(list(argv), code=code, host=host)
    captured = capsys.readouterr()
    return exit_code, captured.out.splitlines(), captured.err


def short(commit: str) -> str:
    return commit[:SHORT_COMMIT_LENGTH]


def data_files(layout: Layout) -> dict[Path, bytes]:
    return {
        path: path.read_bytes()
        for path in layout.live.rglob("*")
        if path.is_file() and layout.versions not in path.parents
    }


def stopgap_plist(layout: Layout) -> Path:
    plist = layout.launch_agents / f"{STOPGAP_LABEL}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(plistlib.dumps({"Label": STOPGAP_LABEL}))
    return plist


def test_install_builds_the_newest_passing_commit_and_starts_the_backend_from_it(
    capsys: pytest.CaptureFixture[str], layout: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={OLDER: gate_runs()}, loaded=[STOPGAP_LABEL])
    stopgap = stopgap_plist(layout)
    data = data_files(layout)

    code, out, err = run(capsys, checkout, host, "install")

    assert code == 0, err
    assert out[0] == f"Profile dev ({NOT_A_CHECKOUT}), stable install {layout.live}"
    version = layout.versions / short(OLDER)
    assert (version / INSTALL_MARKER_NAME).read_text() == ""
    assert OLDER in (version / "packages.txt").read_text()
    assert layout.current.resolve() == version
    assert layout.link.resolve() == version / "venv" / "bin" / "computer-history"
    plist = plistlib.loads((layout.launch_agents / f"{BACKEND.label}.plist").read_bytes())
    assert plist["ProgramArguments"] == [
        str(layout.current / "venv" / "bin" / "computer-history"),
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
    assert f"Installed version {short(OLDER)} (commit {OLDER})" in out


def test_the_installed_command_runs_as_stable_on_the_live_database(
    capsys: pytest.CaptureFixture[str], layout: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={OLDER: gate_runs()})
    assert run(capsys, checkout, host, "install")[0] == 0
    installed = installed_package(layout.link.resolve().parents[1])

    _, out, _ = run(capsys, installed, host, "status", "--aw-url", "http://127.0.0.1:1/api/0")

    assert out[0] == (
        f"Profile stable (version {short(OLDER)}), database {layout.live / DATABASE_NAME}"
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
    capsys: pytest.CaptureFixture[str],
    layout: Layout,
    checkout: Path,
    newest: dict[str, CheckOutcome | None],
) -> None:
    host = FakeHost(checks={NEWEST: gate_runs(**newest), OLDER: gate_runs()})

    code, out, err = run(capsys, checkout, host, "install")

    assert code == 0, err
    assert layout.current.resolve().name == short(OLDER)
    ((check, outcome),) = newest.items()
    reason = "missing" if outcome is None else outcome.value
    assert f"  skipped {short(NEWEST)}: {check} {reason}" in out


def test_install_ignores_the_checks_outside_the_release_gate(
    capsys: pytest.CaptureFixture[str], layout: Layout, checkout: Path
) -> None:
    runs = gate_runs(typecheck=CheckOutcome.FAILURE, perf=CheckOutcome.RUNNING)
    host = FakeHost(checks={NEWEST: runs, OLDER: gate_runs()})

    assert run(capsys, checkout, host, "install")[0] == 0

    assert layout.current.resolve().name == short(NEWEST)


def test_install_with_no_passing_commit_changes_nothing(
    capsys: pytest.CaptureFixture[str], layout: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={NEWEST: gate_runs(unit=CheckOutcome.FAILURE)})
    before = sorted(layout.live.parent.parent.parent.rglob("*"))

    code, _, err = run(capsys, checkout, host, "install")

    assert code == 1
    assert "no commit among the newest" in err
    assert sorted(layout.live.parent.parent.parent.rglob("*")) == before
    assert not any(call[0] in ("load", "unload", "build") for call in host.calls)


@pytest.mark.parametrize(
    "host",
    [
        FakeHost(offline=True),
        FakeHost(checks={OLDER: gate_runs()}, build_error="uv is not installed"),
    ],
    ids=["offline", "uv missing"],
)
def test_install_fails_cleanly_changing_nothing(
    capsys: pytest.CaptureFixture[str], home: Path, layout: Layout, checkout: Path, host: FakeHost
) -> None:
    before = sorted(home.rglob("*"))

    code, _, err = run(capsys, checkout, host, "install")

    assert code == 1
    assert err.startswith("install failed: ")
    assert "nothing was changed" in err
    assert sorted(home.rglob("*")) == before
    assert not any(call[0] in ("load", "unload") for call in host.calls)


def test_install_twice_repairs_without_rebuilding_or_reaching_github(
    capsys: pytest.CaptureFixture[str], layout: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={OLDER: gate_runs()})
    assert run(capsys, checkout, host, "install")[0] == 0
    layout.link.unlink()
    host.checks = {NEWEST: gate_runs(), **host.checks}
    host.calls.clear()

    code, out, err = run(capsys, checkout, host, "install")

    assert code == 0, err
    assert layout.current.resolve().name == short(OLDER)
    assert layout.link.resolve() == layout.current.resolve() / "venv" / "bin" / "computer-history"
    assert [call[0] for call in host.calls if call[0] != "job"] == ["unload", "load"]
    assert host.jobs[BACKEND.label].pid is not None
    assert [path.name for path in layout.versions.iterdir()] == [short(OLDER)]
    assert f"Version {short(OLDER)} is already installed and current" in out


def test_install_refuses_to_replace_a_command_it_did_not_link(
    capsys: pytest.CaptureFixture[str], home: Path, layout: Layout, checkout: Path
) -> None:
    layout.link.parent.mkdir(parents=True)
    layout.link.write_text("#!/bin/sh\n")
    before = sorted(home.rglob("*"))
    host = FakeHost(checks={OLDER: gate_runs()})

    code, _, err = run(capsys, checkout, host, "install")

    assert code == 1
    assert f"{layout.link} already exists and is not the stable install's link" in err
    assert sorted(home.rglob("*")) == before
    assert host.calls == []


def test_uninstall_removes_the_install_and_keeps_the_data(
    capsys: pytest.CaptureFixture[str], home: Path, layout: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={OLDER: gate_runs()})
    data = data_files(layout)
    assert run(capsys, checkout, host, "install")[0] == 0

    code, out, err = run(capsys, checkout, host, "uninstall")

    assert code == 0, err
    assert out[0] == f"Profile dev ({NOT_A_CHECKOUT}), stable install {layout.live}"
    assert host.jobs == {}
    assert not (layout.launch_agents / f"{BACKEND.label}.plist").exists()
    assert not layout.versions.exists()
    assert not layout.current.is_symlink()
    assert not layout.link.is_symlink()
    assert data_files(layout) == data
    assert run(capsys, checkout, host, "uninstall")[0] == 0


def test_uninstall_leaves_a_command_it_did_not_link(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, layout: Layout, checkout: Path
) -> None:
    other = tmp_path / "other-computer-history"
    other.write_text("#!/bin/sh\n")
    layout.link.parent.mkdir(parents=True)
    layout.link.symlink_to(other)

    assert run(capsys, checkout, FakeHost(), "uninstall")[0] == 0

    assert layout.link.resolve() == other
