from __future__ import annotations

import re
from pathlib import Path

from computer_history.stable import RELEASE_GATE

REPO = Path(__file__).resolve().parents[2]
CI = REPO / ".github" / "workflows" / "ci.yml"
CHECKS_DOC = REPO / "docs" / "agents" / "checks.md"


def test_every_release_gate_check_is_a_ci_job() -> None:
    jobs = set(re.findall(r"^  ([\w-]+):$", CI.read_text(encoding="utf-8"), re.MULTILINE))

    assert set(RELEASE_GATE) <= jobs


def test_the_checks_doc_names_the_release_gate_as_mains_required_checks() -> None:
    required = re.search(
        r"^`main` requires (.+?) to pass before a merge\.$",
        CHECKS_DOC.read_text(encoding="utf-8"),
        re.MULTILINE,
    )

    assert required, "docs/agents/checks.md no longer says which checks main requires"
    assert re.findall(r"`([\w-]+)`", required.group(1)) == list(RELEASE_GATE)
