from __future__ import annotations

from dataclasses import dataclass

from computer_history.host import CheckOutcome, CheckRun, Host

CAPTURE_AGENT_GATE = ("macos-capture-agent-tests", "macos-capture-agent-e2e")
RELEASE_GATE = ("lint", "unit", "data", "poc", "secrets", *CAPTURE_AGENT_GATE)
COMMITS_SEARCHED = 20


@dataclass(frozen=True)
class GateVerdict:
    """A commit, and the outcome of each release-gate check it did not pass (None: never ran)."""

    commit: str
    failing: dict[str, CheckOutcome | None]

    @property
    def passed(self) -> bool:
        return not self.failing

    @property
    def summary(self) -> str:
        return ", ".join(
            f"{name} {'missing' if outcome is None else outcome.value}"
            for name, outcome in self.failing.items()
        )


@dataclass(frozen=True)
class GateSearch:
    """The newest main commit that passed the release gate, if any, and the newer ones skipped."""

    chosen: GateVerdict | None
    skipped: tuple[GateVerdict, ...]


def gate_verdict(
    commit: str, runs: list[CheckRun], checks: tuple[str, ...] = RELEASE_GATE
) -> GateVerdict:
    """Judge a commit's check runs: every one of the checks must have run and succeeded."""
    failing: dict[str, CheckOutcome | None] = {}
    for name in checks:
        outcomes = [run.outcome for run in runs if run.name == name]
        if not outcomes:
            failing[name] = None
            continue
        bad = [outcome for outcome in outcomes if outcome is not CheckOutcome.SUCCESS]
        if bad:
            failing[name] = bad[0]
    return GateVerdict(commit, failing)


def newest_passing(host: Host, *, limit: int = COMMITS_SEARCHED) -> GateSearch:
    """Walk main's newest commits, newest first, to the first one the release gate passes."""
    skipped: list[GateVerdict] = []
    for commit in host.main_commits(limit):
        verdict = gate_verdict(commit, host.check_runs(commit))
        if verdict.passed:
            return GateSearch(verdict, tuple(skipped))
        skipped.append(verdict)
    return GateSearch(None, tuple(skipped))


def none_passed(skipped: tuple[GateVerdict, ...]) -> str:
    """Why no commit was chosen: main is empty, or what the newest commit failed."""
    found = f"no commit among the newest {COMMITS_SEARCHED} on main passed the release gate"
    if not skipped:
        return f"{found}: main has no commits"
    return f"{found}; the newest, {skipped[0].commit}, has {skipped[0].summary}"
