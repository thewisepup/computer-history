"""Read mutmut's results, its test-to-function map and each mutant's diff from mutants/."""

import ast
import difflib
import json
from pathlib import Path

MUTANTS = Path(__file__).resolve().parents[2] / "mutants"
STATUS = {
    0: "survived", 1: "killed", 3: "killed", 5: "no tests", 33: "no tests", None: "not checked",
    -24: "timeout", 24: "timeout", 36: "timeout", 152: "timeout", 255: "timeout",
}


def load_exit_codes(mutants: Path) -> dict[str, int | None]:
    codes: dict[str, int | None] = {}
    for meta in sorted(mutants.rglob("*.py.meta")):
        codes.update(json.loads(meta.read_text())["exit_code_by_key"])
    return codes


def status(code: int | None) -> str:
    return STATUS.get(code, "suspicious")


def caught(code: int | None) -> bool:
    """True when the suite catches the mutant, by failing or by hanging."""
    return status(code) in {"killed", "timeout"}


def mutant_function(mutant: str) -> str:
    return mutant.partition("__mutmut_")[0]


def mutant_module(mutant: str) -> str:
    return mutant_function(mutant).rsplit(".", 1)[0]


def load_stats(mutants: Path) -> dict:
    return json.loads((mutants / "mutmut-stats.json").read_text())


def source_file(mutants: Path, mutant: str) -> Path:
    return mutants / (mutant_module(mutant).replace(".", "/") + ".py")


def _function_sources(path: Path) -> dict[str, str]:
    text = path.read_text()
    sources = {}
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and "__mutmut_" in node.name:
            sources[node.name] = ast.get_source_segment(text, node) or ""
    return sources


_cache: dict[Path, dict[str, str]] = {}


def mutant_diff(mutants: Path, mutant: str) -> list[tuple[str, str]]:
    """Each changed line of a mutant as an (original, mutated) pair."""
    path = source_file(mutants, mutant)
    if path not in _cache:
        _cache[path] = _function_sources(path)
    sources = _cache[path]
    local = mutant.rsplit(".", 1)[1]
    original = sources.get(mutant_function(local) + "__mutmut_orig", "")
    mutated = sources.get(local, "")
    old_lines = original.splitlines()[1:]
    new_lines = mutated.splitlines()[1:]
    pairs = []
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old = " / ".join(line.strip() for line in old_lines[i1:i2])
        new = " / ".join(line.strip() for line in new_lines[j1:j2])
        pairs.append((old, new))
    return pairs


def only_changes_a_message(pairs: list[tuple[str, str]]) -> bool:
    """True when every changed line only XX-wraps a string that contains a space."""
    return bool(pairs) and all(
        new.replace("XX", "") == old and _wrapped_has_space(new) for old, new in pairs
    )


def _wrapped_has_space(line: str) -> bool:
    parts = line.split("XX")
    return any(" " in parts[i] for i in range(1, len(parts), 2))
