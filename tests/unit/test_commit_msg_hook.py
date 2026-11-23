from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".githooks" / "commit-msg"


def run_hook(tmp_path: Path, message: str) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text(message, encoding="utf-8")
    return subprocess.run(["sh", str(HOOK), str(path)], capture_output=True, text=True)


@pytest.mark.parametrize(
    "subject", ["M1 ticket 05: CLI ingest + status", "M4: stable install", "ticket 3: backfill"]
)
def test_a_ticket_or_milestone_prefix_is_refused(tmp_path: Path, subject: str) -> None:
    result = run_hook(tmp_path, f"{subject}\n\nbody\n")

    assert result.returncode == 1
    assert "drop the ticket or milestone prefix" in result.stderr


@pytest.mark.parametrize(
    "subject",
    ["CLI ingest + status", "Merge origin/main into ship/x", "Fix M4's fallback (#125)"],
)
def test_a_plain_subject_passes(tmp_path: Path, subject: str) -> None:
    assert run_hook(tmp_path, f"# comment\n{subject}\n").returncode == 0
