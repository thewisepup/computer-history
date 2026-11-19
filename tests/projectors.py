from __future__ import annotations

import json
from dataclasses import fields

from computer_history.sources import KNOWN_SOURCES, projector_for
from computer_history.store import Signal

AW = projector_for(KNOWN_SOURCES)


def no_signal(source: str, payload: str) -> None:
    return None


def payload_fields(source: str, payload: str) -> Signal | None:
    data = json.loads(payload)
    found = {f.name: data[f.name] for f in fields(Signal) if f.name in data}
    return Signal(**found) if found else None
