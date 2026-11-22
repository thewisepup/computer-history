from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from cli_output import RunCli
from fake_host import NOT_A_CHECKOUT, OFFLINE, FakeHost, gate_runs

from computer_history.host import CheckOutcome, CheckRun, GitState
from computer_history.stable import Layout, stable_layout, version_name
from computer_history.stable.gate import COMMITS_SEARCHED

OLDER = "b" * 40
HEAD = "c" * 40
NEWER = "d" * 40
GUARD = "check-agent-install"
HEAD_NAME, NEWER_NAME, OLDER_NAME = (version_name(c) for c in (HEAD, NEWER, OLDER))


def at_head(**changes: object) -> GitState:
    """A clean checkout on main at HEAD, which is origin/main, with the changes given."""
    state = {"branch": "main", "clean": True, "head": HEAD, "origin_main": HEAD} | changes
    return GitState(**state)  # type: ignore[arg-type]


def installed_at(run: RunCli, checkout: Path, commit: str) -> Layout:
    assert run(checkout, "install", host=FakeHost(checks={commit: gate_runs()}))[0] == 0
    return stable_layout()


@pytest.fixture
def stable_at_head(run: RunCli, live: Path, checkout: Path) -> Layout:
    return installed_at(run, checkout, HEAD)


def test_the_guard_passes_when_every_condition_is_met(
    run: RunCli, stable_at_head: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={HEAD: gate_runs(), OLDER: gate_runs()}, git=at_head())

    code, out, err = run(checkout, GUARD, host=host)

    assert code == 0, err
    assert out[1:] == [f"Agent install allowed: every condition holds for HEAD {HEAD_NAME}"]
    assert ("git_state", str(checkout.parent)) in host.calls


def guard_host(git: GitState | None = None, **checks: list[CheckRun]) -> FakeHost:
    """main holding NEWER, HEAD and OLDER, newest first, each passing the gate unless given."""
    runs = {NEWER: gate_runs(), HEAD: gate_runs(), OLDER: gate_runs()}
    return FakeHost(checks=runs | {COMMITS[name]: run for name, run in checks.items()}, git=git)


COMMITS = {"NEWER": NEWER, "HEAD": HEAD, "OLDER": OLDER}


def refusal(err: str) -> tuple[str, list[str]]:
    first, *lines = err.splitlines()
    return first, lines


@pytest.mark.parametrize(
    ("git", "checks", "condition", "expected"),
    [
        (
            at_head(branch="feature"),
            {},
            "on main",
            "the checkout is on feature; switch: git switch main",
        ),
        (
            at_head(branch=None),
            {},
            "on main",
            "HEAD is detached; switch: git switch main",
        ),
        (
            at_head(clean=False),
            {},
            "clean working tree",
            "the working tree has uncommitted changes; commit or stash them",
        ),
        (
            at_head(origin_main=NEWER),
            {},
            "HEAD is origin/main",
            f"HEAD {HEAD_NAME} is not origin/main {NEWER_NAME}; pull, or push what main"
            " holds locally, until they match: git pull",
        ),
        (
            at_head(origin_main=None),
            {},
            "HEAD is origin/main",
            "the checkout has no origin/main; fetch it: git fetch origin main",
        ),
        (
            at_head(),
            {"HEAD": gate_runs(**{"macos-capture-agent-e2e": CheckOutcome.RUNNING})},
            "capture-agent checks passed on HEAD",
            "macos-capture-agent-e2e running; wait for CI to finish on it",
        ),
        (
            at_head(),
            {"HEAD": gate_runs(**{"macos-capture-agent-tests": None})},
            "capture-agent checks passed on HEAD",
            "macos-capture-agent-tests missing; a job that never ran won't appear by waiting:"
            " re-run CI on HEAD or check the job name",
        ),
        (
            at_head(),
            {"HEAD": gate_runs(**{"macos-capture-agent-tests": CheckOutcome.FAILURE})},
            "capture-agent checks passed on HEAD",
            "macos-capture-agent-tests failure; fix or re-run the failing jobs in CI",
        ),
        (
            at_head(),
            {"HEAD": gate_runs(**{"macos-capture-agent-e2e": CheckOutcome.CANCELLED})},
            "capture-agent checks passed on HEAD",
            "macos-capture-agent-e2e cancelled; fix or re-run the failing jobs in CI",
        ),
    ],
    ids=[
        "feature-branch",
        "detached",
        "dirty",
        "behind-origin",
        "no-origin-main",
        "agent-checks-running",
        "agent-checks-never-ran",
        "agent-checks-failed",
        "agent-checks-cancelled",
    ],
)
def test_each_unmet_condition_alone_refuses_and_names_itself_with_its_fix(
    run: RunCli,
    stable_at_head: Layout,
    checkout: Path,
    git: GitState,
    checks: dict[str, list[CheckRun]],
    condition: str,
    expected: str,
) -> None:
    code, out, err = run(checkout, GUARD, host=guard_host(git, **checks))

    assert code == 1
    assert out[1:] == []
    first, lines = refusal(err)
    assert first == (
        f"Agent install refused: 1 unmet condition for HEAD {HEAD_NAME}"
        " (pass --force to install anyway)"
    )
    assert lines == [f"  {condition}: {expected}"]


def test_checks_outside_the_capture_agent_jobs_do_not_refuse(
    run: RunCli, stable_at_head: Layout, checkout: Path
) -> None:
    host = guard_host(at_head(), HEAD=gate_runs(unit=CheckOutcome.FAILURE, lint=None))

    code, _, err = run(checkout, GUARD, host=host)

    assert code == 0, err


def test_a_backend_older_than_head_refuses_and_says_to_update(
    run: RunCli, live: Path, checkout: Path
) -> None:
    installed_at(run, checkout, OLDER)

    code, _, err = run(checkout, GUARD, host=guard_host(at_head()))

    assert code == 1
    assert refusal(err)[1] == [
        f"  stable backend at HEAD or newer: the stable backend is version {OLDER_NAME}, older"
        f" than HEAD {HEAD_NAME}; move it forward first: computer-history update"
    ]


def test_a_backend_newer_than_head_passes(run: RunCli, live: Path, checkout: Path) -> None:
    installed_at(run, checkout, NEWER)

    code, out, err = run(checkout, GUARD, host=guard_host(at_head()))

    assert code == 0, err
    assert out[1:] == [f"Agent install allowed: every condition holds for HEAD {HEAD_NAME}"]


def test_newer_is_judged_by_mains_order_not_by_how_the_commits_sort(
    run: RunCli, live: Path, checkout: Path
) -> None:
    sorts_first, sorts_last = "a" * 40, "f" * 40
    installed_at(run, checkout, sorts_first)
    host = FakeHost(
        checks={sorts_first: gate_runs(), sorts_last: gate_runs()},
        git=at_head(head=sorts_last, origin_main=sorts_last),
    )

    code, _, err = run(checkout, GUARD, host=host)

    assert code == 0, err


def test_a_head_missing_from_mains_newest_commits_refuses(
    run: RunCli, stable_at_head: Layout, checkout: Path
) -> None:
    stray = "e" * 40
    host = guard_host(at_head(head=stray, origin_main=stray))
    host.off_main[stray] = gate_runs()

    code, _, err = run(checkout, GUARD, host=host)

    assert code == 1
    assert refusal(err)[1] == [
        f"  stable backend at HEAD or newer: HEAD {version_name(stray)} is not among main's"
        f" newest {COMMITS_SEARCHED} commits, so it can't be compared with the stable backend's"
        f" version {HEAD_NAME};"
        " pull main: git pull"
    ]


def test_a_backend_at_head_passes_even_when_main_has_moved_far_past_it(
    run: RunCli, stable_at_head: Layout, checkout: Path
) -> None:
    host = FakeHost(checks={NEWER: gate_runs()}, git=at_head())
    host.off_main[HEAD] = gate_runs()

    code, _, err = run(checkout, GUARD, host=host)

    assert code == 0, err
    assert ("main_commits", str(COMMITS_SEARCHED)) not in host.calls


def test_no_stable_install_refuses_and_says_to_install(
    run: RunCli, live: Path, checkout: Path
) -> None:
    host = guard_host(at_head())

    code, _, err = run(checkout, GUARD, host=host)

    assert code == 1
    assert refusal(err)[1] == [
        "  stable backend at HEAD or newer: there is no stable install; set it up first:"
        " computer-history install"
    ]
    assert ("main_commits", str(COMMITS_SEARCHED)) not in host.calls


def test_every_unmet_condition_is_listed_at_once(run: RunCli, live: Path, checkout: Path) -> None:
    git = at_head(branch="feature", clean=False, origin_main=NEWER)
    host = guard_host(git, HEAD=gate_runs(**{"macos-capture-agent-e2e": CheckOutcome.FAILURE}))

    code, _, err = run(checkout, GUARD, host=host)

    assert code == 1
    first, lines = refusal(err)
    assert first.startswith(f"Agent install refused: 5 unmet conditions for HEAD {HEAD_NAME}")
    assert [line.split(":")[0].strip() for line in lines] == [
        "on main",
        "clean working tree",
        "HEAD is origin/main",
        "capture-agent checks passed on HEAD",
        "stable backend at HEAD or newer",
    ]


def test_github_out_of_reach_refuses_with_the_hosts_error(
    run: RunCli, live: Path, checkout: Path
) -> None:
    installed_at(run, checkout, OLDER)
    host = guard_host(at_head())
    host.offline = True

    code, _, err = run(checkout, GUARD, host=host)

    assert code == 1
    unreachable = "check the network and try again, or pass --force to install unverified"
    assert refusal(err)[1] == [
        f"  capture-agent checks passed on HEAD: {OFFLINE}; {unreachable}",
        f"  stable backend at HEAD or newer: {OFFLINE}; {unreachable}",
    ]


def test_force_passes_and_lists_every_condition_it_skipped(
    run: RunCli, stable_at_head: Layout, checkout: Path
) -> None:
    host = guard_host(at_head(branch="feature", clean=False))
    host.offline = True

    code, out, err = run(checkout, GUARD, "--force", host=host)

    assert code == 0, err
    assert (
        out[1]
        == f"Agent install allowed by --force, skipping 3 unmet conditions for HEAD {HEAD_NAME}:"
    )
    assert [line.split(":")[0].strip() for line in out[2:]] == [
        "on main",
        "clean working tree",
        "capture-agent checks passed on HEAD",
    ]


def test_force_with_every_condition_met_just_passes(
    run: RunCli, stable_at_head: Layout, checkout: Path
) -> None:
    code, out, _ = run(checkout, GUARD, "--force", host=guard_host(at_head()))

    assert code == 0
    assert out[1:] == [f"Agent install allowed: every condition holds for HEAD {HEAD_NAME}"]


def test_a_checkout_git_cannot_read_refuses_unless_forced(
    run: RunCli, stable_at_head: Layout, checkout: Path
) -> None:
    code, _, err = run(checkout, GUARD, host=guard_host(git=None))
    forced, out, _ = run(checkout, GUARD, "--force", host=guard_host(git=None))

    assert code == 1
    assert err.splitlines() == [
        f"Agent install refused: the guard could not run ({NOT_A_CHECKOUT})"
    ]
    assert forced == 0
    assert out[1:] == [
        f"Agent install allowed by --force: the guard could not run ({NOT_A_CHECKOUT})"
    ]


def test_the_guard_only_reads_and_opens_no_database_or_spool_from_a_dev_checkout(
    run: RunCli, stable_at_head: Layout, checkout: Path, dev: Path
) -> None:
    host = guard_host(at_head(branch="feature"))
    before = tree(stable_at_head.live.parent.parent.parent)

    code, out, _ = run(checkout, GUARD, host=host)

    assert code == 1
    assert out[0].startswith("Profile dev (")
    assert out[0].endswith(f"stable install {stable_at_head.live}")
    assert tree(stable_at_head.live.parent.parent.parent) == before
    assert not dev.exists()
    assert {call for call, _ in host.calls} == {"git_state", "check_runs"}


def tree(folder: Path) -> dict[Path, bytes | str]:
    return {
        path: str(path.readlink()) if path.is_symlink() else path.read_bytes()
        for path in folder.rglob("*")
        if path.is_symlink() or path.is_file()
    }


INSTALL_SCRIPT = Path(__file__).resolve().parents[2] / "capture-agent" / "scripts" / "install.sh"


@pytest.mark.parametrize("argv", [(), ("--force",)], ids=["plain", "forced"])
def test_the_install_script_asks_the_guard_first_and_stops_when_it_refuses(
    home: Path, tmp_path: Path, argv: tuple[str, ...]
) -> None:
    checkout = tmp_path / "repo"
    script = checkout / "capture-agent" / "scripts" / "install.sh"
    script.parent.mkdir(parents=True)
    shutil.copy(INSTALL_SCRIPT, script)
    asked = tmp_path / "guard-args"
    built = tmp_path / "built"
    fake_command(script.parent / "build.sh", f"touch {built}")
    bin_folder = checkout / ".venv" / "bin"
    fake_command(checkout / "scripts" / "venv-python", f"echo {bin_folder / 'python'}")
    fake_command(bin_folder / "computer-history", f'printf "%s\\n" "$@" > {asked}; exit 1')

    done = subprocess.run(["/bin/sh", str(script), *argv], capture_output=True, text=True)

    assert done.returncode == 1
    assert asked.read_text().splitlines() == [GUARD, *argv]
    assert not built.exists()


def fake_command(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
