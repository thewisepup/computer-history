"""scripts/ci-changes: which CI jobs a pull request's changed files reach."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ci-changes"
NOT_REPO_DOCS = {
    "README.md": "test_live_host's fake GitHub listing and test_synthetic_cache's temp tree",
    "posts/sqlite-wal.md": "a file name in the developer persona's invented timeline",
}


def reaches(*paths: str) -> dict[str, bool]:
    out = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input="\n".join(paths),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {job: run == "true" for job, run in (line.split("=") for line in out.split())}


@pytest.mark.parametrize(
    ("paths", "python", "e2e", "agent"),
    [
        (("GLOSSARY.md", "docs/milestones.md", ".claude/x/SKILL.md"), False, False, False),
        (("docs/DESIGN.md",), True, False, False),
        (("computer_history/stable/install.py", "tests/unit/test_install.py"), True, False, False),
        (("computer_history/cli/update.py", "README.md"), True, False, False),
        (("computer_history/cli/status.py",), True, True, False),
        (("computer_history/sources/capture_spool/adapter.py",), True, True, False),
        (("tests/data/test_synthetic_spool.py",), True, True, False),
        (("capture-agent/Sources/CaptureAgent/SpoolWriter.swift",), True, True, True),
        (("fixtures/spool/records.jsonl",), True, True, True),
        ((".github/workflows/ci.yml",), True, True, True),
        (("pyproject.toml",), True, True, False),
        (("somewhere/new.py",), True, True, False),
        ((), True, True, True),
    ],
)
def test_jobs_run_unless_every_path_is_known_not_to_reach_them(
    paths: tuple[str, ...], python: bool, e2e: bool, agent: bool
) -> None:
    assert reaches(*paths) == {"python": python, "e2e": e2e, "agent": agent}


def test_every_markdown_file_the_code_names_runs_the_python_checks() -> None:
    named = {
        node.value
        for path in [*(REPO / "computer_history").rglob("*.py"), *(REPO / "tests").rglob("*.py")]
        if path != Path(__file__).resolve()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.fullmatch(r"[\w./-]+\.md", node.value)
    }
    tracked = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()

    unchecked = [
        doc
        for name in named - NOT_REPO_DOCS.keys()
        for doc in tracked
        if doc.endswith(name) and not reaches(doc)["python"]
    ]

    assert unchecked == [], f"add these to READ_BY_TESTS in scripts/ci-changes: {unchecked}"
