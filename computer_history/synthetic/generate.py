"""The inputs that pick a dataset, and the timeline they always produce."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from computer_history.synthetic.content_creator import CONTENT_CREATOR
from computer_history.synthetic.days import live
from computer_history.synthetic.developer import DEVELOPER
from computer_history.synthetic.persona import Persona, heavier
from computer_history.synthetic.scenarios import SCENARIOS
from computer_history.synthetic.seeds import part_random
from computer_history.synthetic.timeline import Timeline, local_midnight

PERSONAS: Mapping[str, Persona] = MappingProxyType(
    {persona.name: persona for persona in (DEVELOPER, CONTENT_CREATOR)}
)
TIERS: Mapping[str, int] = MappingProxyType({"day": 1, "week": 7, "month": 30, "year": 365})
HEAVY = 2.0
DEFAULT_START = date(2026, 1, 5)
DEFAULT_TIMEZONE = "America/Los_Angeles"


@dataclass(frozen=True)
class DatasetInputs:
    """Who the user is, what happens, how many days and the seed, plus where the range starts.

    A heavy factor above 1 makes the persona a heavier user, and HEAVY is the usual one.
    """

    persona: str
    scenario: str
    tier: str
    seed: int
    start: date = DEFAULT_START
    timezone: str = DEFAULT_TIMEZONE
    heavy: float = 1.0

    def __post_init__(self) -> None:
        for name, value, known in (
            ("persona", self.persona, PERSONAS),
            ("scenario", self.scenario, SCENARIOS),
            ("tier", self.tier, TIERS),
        ):
            if value not in known:
                raise ValueError(f"unknown {name} {value!r}: pick one of {sorted(known)}")
        ZoneInfo(self.timezone)
        heavier(PERSONAS[self.persona], self.heavy)


def generate_timeline(inputs: DatasetInputs) -> Timeline:
    """The persona's ordinary days over the tier's range, with the scenario's happenings placed.

    Heavy scales the persona before it fills the range.
    """
    days = TIERS[inputs.tier]
    zone = ZoneInfo(inputs.timezone)
    start = local_midnight(inputs.start, zone)
    end = local_midnight(inputs.start + timedelta(days=days), zone)
    persona = heavier(PERSONAS[inputs.persona], inputs.heavy)
    rng = part_random(inputs.seed, f"persona:{persona.name}")
    stretches = live(persona, inputs.start, days, inputs.timezone, rng)
    ordinary = Timeline(start, end, inputs.timezone, stretches)
    scenario = SCENARIOS[inputs.scenario]
    return scenario(ordinary, part_random(inputs.seed, f"scenario:{inputs.scenario}"))
