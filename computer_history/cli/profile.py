from __future__ import annotations

import os
import subprocess
from pathlib import Path

from computer_history.store import Profile, stable_version

GIT_TIMEOUT_SECONDS = 5
SHORT_COMMIT_LENGTH = 7
BRANCH_REF_PREFIX = "refs/heads/"
NOT_A_CHECKOUT = "not a git checkout"


def profile_line(code: Path, profile: Profile, db_path: Path | None) -> str:
    """The first line of every command: the profile, its version or checkout, and the database."""
    if profile is Profile.STABLE:
        running = f"version {stable_version(code)}"
    else:
        running = _checkout(code)
    database = "refused" if db_path is None else str(db_path)
    return f"Profile {profile.value} ({running}), database {database}"


def _checkout(code: Path) -> str:
    try:
        run = subprocess.run(
            ["git", "-C", str(code), "rev-parse", "HEAD", "--symbolic-full-name", "HEAD"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
            env={name: value for name, value in os.environ.items() if not name.startswith("GIT_")},
        )
    except (OSError, subprocess.TimeoutExpired):
        return NOT_A_CHECKOUT
    lines = run.stdout.split()
    if run.returncode != 0 or len(lines) != 2:
        return NOT_A_CHECKOUT
    commit, ref = lines[0][:SHORT_COMMIT_LENGTH], lines[1]
    if not ref.startswith(BRANCH_REF_PREFIX):
        return f"detached at {commit}"
    return f"branch {ref.removeprefix(BRANCH_REF_PREFIX)} at {commit}"
