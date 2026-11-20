"""What a renderer is: it turns a whole timeline into one source family's raw data."""

from __future__ import annotations

import random
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple, Protocol

from computer_history.sources import HistorySource, Source
from computer_history.synthetic.timeline import Timeline


class Feed(NamedTuple):
    """The adapter ingest reads rendered data through, and the same adapter if it backfills."""

    source: Source
    history: HistorySource | None = None


class RenderedSource(Protocol):
    """One source family's raw data, rendered from a timeline."""

    def observation_counts(self) -> Mapping[str, int]:
        """How many observations each stream holds."""
        ...

    def feed(self, folder: Path) -> Feed:
        """An adapter over the data, keeping any files it needs in the folder."""
        ...


class Renderer(Protocol):
    """Renders a timeline into one source family's raw data for the streams it names."""

    name: str
    streams: tuple[str, ...]

    def render(self, timeline: Timeline, rng: random.Random) -> RenderedSource: ...
