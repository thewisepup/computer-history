from __future__ import annotations

import pytest


def logged(caplog: pytest.LogCaptureFixture, message: str) -> list[dict[str, object]]:
    """The attributes of every captured record with this message, oldest first."""
    return [vars(r) for r in caplog.records if r.getMessage() == message]
