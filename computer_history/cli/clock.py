from __future__ import annotations

from datetime import UTC, datetime

AW_CHECK_TIMEOUT_SECONDS = 5


def utc_now() -> datetime:
    return datetime.now(UTC)
