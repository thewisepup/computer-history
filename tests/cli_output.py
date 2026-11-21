"""Reading command output past the profile line every command starts with."""

from __future__ import annotations


def after_profile_line(out: str) -> str:
    """The output after its first line, which must be the profile line."""
    first, _, rest = out.partition("\n")
    assert first.startswith("Profile "), out
    return rest
