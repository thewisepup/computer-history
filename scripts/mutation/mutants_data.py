"""Read mutmut's results, its test-to-function map and each mutant's diff from mutants/."""

import ast
import difflib
import json
from pathlib import Path

KILLED = {1, 3}
STATUS = {
    0: "survived", 1: "killed", 3: "killed", 5: "no tests", 33: "no tests", None: "not checked"
}


def load_exit_codes(mutants: Path) -> dict[str, int | None]:
    codes: dict[str, int | None] = {}
    for meta in sorted(mutants.rglob("*.py.meta")):
        codes.update(json.loads(meta.read_text())["exit_code_by_key"])
    return codes


def status(code: int | None) -> str:
    return STATUS.get(code, "timeout" if code in {-24, 24, 36, 152, 255} else "suspicious")


def load_stats(mutants: Path) -> dict:
    return json.loads((mutants / "mutmut-stats.json").read_text())


def source_file(mutants: Path, mutant: str) -> Path:
    module = mutant.partition("__mutmut_")[0].rsplit(".", 1)[0]
    return mutants / (module.replace(".", "/") + ".py")


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
    original = sources.get(local.partition("__mutmut_")[0] + "__mutmut_orig", "")
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


def only_changes_a_string(pairs: list[tuple[str, str]]) -> bool:
    """True when every changed line differs only by XX-wrapping or recasing a string."""
    return bool(pairs) and all(
        new.replace("XX", "") == old or new.lower() == old.lower() for old, new in pairs
    )
