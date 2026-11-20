"""Fixed randomness: every part of the generator draws from its own seeded generator."""

from __future__ import annotations

import hashlib
import random


def part_random(seed: int, part: str) -> random.Random:
    """A random generator for one part of the generator, fixed by the seed and the part's name."""
    digest = hashlib.sha256(f"{seed}:{part}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))
