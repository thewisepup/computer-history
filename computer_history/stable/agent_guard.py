from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from computer_history.host import CheckOutcome, GitState, Host, HostError
from computer_history.stable.gate import CAPTURE_AGENT_GATE, COMMITS_SEARCHED, gate_verdict
from computer_history.stable.layout import Layout
from computer_history.stable.versions import pointed, version_name

MAIN_BRANCH = "main"
UNREACHABLE_FIX = "check the network and try again, or pass --force to install unverified"


class GuardCondition(Enum):
    ON_MAIN = "on main"
    CLEAN = "clean working tree"
    AT_ORIGIN_MAIN = "HEAD is origin/main"
    AGENT_CHECKS_PASSED = "capture-agent checks passed on HEAD"
    BACKEND_CAUGHT_UP = "stable backend at HEAD or newer"


@dataclass(frozen=True)
class Unmet:
    """A guard condition that does not hold, why not, and what to do about it."""

    condition: GuardCondition
    reason: str
    fix: str


@dataclass(frozen=True)
class GuardVerdict:
    """The commit the checkout is at, and every condition its agent install does not meet."""

    head: str
    unmet: tuple[Unmet, ...]


class GuardFailed(Exception):
    """The guard could not read the checkout's git state; the message says why."""


def check_agent_install(host: Host, layout: Layout, checkout: Path) -> GuardVerdict:
    """Judge whether the capture agent in a checkout may be installed by hand, changing nothing.

    It reads git, GitHub and the stable install's current pointer, and opens no database or spool.
    """
    try:
        git = host.git_state(checkout)
    except HostError as exc:
        raise GuardFailed(str(exc)) from exc
    found = [
        *_checkout_unmet(git),
        _agent_checks_unmet(host, git.head),
        _backend_unmet(host, layout, git.head),
    ]
    return GuardVerdict(git.head, tuple(unmet for unmet in found if unmet is not None))


def _checkout_unmet(git: GitState) -> list[Unmet]:
    found: list[Unmet] = []
    if git.branch != MAIN_BRANCH:
        where = "HEAD is detached" if git.branch is None else f"the checkout is on {git.branch}"
        found.append(Unmet(GuardCondition.ON_MAIN, where, "switch: git switch main"))
    if not git.clean:
        found.append(
            Unmet(
                GuardCondition.CLEAN,
                "the working tree has uncommitted changes",
                "commit or stash them",
            )
        )
    if git.origin_main is None:
        found.append(
            Unmet(
                GuardCondition.AT_ORIGIN_MAIN,
                "the checkout has no origin/main",
                "fetch it: git fetch origin main",
            )
        )
    elif git.head != git.origin_main:
        found.append(
            Unmet(
                GuardCondition.AT_ORIGIN_MAIN,
                f"HEAD {version_name(git.head)} is not origin/main {version_name(git.origin_main)}",
                "pull, or push what main holds locally, until they match: git pull",
            )
        )
    return found


def _agent_checks_unmet(host: Host, head: str) -> Unmet | None:
    try:
        runs = host.check_runs(head)
    except HostError as exc:
        return Unmet(GuardCondition.AGENT_CHECKS_PASSED, str(exc), UNREACHABLE_FIX)
    verdict = gate_verdict(head, runs, CAPTURE_AGENT_GATE)
    if verdict.passed:
        return None
    pending = all(outcome in (None, CheckOutcome.RUNNING) for outcome in verdict.failing.values())
    fix = "wait for CI to finish on it" if pending else "fix or re-run the failing jobs in CI"
    return Unmet(GuardCondition.AGENT_CHECKS_PASSED, verdict.summary, fix)


def _backend_unmet(host: Host, layout: Layout, head: str) -> Unmet | None:
    current = pointed(layout.current)
    if current is None:
        return Unmet(
            GuardCondition.BACKEND_CAUGHT_UP,
            "there is no stable install",
            "set it up first: computer-history install",
        )
    try:
        commits = host.main_commits(COMMITS_SEARCHED)
    except HostError as exc:
        return Unmet(GuardCondition.BACKEND_CAUGHT_UP, str(exc), UNREACHABLE_FIX)
    if head not in commits:
        return Unmet(
            GuardCondition.BACKEND_CAUGHT_UP,
            f"HEAD {version_name(head)} is not among main's newest {COMMITS_SEARCHED} commits,"
            f" so it can't be compared with the stable backend's version {current.name}",
            "pull main: git pull",
        )
    at_or_after_head = commits[: commits.index(head) + 1]
    if current.name in (version_name(commit) for commit in at_or_after_head):
        return None
    return Unmet(
        GuardCondition.BACKEND_CAUGHT_UP,
        f"the stable backend is version {current.name}, older than HEAD {version_name(head)}",
        "move it forward first: computer-history update",
    )
