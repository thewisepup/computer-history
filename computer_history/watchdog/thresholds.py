from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import cast

from computer_history.watchdog.checks import Check

WATCHDOG_KEY = "watchdog"
DEFAULT_SILENT_MINUTES = 5
MIN_SILENT_MINUTES = 1
MAX_SILENT_MINUTES = 1440
CONFIG_KEYS = {
    Check.CAPTURE_AGENT: "capture_agent_minutes",
    Check.ACTIVITYWATCH: "activitywatch_minutes",
    Check.BACKEND: "backend_minutes",
}


def _defaults() -> dict[Check, timedelta]:
    return {check: timedelta(minutes=DEFAULT_SILENT_MINUTES) for check in Check}


@dataclass(frozen=True)
class Thresholds:
    """How long each check's subject may stay silent before the watchdog calls it a problem."""

    silent_after: dict[Check, timedelta] = field(default_factory=_defaults)
    problems: tuple[str, ...] = ()


def read_thresholds(config: Path) -> Thresholds:
    """Read each threshold from the config file's watchdog object, falling back to the default."""
    silent_after = _defaults()
    try:
        whole = json.loads(config.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Thresholds(silent_after)
    except (OSError, ValueError) as exc:
        return Thresholds(silent_after, (f"cannot read {config}: {exc}, using the defaults",))
    settings = cast(dict[str, object], whole) if isinstance(whole, dict) else {}
    section = settings.get(WATCHDOG_KEY, {})
    if not isinstance(section, dict):
        return Thresholds(silent_after, (f"{WATCHDOG_KEY} must be an object, using the defaults",))
    values = cast(dict[str, object], section)
    problems = [
        f'unknown key "{WATCHDOG_KEY}.{name}" ignored'
        for name in sorted(values)
        if name not in CONFIG_KEYS.values()
    ]
    for check, key in CONFIG_KEYS.items():
        if key not in values:
            continue
        value = values[key]
        if (
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and MIN_SILENT_MINUTES <= value <= MAX_SILENT_MINUTES
        ):
            silent_after[check] = timedelta(minutes=value)
            continue
        problems.append(
            f"{WATCHDOG_KEY}.{key} must be a number of minutes from {MIN_SILENT_MINUTES} to"
            f" {MAX_SILENT_MINUTES}, using {DEFAULT_SILENT_MINUTES}"
        )
    return Thresholds(silent_after, tuple(problems))
