"""The four inputs that pick a dataset, and the timeline they always produce."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from computer_history.synthetic.developer import DEVELOPER
from computer_history.synthetic.persona import Persona, live
from computer_history.synthetic.scenarios import SCENARIOS
from computer_history.synthetic.timeline import (
    DEFAULT_START,
    DEFAULT_TIMEZONE,
    Timeline,
    part_random,
)

PERSONAS: Mapping[str, Persona] = MappingProxyType({DEVELOPER.name: DEVELOPER})
TIERS: Mapping[str, int] = MappingProxyType({"day": 1})


@dataclass(frozen=True)
class DatasetInputs:
    """Who the user is, what happens, how many days and the seed, plus where the range starts."""

    persona: str
    scenario: str
    tier: str
    seed: int
    start: date = DEFAULT_START
    timezone: str = DEFAULT_TIMEZONE

    def __post_init__(self) -> None:
        for name, value, known in (
            ("persona", self.persona, PERSONAS),
            ("scenario", self.scenario, SCENARIOS),
            ("tier", self.tier, TIERS),
        ):
            if value not in known:
                raise ValueError(f"unknown {name} {value!r}: pick one of {sorted(known)}")
        ZoneInfo(self.timezone)


def generate_timeline(inputs: DatasetInputs) -> Timeline:
    """The persona's ordinary days over the tier's range, with the scenario's happenings placed."""
    days = TIERS[inputs.tier]
    zone = ZoneInfo(inputs.timezone)
    start = datetime.combine(inputs.start, time(), zone).astimezone(UTC)
    end = datetime.combine(inputs.start + timedelta(days=days), time(), zone).astimezone(UTC)
    persona = PERSONAS[inputs.persona]
    rng = part_random(inputs.seed, f"persona:{persona.name}")
    stretches = live(persona, inputs.start, days, inputs.timezone, rng)
    ordinary = Timeline(start, end, inputs.timezone, stretches)
    scenario = SCENARIOS[inputs.scenario]
    return scenario(ordinary, part_random(inputs.seed, f"scenario:{inputs.scenario}"))
