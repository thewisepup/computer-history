"""The three candidate scrubbers behind one interface.

Each exposes `scrub(text) -> (clean_text, [label, ...])`; a label is the typed marker's
name, so the replacement is `[secret:<label>]`.
"""

from __future__ import annotations

import math
import re
import tomllib
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable

HERE = Path(__file__).parent

Span = tuple[int, int, str]


def apply_spans(text: str, spans: Iterable[Span]) -> tuple[str, list[str]]:
    """Replace non-overlapping spans (earliest, then longest, wins) with typed markers."""
    kept: list[Span] = []
    end = -1
    for s, e, label in sorted(spans, key=lambda x: (x[0], -(x[1] - x[0]))):
        if s >= end:
            kept.append((s, e, label))
            end = e
    out, pos = [], 0
    for s, e, label in kept:
        out.append(text[pos:s])
        out.append(f"[secret:{label}]")
        pos = e
    out.append(text[pos:])
    return "".join(out), [k[2] for k in kept]


def shannon(s: str) -> float:
    if not s:
        return 0.0
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in Counter(s).values())


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ---------------------------------------------------------------- hand-written

_PLACEHOLDER = re.compile(
    r"^(?:\$|\{\{|<|%|\*+$|x+$|your|my[-_]|changeme|example|placeholder|none$|null$|true$|false$|"
    r"redacted|undefined|string$|env\b|process\.env|os\.|self\.|config\.|settings\.|args\.)",
    re.I,
)
_IDENT_LIKE = re.compile(r"^[A-Za-z_][A-Za-z_.\[\]()]*$")

_HAND: list[tuple[str, re.Pattern[str], int]] = []


def _p(label: str, pattern: str, group: int = 0, flags: int = 0) -> None:
    _HAND.append((label, re.compile(pattern, flags), group))


_p("private-key", r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----|\Z)")
_p("aws-key", r"\b(?:AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}\b")
_p("github-token", r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")
_p("github-token", r"\bgithub_pat_[A-Za-z0-9_]{22,255}\b")
_p("anthropic-key", r"\bsk-ant-[A-Za-z0-9_-]{20,}")
_p("openai-key", r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}")
_p("slack-token", r"\bxox[abeoprs]-[A-Za-z0-9-]{10,}")
_p("slack-webhook", r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+")
_p("stripe-key", r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}")
_p("stripe-key", r"\bwhsec_[A-Za-z0-9]{24,}")
_p("google-api-key", r"\bAIza[0-9A-Za-z_-]{35}\b")
_p("jwt", r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")
_p("sendgrid-key", r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}")
_p("twilio-key", r"\b(?:SK|AC)[0-9a-f]{32}\b")
_p("npm-token", r"\bnpm_[A-Za-z0-9]{36}\b")
_p("pypi-token", r"\bpypi-AgEIcHlwaS5vcmc[A-Za-z0-9_-]{50,}")
_p("gitlab-token", r"\bglpat-[A-Za-z0-9_-]{20,}")
_p("huggingface-token", r"\bhf_[A-Za-z0-9]{30,}\b")
_p("telegram-token", r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b")
_p("digitalocean-token", r"\bdop_v1_[a-f0-9]{64}\b")
_p("shopify-token", r"\bshp(?:at|ca|pa|ss)_[a-f0-9]{32}\b")
_p("linear-key", r"\blin_api_[A-Za-z0-9]{40}\b")
_p("postman-key", r"\bPMAK-[a-f0-9]{24}-[a-f0-9]{34}\b")
_p("mailchimp-key", r"\b[0-9a-f]{32}-us\d{1,2}\b")
_p("url-credential", r"\b[a-z][a-z0-9+.-]{1,20}://([^\s/:@'\"]+:[^\s/@'\"]{3,})@", group=1, flags=re.I)
_p(
    "url-query-secret",
    r"[?&;](?:access_token|refresh_token|id_token|token|api[_-]?key|apikey|key|secret|"
    r"client_secret|password|passwd|pwd|auth|sig|signature)=([^&\s#\"'<>]{12,})",
    group=1,
    flags=re.I,
)
_p("bearer-token", r"\b[Bb]earer\s+([A-Za-z0-9._~+/=-]{20,})", group=1)
_p("basic-auth", r"\b[Bb]asic\s+([A-Za-z0-9+/]{16,}={0,2})(?=\s|$|[\"'])", group=1)
_KV = re.compile(
    r"""(?ix)
    ([A-Za-z0-9_.-]{0,40}(?:secret|token|passw(?:or)?d|passwd|api[_-]?key|apikey|private[_-]?key|
    access[_-]?key|auth[_-]?key|credential)[A-Za-z0-9_.-]{0,40})
    ["']?\s*[:=]\s*["']?
    ([^\s"',;]{8,})"""
)
# v2 additions, made after reading v1's false positives on the corpus
_BENIGN_KEY = re.compile(
    r"(?:count|length|len|size|name|id|type|url|uri|path|field|file|ttl|limit|format|header|prefix)$",
    re.I,
)
_DOTTED = re.compile(r"^[A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)+[})\]]*$")


def _kv_ok(value: str, key: str, v2: bool) -> bool:
    if _PLACEHOLDER.match(value) or _IDENT_LIKE.match(value) or "(" in value:
        return False
    if v2 and (_BENIGN_KEY.search(key) or _DOTTED.match(value) or "://" in value or value[0] in "{<"):
        return False
    has_digit = any(c.isdigit() for c in value)
    has_alpha = any(c.isalpha() for c in value)
    return (has_digit and has_alpha) or shannon(value) >= 3.5


def _handwritten(text: str, v2: bool) -> tuple[str, list[str]]:
    spans: list[Span] = []
    for label, pat, group in _HAND:
        for m in pat.finditer(text):
            spans.append((*m.span(group), label))
    for m in _KV.finditer(text):
        value = m.group(2)
        start = m.start(2)
        if v2:  # `token_count=3&session=abc` is two parameters, not one value
            cut = re.search(r"&(?=\w+=)", value)
            value = value[: cut.start()] if cut else value
        if len(value) >= 8 and _kv_ok(value, m.group(1), v2):
            spans.append((start, start + len(value), "credential-assignment"))
    return apply_spans(text, spans)


def handwritten_v1(text: str) -> tuple[str, list[str]]:
    return _handwritten(text, v2=False)


def handwritten_v2(text: str) -> tuple[str, list[str]]:
    return _handwritten(text, v2=True)


# ------------------------------------------------------------- gitleaks (port)

_POSIX = {
    "[:alnum:]": "a-zA-Z0-9",
    "[:alpha:]": "a-zA-Z",
    "[:digit:]": "0-9",
    "[:xdigit:]": "0-9a-fA-F",
    "[:word:]": r"\w",
    "[:upper:]": "A-Z",
    "[:lower:]": "a-z",
    "[:space:]": r"\s",
}


def go_to_python(rx: str) -> str:
    """Translate the Go (RE2) syntax gitleaks' rules use into Python's `re` syntax."""
    for k, v in _POSIX.items():
        rx = rx.replace(k, v)
    rx = rx.replace(r"\z", r"\Z")
    rx = re.sub(r"\(\?<([A-Za-z_]\w*)>", r"(?P<\1>", rx)
    out: list[str] = []
    # Go applies an inline flag group `(?i)` to the rest of the enclosing group, across `|`.
    # Python needs `(?i:...)`, so close the scope before each `|` and reopen it after.
    pending: list[list[str]] = [[]]
    i, in_class = 0, False
    while i < len(rx):
        c = rx[i]
        if c == "\\":
            out.append(rx[i : i + 2])
            i += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
            out.append(c)
        elif c == "[":
            in_class = True
            out.append(c)
            if rx[i + 1 : i + 2] == "^":
                out.append("^")
                i += 1
            if rx[i + 1 : i + 2] == "]":
                out.append("]")
                i += 1
        elif c == "(":
            m = re.match(r"\(\?([a-z-]+)\)", rx[i:])
            if m and i > 0:
                out.append(f"(?{m.group(1)}:")
                pending[-1].append(m.group(1))
                i += m.end()
                continue
            pending.append([])
            out.append(c)
        elif c == ")":
            out.append(")" * len(pending.pop()))
            out.append(c)
        elif c == "|" and pending[-1]:
            out.append(")" * len(pending[-1]) + "|" + "".join(f"(?{f}:" for f in pending[-1]))
        else:
            out.append(c)
        i += 1
    out.append(")" * len(pending[0]))
    return "".join(out)


class GitleaksPort:
    """gitleaks' rules (v8.30.1 `config/gitleaks.toml`) run through Python `re`.

    Follows gitleaks' pipeline: keyword prefilter, regex, secret group, entropy floor,
    global then rule allowlists (regexes against secret/match/line, stopwords).
    """

    def __init__(self, toml_path: Path = HERE / "gitleaks.toml") -> None:
        cfg = tomllib.loads(toml_path.read_text())
        self.global_regexes = [re.compile(go_to_python(r)) for r in cfg["allowlist"].get("regexes", [])]
        self.global_stop = [s.lower() for s in cfg["allowlist"].get("stopwords", [])]
        self.rules: list[dict] = []
        self.unported: list[str] = []
        self.path_only: list[str] = []
        for r in cfg["rules"]:
            if "regex" not in r:
                continue
            if "path" in r:  # fires only on matching file names, and signals have none
                self.path_only.append(r["id"])
                continue
            try:
                rx = re.compile(go_to_python(r["regex"]))
                allows = []
                for a in r.get("allowlists", []):
                    allows.append(
                        {
                            "regexes": [re.compile(go_to_python(x)) for x in a.get("regexes", [])],
                            "target": a.get("regexTarget", "secret"),
                            "stop": [s.lower() for s in a.get("stopwords", [])],
                            "cond": a.get("condition", "OR"),
                        }
                    )
            except re.error as e:
                self.unported.append(f"{r['id']}: {e}")
                continue
            self.rules.append(
                {
                    "id": r["id"],
                    "rx": rx,
                    "kw": [k.lower() for k in r.get("keywords", [])],
                    "entropy": r.get("entropy", 0),
                    "group": r.get("secretGroup", 0),
                    "allows": allows,
                }
            )

    def _allowed(self, a: dict, secret: str, match: str, line: str) -> bool:
        checks: list[bool] = []
        if a["regexes"]:
            tgt = {"secret": secret, "match": match, "line": line}[a["target"]]
            checks.append(any(x.search(tgt) for x in a["regexes"]))
        if a["stop"]:
            checks.append(any(w in secret.lower() for w in a["stop"]))
        if not checks:
            return False
        return all(checks) if a["cond"] == "AND" else any(checks)

    def scrub(self, text: str) -> tuple[str, list[str]]:
        low = text.lower()
        spans: list[Span] = []
        for r in self.rules:
            if r["kw"] and not any(k in low for k in r["kw"]):
                continue
            for m in r["rx"].finditer(text):
                g = r["group"] or next((k for k, v in enumerate(m.groups(), 1) if v), 0)
                secret = m.group(g)
                if r["entropy"] and shannon(secret) <= r["entropy"]:
                    continue
                if any(x.search(secret) for x in self.global_regexes):
                    continue
                if any(w in secret.lower() for w in self.global_stop):
                    continue
                line_s = text.rfind("\n", 0, m.start()) + 1
                line_e = text.find("\n", m.end())
                line = text[line_s : len(text) if line_e < 0 else line_e]
                if any(self._allowed(a, secret, m.group(0), line) for a in r["allows"]):
                    continue
                spans.append((*m.span(g), r["id"]))
        return apply_spans(text, spans)


# ------------------------------------------------------------- detect-secrets


class DetectSecrets:
    """Yelp's detect-secrets 1.5.0 as a library: every plugin, default filters.

    mode "file": entropy plugins need quoted strings (what `scan` does on files).
    mode "adhoc": `scan_line`'s eager search, which also tries unquoted strings.
    Line-oriented: text is scanned line by line (a collapsed signal is one line).
    """

    def __init__(self, mode: str = "file", full_match: bool = False) -> None:
        from detect_secrets.core import scan as ds_scan
        from detect_secrets.plugins.base import RegexBasedDetector
        from detect_secrets.core.plugins.util import get_mapping_from_secret_type_to_class
        from detect_secrets.core.scan import get_plugins
        from detect_secrets.settings import get_settings, transient_settings
        from detect_secrets.util.code_snippet import get_code_snippet

        self.mode = mode
        self.full_match = full_match
        self._regex_based = RegexBasedDetector
        self._scan = ds_scan
        self._snippet = get_code_snippet
        self._ctx = transient_settings(
            {
                "plugins_used": [
                    {"name": cls.__name__} for cls in get_mapping_from_secret_type_to_class().values()
                ]
            }
        )
        self._ctx.__enter__()
        get_settings().disable_filters("detect_secrets.filters.common.is_invalid_file")
        self._plugins = list(get_plugins())

    def _regex_plugin(self, plugin, line, ctx, offset, spans) -> None:
        """Regex plugins yield only a capture group as `secret_value` (for GitHub tokens, just
        the `ghp` prefix). Re-run their denylist and take the whole match's span instead."""
        for rx in plugin.denylist:
            for m in rx.finditer(line):
                value = next((g for g in m.groups() if g), m.group(0))
                if self._scan._is_filtered_out(
                    required_filter_parameters=["context"],
                    filename="adhoc-string-scan",
                    secret=value,
                    plugin=plugin,
                    line=line,
                    context=ctx,
                ):
                    continue
                spans.append((offset + m.start(), offset + m.end(), slug(plugin.secret_type)))

    def scrub(self, text: str) -> tuple[str, list[str]]:
        spans: list[Span] = []
        offset = 0
        for line in text.split("\n"):
            ctx = self._snippet(lines=[line], line_number=1)
            for plugin in self._plugins:
                if self.full_match and isinstance(plugin, self._regex_based):
                    self._regex_plugin(plugin, line, ctx, offset, spans)
                    continue
                for sec in self._scan._scan_line(
                    plugin=plugin,
                    filename="adhoc-string-scan",
                    line=line,
                    line_number=0,
                    enable_eager_search=(self.mode == "adhoc"),
                    context=ctx,
                ):
                    if self._scan._is_filtered_out(
                        required_filter_parameters=["context"],
                        filename=sec.filename,
                        secret=sec.secret_value,
                        plugin=plugin,
                        line=line,
                        context=ctx,
                    ):
                        continue
                    v = sec.secret_value
                    if not v:
                        continue
                    for m in re.finditer(re.escape(v), line):
                        spans.append((offset + m.start(), offset + m.end(), slug(sec.type)))
            offset += len(line) + 1
        return apply_spans(text, spans)


def candidates() -> dict[str, Callable[[str], tuple[str, list[str]]]]:
    return {
        "hand-written v1 (first draft)": handwritten_v1,
        "hand-written v2 (tuned on v1 false positives)": handwritten_v2,
        "gitleaks-port": GitleaksPort().scrub,
        "detect-secrets (file mode)": DetectSecrets("file").scrub,
        "detect-secrets (file mode, full-match spans)": DetectSecrets("file", True).scrub,
        "detect-secrets (adhoc mode, full-match spans)": DetectSecrets("adhoc", True).scrub,
    }
