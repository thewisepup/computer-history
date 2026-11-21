from __future__ import annotations

from pathlib import Path

from computer_history.store import Profile, RunningCode

SHORT_COMMIT_LENGTH = 7
BRANCH_REF_PREFIX = "refs/heads/"
GITDIR_PREFIX = "gitdir:"
SYMBOLIC_REF_PREFIX = "ref:"
INSTALLED_FOLDER_NAMES = frozenset({"site-packages", "dist-packages"})
NOT_A_CHECKOUT = "not a git checkout"
INSTALLED_COPY = "an installed copy, not a checkout"


def profile_line(running: RunningCode, code: Path, uses: str | None) -> str:
    """The first line of every command: the profile, its version or checkout, and what it uses."""
    if running.profile is Profile.STABLE:
        source = f"version {running.version}"
    else:
        source = checkout(code)
    line = f"Profile {running.profile.value} ({source})"
    return line if uses is None else f"{line}, {uses}"


def checkout(code: Path) -> str:
    """The branch and commit of the git checkout holding the code, read from its git folder."""
    resolved = code.expanduser().resolve()
    folders = (resolved, *resolved.parents)
    if any(folder.name in INSTALLED_FOLDER_NAMES for folder in folders):
        return INSTALLED_COPY
    for folder in folders:
        dot_git = folder / ".git"
        if dot_git.exists():
            try:
                return _describe(_git_folder(dot_git))
            except (OSError, ValueError):
                return NOT_A_CHECKOUT
    return NOT_A_CHECKOUT


def _git_folder(dot_git: Path) -> Path:
    if dot_git.is_dir():
        return dot_git
    pointer = dot_git.read_text().strip()
    if not pointer.startswith(GITDIR_PREFIX):
        raise ValueError(f"{dot_git} does not point at a git folder")
    return (dot_git.parent / pointer.removeprefix(GITDIR_PREFIX).strip()).resolve()


def _describe(git_folder: Path) -> str:
    head = (git_folder / "HEAD").read_text().strip()
    if not head.startswith(SYMBOLIC_REF_PREFIX):
        return f"detached at {head[:SHORT_COMMIT_LENGTH]}"
    ref = head.removeprefix(SYMBOLIC_REF_PREFIX).strip()
    branch = ref.removeprefix(BRANCH_REF_PREFIX)
    commit = _commit(git_folder, ref)
    if commit is None:
        return f"branch {branch}, no commits yet"
    return f"branch {branch} at {commit[:SHORT_COMMIT_LENGTH]}"


def _commit(git_folder: Path, ref: str) -> str | None:
    common = git_folder
    if (git_folder / "commondir").is_file():
        common = (git_folder / (git_folder / "commondir").read_text().strip()).resolve()
    for folder in (git_folder, common):
        if (folder / ref).is_file():
            return (folder / ref).read_text().strip()
    packed = common / "packed-refs"
    if not packed.is_file():
        return None
    for line in packed.read_text().splitlines():
        commit, _, name = line.partition(" ")
        if name == ref:
            return commit
    return None
