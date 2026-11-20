from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime

_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2066-\u2069\ufeff]")
_RECORD_ATTRIBUTES = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "run", "cmd"}
_PACKAGE_PREFIX = "computer_history."
_TEXT_TIME = "%Y-%m-%d %H:%M:%S"


def escape(text: str) -> str:
    """The text with control, line-breaking and invisible characters written as escapes."""
    return _CONTROL.sub(_escaped, text)


def _escaped(match: re.Match[str]) -> str:
    code = ord(match.group())
    return f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}"


class _DocFormatter(logging.Formatter):
    def doc(self, record: logging.LogRecord) -> dict[str, object]:
        doc: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            "run": getattr(record, "run", "-"),
            "cmd": getattr(record, "cmd", "-"),
        }
        doc.update((k, v) for k, v in vars(record).items() if k not in _RECORD_ATTRIBUTES)
        if record.exc_info:
            doc["exc"] = self.formatException(record.exc_info)
        return doc


class JsonFormatter(_DocFormatter):
    """A record as one JSON object on one line, with its extra fields."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(self.doc(record), default=str)


class TextFormatter(_DocFormatter):
    """A record as one readable line: time, level, logger, message and its plain fields."""

    def format(self, record: logging.LogRecord) -> str:
        return text_line(self.doc(record))


def text_line(doc: dict[str, object], *, with_run: bool = False) -> str:
    """One JSON log record as a text line, its traceback indented below it."""
    ts = datetime.fromisoformat(str(doc.get("ts"))).astimezone().strftime(_TEXT_TIME)
    level = str(doc.get("level", "")).upper()
    logger = str(doc.get("logger", "")).removeprefix(_PACKAGE_PREFIX)
    head = f"{ts} {level:<7} {logger}"
    if with_run:
        head += f" [{doc.get('cmd', '-')} {doc.get('run', '-')}]"
    line = f"{head}  {escape(str(doc.get('msg', '')))}"
    fields = " ".join(
        f"{key}={_value(value)}"
        for key, value in doc.items()
        if key not in _DOC_KEYS and isinstance(value, str | int | float | bool | None)
    )
    if fields:
        line += f"  {fields}"
    exc = doc.get("exc")
    if isinstance(exc, str):
        line += "".join(f"\n  | {escape(part)}" for part in exc.splitlines())
    return line


_DOC_KEYS = {"ts", "level", "logger", "msg", "run", "cmd", "exc"}


def _value(value: object) -> str:
    if isinstance(value, str) and (not value or any(c.isspace() or c in '"=' for c in value)):
        return '"' + escape(value).replace('"', '\\"') + '"'
    return escape(str(value))
