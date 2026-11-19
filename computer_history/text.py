from __future__ import annotations

from urllib.parse import urlsplit

MAX_TEXT_LENGTH = 2000
MAX_URL_LENGTH = 4096

_URL_CONTROL_CHARS = dict.fromkeys([*range(0x20), 0x7F])


def clean_text(value: str | None, limit: int = MAX_TEXT_LENGTH) -> str | None:
    """Strip and collapse whitespace and cap the length. Empty becomes None."""
    if value is None:
        return None
    return " ".join(_scrub(value).split())[:limit] or None


def clean_url(value: str | None) -> str | None:
    """Remove control characters and cap the length. Empty becomes None."""
    if value is None:
        return None
    return _sanitize_url(value)[:MAX_URL_LENGTH] or None


def extract_domain(url: str | None) -> str | None:
    """The lowercased host of a web URL, without port or a leading www.

    Missing, unreadable and non-web URLs (chrome://, file://, ...) become None.
    """
    if not url:
        return None
    try:
        parts = urlsplit(_sanitize_url(url))
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host:
        return None
    host = host.rstrip(".")
    if host.startswith("www."):
        host = host[len("www.") :]
    return host or None


def _sanitize_url(value: str) -> str:
    return _scrub(value).translate(_URL_CONTROL_CHARS).strip(" ")


def _scrub(value: str) -> str:
    # Replace characters SQLite cannot store.
    return value.encode("utf-8", "replace").decode("utf-8")
