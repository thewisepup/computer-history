from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from computer_history.cli.formatting import plural
from computer_history.stable import (
    GuardFailed,
    Unmet,
    check_agent_install,
    stable_layout,
    version_name,
)

log = logging.getLogger(__name__)


def cmd_check_agent_install(args: argparse.Namespace) -> int:
    try:
        verdict = check_agent_install(args.host, stable_layout(), _checkout(args.code))
    except GuardFailed as exc:
        log.info("agent install not checked", extra={"error": str(exc), "forced": args.force})
        if args.force:
            print(f"Agent install allowed by --force: the guard could not run ({exc})")
            return 0
        print(f"Agent install refused: the guard could not run ({exc})", file=sys.stderr)
        return 1
    log.info(
        "agent install checked",
        extra={
            "commit": verdict.head,
            "unmet": [unmet.condition.name for unmet in verdict.unmet],
            "forced": args.force,
        },
    )
    head = version_name(verdict.head)
    if not verdict.unmet:
        print(f"Agent install allowed: every condition holds for HEAD {head}")
        return 0
    count = f"{len(verdict.unmet)} unmet {plural('condition', len(verdict.unmet))}"
    if args.force:
        print(f"Agent install allowed by --force, skipping {count} for HEAD {head}:")
        for unmet in verdict.unmet:
            print(_line(unmet))
        return 0
    print(
        f"Agent install refused: {count} for HEAD {head} (pass --force to install anyway)",
        file=sys.stderr,
    )
    for unmet in verdict.unmet:
        print(_line(unmet), file=sys.stderr)
    return 1


def _checkout(code: Path) -> Path:
    return code.parent


def _line(unmet: Unmet) -> str:
    return f"  {unmet.condition.value}: {unmet.reason}; {unmet.fix}"
