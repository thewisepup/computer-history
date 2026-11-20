from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


def duration(seconds: float) -> str:
    """Format seconds like 42s, 3m 12s, 2h 5m or 1d 3h."""
    total = max(0, round(seconds))
    if total < 60:
        return f"{total}s"
    parts: list[str] = []
    for suffix, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        value, total = divmod(total, size)
        if value:
            parts.append(f"{value}{suffix}")
            if len(parts) == 2:
                break
    return " ".join(parts)


def lag(delta: timedelta) -> str:
    seconds = delta.total_seconds()
    if seconds < 0:
        return f"{duration(-seconds)} ahead of now"
    return f"{duration(seconds)} behind now"


def ago(value: datetime | None, now: datetime) -> str:
    """Local wall-clock time and how long before now it was, or never when missing."""
    if value is None:
        return "never"
    seconds = (now - value).total_seconds()
    if seconds < 0:
        return f"{when(value)} ({duration(-seconds)} ahead of now)"
    return f"{when(value)} ({duration(seconds)} ago)"


def when(value: datetime | None) -> str:
    """Local wall-clock time, to the minute. A dash when missing."""
    return "-" if value is None else value.astimezone().strftime("%Y-%m-%d %H:%M")


def app_name(value: str | None) -> str:
    """An app name with unprintable characters dropped, or a placeholder when missing."""
    return "(no name)" if value is None else "".join(c for c in value if c.isprintable())


def db_size(path: Path) -> str:
    size = human_size(path.stat().st_size)
    wal = path.with_name(path.name + "-wal")
    if wal.exists() and wal.stat().st_size:
        size += f" + {human_size(wal.stat().st_size)} WAL"
    return size


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    value = n / 1024
    for unit in ("KB", "MB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
