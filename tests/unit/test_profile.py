from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aw_http import served_over_http
from cli_output import RunCli
from fake_aw import FakeAW

from computer_history.cli import dev as cli_dev
from computer_history.cli.profile import INSTALLED_COPY, NOT_A_CHECKOUT
from computer_history.sources import SPOOL_ENV_VAR
from computer_history.sources.capture_spool.paths import SPOOL_FOLDER_NAME
from computer_history.store import (
    DATABASE_NAME,
    DB_ENV_VAR,
    INSTALL_MARKER_NAME,
    VERSIONS_FOLDER_NAME,
    connect,
    table_counts,
)

WINDOW_BUCKET = "aw-watcher-window_test-host.local"
UNREACHABLE_AW = ("--aw-url", "http://127.0.0.1:1/api/0")
SCREENSHOTS_FOLDER = "screenshots"
DEVELOPER_DAY = ("--persona", "developer", "--scenario", "typical", "--tier", "day", "--seed", "1")


def test_a_checkout_run_is_dev_and_uses_the_dev_folder(
    run: RunCli, live: Path, dev: Path, checkout: Path
) -> None:
    code, out, _ = run(checkout, "status", *UNREACHABLE_AW)

    assert code == 0
    assert out[0] == f"Profile dev ({NOT_A_CHECKOUT}), database {dev / DATABASE_NAME}"
    assert f"Database:      {dev / DATABASE_NAME} (not created yet" in "\n".join(out)
    assert list(live.iterdir()) == []


def installed(live: Path, version: str, *, marked: bool) -> Path:
    folder = live / VERSIONS_FOLDER_NAME / version
    code = folder / "venv" / "lib" / "python3.12" / "site-packages" / "computer_history"
    code.mkdir(parents=True)
    if marked:
        (folder / INSTALL_MARKER_NAME).write_text("")
    return code


def test_a_marked_version_of_the_stable_install_is_stable_and_uses_the_live_folder(
    run: RunCli, live: Path, dev: Path
) -> None:
    code, out, _ = run(installed(live, "1a2b3c4", marked=True), "ingest", *UNREACHABLE_AW)

    assert out[0] == f"Profile stable (version 1a2b3c4), database {live / DATABASE_NAME}"
    assert code == 1
    assert (live / DATABASE_NAME).is_file()
    assert not dev.exists()


def test_a_version_without_the_marker_is_dev(
    run: RunCli, live: Path, dev: Path
) -> None:
    code, out, _ = run(installed(live, "1a2b3c4", marked=False), "status", *UNREACHABLE_AW)

    assert code == 0
    assert out[0] == f"Profile dev ({INSTALLED_COPY}), database {dev / DATABASE_NAME}"
    assert not (live / DATABASE_NAME).exists()


def spellings(live: Path, tmp_path: Path) -> dict[str, Path]:
    alias = tmp_path / "alias"
    alias.symlink_to(live)
    return {"plain": live, "symlink": alias, "case": Path(str(live).upper())}


@pytest.mark.parametrize("spelling", ["plain", "symlink", "case"])
@pytest.mark.parametrize("given", ["flag", "env"])
def test_dev_is_refused_the_live_database(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    live: Path,
    dev: Path,
    checkout: Path,
    given: str,
    spelling: str,
) -> None:
    (live / DATABASE_NAME).write_text("real history\n")
    db = spellings(live, tmp_path)[spelling] / DATABASE_NAME
    argv = ["ingest", *UNREACHABLE_AW]
    if given == "flag":
        argv += ["--db-path", str(db)]
    else:
        monkeypatch.setenv(DB_ENV_VAR, str(db))

    code, out, err = run(checkout, *argv)

    assert code == 1
    assert out == [f"Profile dev ({NOT_A_CHECKOUT}), database refused"]
    assert err.startswith(f"refused: {db} is in the live data folder {live}.")
    assert "--db-path" in err and DB_ENV_VAR in err and str(dev / DATABASE_NAME) in err
    assert sorted(path.name for path in live.iterdir()) == [DATABASE_NAME]
    assert (live / DATABASE_NAME).read_text() == "real history\n"


@pytest.mark.parametrize("spelling", ["plain", "symlink", "case"])
@pytest.mark.parametrize("given", ["flag", "env"])
@pytest.mark.parametrize("folder", [SPOOL_FOLDER_NAME, SCREENSHOTS_FOLDER])
def test_dev_is_refused_the_live_spool_and_screenshots(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    live: Path,
    dev: Path,
    checkout: Path,
    given: str,
    spelling: str,
    folder: str,
) -> None:
    (live / folder).mkdir()
    (live / folder / "20260105T090000.000000Z.jsonl").write_text("waiting\n")
    spool = spellings(live, tmp_path)[spelling] / folder
    argv = ["ingest", *UNREACHABLE_AW]
    if given == "flag":
        argv += ["--spool-path", str(spool)]
    else:
        monkeypatch.setenv(SPOOL_ENV_VAR, str(spool))

    code, out, err = run(checkout, *argv)

    assert code == 1
    assert out == [f"Profile dev ({NOT_A_CHECKOUT}), database {dev / DATABASE_NAME}"]
    assert err.startswith(f"refused: {spool} is in the live data folder {live}.")
    assert "--spool-path" in err and SPOOL_ENV_VAR in err and str(dev / SPOOL_FOLDER_NAME) in err
    assert [path.name for path in (live / folder).iterdir()] == ["20260105T090000.000000Z.jsonl"]
    assert not dev.exists()


def test_stable_is_not_walled_off_from_its_own_folder(
    run: RunCli, live: Path
) -> None:
    code = installed(live, "1a2b3c4", marked=True)

    status, _, err = run(
        code, "status", "--db-path", str(live / DATABASE_NAME), *UNREACHABLE_AW
    )

    assert status == 0
    assert "refused" not in err


def test_dev_ingests_activitywatch_into_its_own_database(
    run: RunCli, live: Path, dev: Path, checkout: Path
) -> None:
    now = datetime.now(UTC)
    aw = FakeAW({WINDOW_BUCKET: "currentwindow"}, t0=now - timedelta(minutes=60))
    aw.add(WINDOW_BUCKET, 0, 600, {"app": "Code", "title": "cli.py"})

    with served_over_http(aw) as url:
        code, out, err = run(checkout, "ingest", "--aw-url", url)

    assert code == 0, err
    assert out[0] == f"Profile dev ({NOT_A_CHECKOUT}), database {dev / DATABASE_NAME}"
    conn = connect(dev / DATABASE_NAME)
    try:
        assert table_counts(conn)["observations"] == 1
    finally:
        conn.close()
    assert list(live.iterdir()) == []


def git(repo: Path, *argv: str) -> str:
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    identity = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    done = subprocess.run(
        ["git", "-C", str(repo), *identity, *argv],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return done.stdout.strip()


def test_a_dev_run_from_a_git_checkout_names_its_branch_and_commit(
    run: RunCli, tmp_path: Path, live: Path, dev: Path
) -> None:
    repo = tmp_path / "repo"
    code = repo / "computer_history"
    code.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "feature")
    git(repo, "commit", "-q", "--allow-empty", "-m", "first")
    commit = git(repo, "rev-parse", "--short", "HEAD")
    git(repo, "checkout", "-q", "--detach")

    _, detached, _ = run(code, "status", *UNREACHABLE_AW)
    git(repo, "checkout", "-q", "feature")
    _, on_branch, _ = run(code, "status", *UNREACHABLE_AW)

    database = dev / DATABASE_NAME
    assert detached[0] == f"Profile dev (detached at {commit}), database {database}"
    assert on_branch[0] == f"Profile dev (branch feature at {commit}), database {database}"


def test_the_checkout_named_is_the_codes_own_not_one_git_points_at(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    live: Path,
    dev: Path,
    checkout: Path,
) -> None:
    repo = tmp_path / "elsewhere"
    repo.mkdir()
    git(repo, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))

    _, out, _ = run(checkout, "status", *UNREACHABLE_AW)

    assert out[0] == f"Profile dev ({NOT_A_CHECKOUT}), database {dev / DATABASE_NAME}"


def committed_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "feature")
    git(repo, "commit", "-q", "--allow-empty", "-m", "first")
    return repo, git(repo, "rev-parse", "--short", "HEAD")


def test_an_unborn_branch_is_named_with_no_commit(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    live: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "computer_history").mkdir(parents=True)
    git(repo, "init", "-q", "-b", "feature")
    monkeypatch.setattr(cli_dev, "run_gate", failing_gate)

    _, out, _ = run(repo / "computer_history", "dev", "perf")

    assert out[0] == "Profile dev (branch feature, no commits yet)"


def test_a_worktree_names_its_branch_even_once_refs_are_packed(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    live: Path,
) -> None:
    repo, commit = committed_repo(tmp_path)
    tree = tmp_path / "tree"
    git(repo, "worktree", "add", "-q", "-b", "side", str(tree))
    git(repo, "pack-refs", "--all")
    (tree / "computer_history").mkdir()
    monkeypatch.setattr(cli_dev, "run_gate", failing_gate)

    _, out, _ = run(tree / "computer_history", "dev", "perf")

    assert not (repo / ".git" / "refs" / "heads" / "side").exists()
    assert out[0] == f"Profile dev (branch side at {commit})"


def test_a_copy_installed_into_a_venv_inside_a_checkout_is_not_named_as_the_checkout(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    live: Path,
) -> None:
    repo, _ = committed_repo(tmp_path)
    code = repo / ".venv" / "lib" / "python3.12" / "site-packages" / "computer_history"
    code.mkdir(parents=True)
    monkeypatch.setattr(cli_dev, "run_gate", failing_gate)

    _, out, _ = run(code, "dev", "perf")

    assert out[0] == f"Profile dev ({INSTALLED_COPY})"


def failing_gate(*args: object, **kwargs: object) -> None:
    raise OSError("no gate in this test")


def test_dev_tools_that_open_no_database_neither_resolve_nor_name_one(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    live: Path,
    checkout: Path,
) -> None:
    monkeypatch.setenv(DB_ENV_VAR, str(live / DATABASE_NAME))
    monkeypatch.setenv(SPOOL_ENV_VAR, str(live / SPOOL_FOLDER_NAME))
    monkeypatch.setattr(cli_dev, "run_gate", failing_gate)
    out_folder = tmp_path / "out"

    perf, perf_out, perf_err = run(checkout, "dev", "perf")
    build, build_out, build_err = run(
        checkout,
        "dev",
        "build-db",
        *DEVELOPER_DAY,
        "--timezone",
        "Nowhere/Nope",
        "--out",
        str(out_folder),
    )

    assert (perf, perf_out) == (1, [f"Profile dev ({NOT_A_CHECKOUT})"])
    assert perf_err == "dev perf failed: OSError: no gate in this test\n"
    assert build == 2
    assert build_out == [f"Profile dev ({NOT_A_CHECKOUT}), output {out_folder}"]
    assert "refused" not in build_err and "invalid dataset inputs" in build_err
    assert list(live.iterdir()) == []
