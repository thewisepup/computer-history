"""The four inputs that pick a dataset, and the timeline they always produce."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from computer_history.synthetic.days import live
from computer_history.synthetic.developer import DEVELOPER
from computer_history.synthetic.persona import Persona
from computer_history.synthetic.scenarios import SCENARIOS
from computer_history.synthetic.seeds import part_random
from computer_history.synthetic.timeline import Timeline, local_midnight

PERSONAS: Mapping[str, Persona] = MappingProxyType({DEVELOPER.name: DEVELOPER})
TIERS: Mapping[str, int] = MappingProxyType({"day": 1})
DEFAULT_START = date(2026, 1, 5)
DEFAULT_TIMEZONE = "America/Los_Angeles"


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
    start = local_midnight(inputs.start, zone)
    end = local_midnight(inputs.start + timedelta(days=days), zone)
    persona = PERSONAS[inputs.persona]
    rng = part_random(inputs.seed, f"persona:{persona.name}")
    stretches = live(persona, inputs.start, days, inputs.timezone, rng)
    ordinary = Timeline(start, end, inputs.timezone, stretches)
    scenario = SCENARIOS[inputs.scenario]
    return scenario(ordinary, part_random(inputs.seed, f"scenario:{inputs.scenario}"))
