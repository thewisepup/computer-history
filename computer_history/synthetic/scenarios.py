"""What happens to the user: each scenario places its happenings on the ordinary timeline."""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from types import MappingProxyType

from computer_history.synthetic.timeline import Timeline

Scenario = Callable[[Timeline, random.Random], Timeline]


def typical(timeline: Timeline, rng: random.Random) -> Timeline:
    """An ordinary stretch of time with nothing going wrong."""
    return timeline


SCENARIOS: Mapping[str, Scenario] = MappingProxyType({"typical": typical})
