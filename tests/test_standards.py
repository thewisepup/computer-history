from __future__ import annotations

import ast
import io
import re
import tokenize
import unicodedata
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent / "computer_history"
SOURCES = sorted(PACKAGE.rglob("*.py"))
TESTS = sorted(Path(__file__).resolve().parent.rglob("*.py"))
COMMENTED = SOURCES + TESTS

BANNED_MODULE_NAMES = {"utils", "helpers", "misc", "common", "shared", "types", "reads", "writes"}
DOCSTRING_MARKUP = re.compile(
    r"DESIGN\.md|§|\bticket \d+|:(?:func|class|mod|data|meth):|``|^\s*::\s*$", re.M
)
REASONING = re.compile(r";|\bbecause\b|\bso that\b|\bto avoid\b", re.I)
SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
ABBREVIATIONS = re.compile(r"\b(?:e\.g|i\.e|etc|vs)\.")
MAX_DOCSTRING_SENTENCES = 2


def _rel(path: Path) -> str:
    return str(path.relative_to(PACKAGE.parent))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _layer(path: Path) -> str:
    parts = path.relative_to(PACKAGE).parts
    return parts[0] if len(parts) > 1 else ""


def _ids(paths: list[Path]) -> list[str]:
    return [_rel(p) for p in paths]


def _docstring_nodes(tree: ast.Module):
    yield tree
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield node


def _sentences(text: str) -> int:
    return len(SENTENCE_END.findall(ABBREVIATIONS.sub("", text)))


@pytest.mark.parametrize("path", SOURCES, ids=_ids(SOURCES))
def test_module_name_is_not_a_grab_bag(path: Path) -> None:
    assert path.stem not in BANNED_MODULE_NAMES, (
        f"{_rel(path)}: name the module for what it owns, not {path.stem!r}"
    )


@pytest.mark.parametrize("path", COMMENTED, ids=_ids(COMMENTED))
def test_docstrings_have_no_doc_references_or_markup(path: Path) -> None:
    found = []
    for node in _docstring_nodes(_tree(path)):
        doc = ast.get_docstring(node, clean=False)
        if doc and (match := DOCSTRING_MARKUP.search(doc)):
            found.append(f"line {getattr(node, 'lineno', 1)}: {match.group().strip()!r}")
    assert not found, f"{_rel(path)}: docstring references or markup: {found}"


@pytest.mark.parametrize("path", COMMENTED, ids=_ids(COMMENTED))
def test_docstrings_are_at_most_two_sentences(path: Path) -> None:
    long = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            doc = ast.get_docstring(node)
            if doc and _sentences(doc) > MAX_DOCSTRING_SENTENCES:
                long.append(f"{node.name} (line {node.lineno})")
    assert not long, f"{_rel(path)}: docstrings over {MAX_DOCSTRING_SENTENCES} sentences: {long}"


@pytest.mark.parametrize("path", COMMENTED, ids=_ids(COMMENTED))
def test_comments_are_single_plain_lines(path: Path) -> None:
    problems = []
    previous_comment_line = None
    source = path.read_text(encoding="utf-8")
    code_lines = {
        tok.start[0]
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE,
                            tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER)
    }
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type != tokenize.COMMENT or "noqa" in tok.string or tok.string.startswith("# ---"):
            continue
        line = tok.start[0]
        if REASONING.search(tok.string):
            problems.append(f"line {line}: reasoning-style comment {tok.string!r}")
        if line not in code_lines and previous_comment_line == line - 1:
            problems.append(f"line {line}: multi-line comment block")
        previous_comment_line = line if line not in code_lines else None
    assert not problems, f"{_rel(path)}: {problems}"


@pytest.mark.parametrize("path", SOURCES, ids=_ids(SOURCES))
def test_no_private_names_imported_across_modules(path: Path) -> None:
    private = [
        f"line {node.lineno}: {alias.name} from {node.module}"
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("computer_history")
        for alias in node.names
        if alias.name.startswith("_") and not alias.name.startswith("__")
    ]
    assert not private, f"{_rel(path)}: make these public where they live: {private}"


FORBIDDEN_IMPORTS = {
    "store": ("computer_history.sources", "computer_history.synthetic", "computer_history.cli"),
    "sources": ("computer_history.synthetic", "computer_history.cli"),
    "synthetic": ("computer_history.cli",),
}
OPENERS = ("AWClient", "connect", "connect_readonly", "open_store")
SCRATCH_DATABASE_LAYERS = ("synthetic",)


@pytest.mark.parametrize("path", SOURCES, ids=_ids(SOURCES))
def test_layers_only_depend_downward(path: Path) -> None:
    forbidden = FORBIDDEN_IMPORTS.get(_layer(path), ())
    bad = []
    for node in ast.walk(_tree(path)):
        modules = []
        if isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        elif isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        bad += [f"line {node.lineno}: {m}" for m in modules if m.startswith(forbidden)]
    assert not bad, f"{_rel(path)}: {_layer(path)}/ must not import upward: {bad}"


@pytest.mark.parametrize("path", SOURCES, ids=_ids(SOURCES))
def test_only_the_store_runs_sql(path: Path) -> None:
    if _layer(path) == "store":
        return
    calls = [
        f"line {node.lineno}: .{node.func.attr}()"
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("execute", "executemany", "executescript")
    ]
    assert not calls, f"{_rel(path)}: SQL belongs in computer_history/store: {calls}"


@pytest.mark.parametrize("path", SOURCES, ids=_ids(SOURCES))
def test_only_the_cli_opens_connections_and_clients(path: Path) -> None:
    if _layer(path) in ("cli", "store"):
        return
    scratch = _layer(path) in SCRATCH_DATABASE_LAYERS
    calls = [
        f"line {node.lineno}: {node.func.id}()"
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in OPENERS
        and not (scratch and node.func.id == "connect" and node.args)
    ]
    assert not calls, f"{_rel(path)}: take these as parameters instead: {calls}"


DIAGRAMMED_PACKAGES = [
    init.parent
    for init in sorted(PACKAGE.rglob("__init__.py"))
    if re.search(r"\b\w+\.py\b", ast.get_docstring(_tree(init)) or "")
]


@pytest.mark.parametrize("package", DIAGRAMMED_PACKAGES, ids=_ids(DIAGRAMMED_PACKAGES))
def test_package_diagram_lists_every_module(package: Path) -> None:
    diagram = ast.get_docstring(_tree(package / "__init__.py")) or ""
    modules = {p.name for p in package.glob("*.py") if p.name != "__init__.py"}
    mentioned = set(re.findall(r"\b(\w+\.py)\b", diagram))
    missing, stale = sorted(modules - mentioned), sorted(mentioned - modules)
    assert not missing, f"{_rel(package)}: diagram is missing {missing}"
    assert not stale, f"{_rel(package)}: diagram names files that do not exist: {stale}"


DESIGN = PACKAGE.parent / "docs" / "DESIGN.md"
LAID_OUT_PACKAGES = ("store", "sources", "synthetic")


def _layout_block(package: str) -> str:
    layout = DESIGN.read_text(encoding="utf-8").split("\ncomputer_history/\n", 1)[1]
    block = re.search(rf"^  {package}/ +#(.*?)(?=^  \S)", layout, re.MULTILINE | re.DOTALL)
    assert block, f"docs/DESIGN.md's package layout has no {package}/ entry"
    return block.group(1)


@pytest.mark.parametrize("package", LAID_OUT_PACKAGES)
def test_the_design_layout_names_every_module(package: str) -> None:
    block = _layout_block(package)
    modules = sorted({p.stem for p in (PACKAGE / package).rglob("*.py")} - {"__init__"})
    missing = [stem for stem in modules if not re.search(rf"\b{stem}\b", block)]
    assert not missing, f"docs/DESIGN.md's {package}/ layout is missing {missing}"


@pytest.mark.parametrize("path", COMMENTED, ids=_ids(COMMENTED))
def test_invisible_characters_are_written_as_escapes(path: Path) -> None:
    raw = [
        f"line {number}: U+{ord(char):04X}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        for char in line
        if unicodedata.category(char) in ("Cf", "Mn", "Zl", "Zp")
    ]
    assert not raw, f"{_rel(path)}: write these as \\u escapes: {raw}"
