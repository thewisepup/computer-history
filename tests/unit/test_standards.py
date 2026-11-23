from __future__ import annotations

import ast
import io
import re
import tokenize
import unicodedata
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "computer_history"
SOURCES = sorted(PACKAGE.rglob("*.py"))
TESTS = sorted((REPO / "tests").rglob("*.py"))
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
        if tok.type
        not in (
            tokenize.COMMENT,
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.ENDMARKER,
        )
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
    "host": (
        "computer_history.store",
        "computer_history.sources",
        "computer_history.synthetic",
        "computer_history.stable",
        "computer_history.watchdog",
        "computer_history.status",
        "computer_history.cli",
    ),
    "store": (
        "computer_history.sources",
        "computer_history.synthetic",
        "computer_history.stable",
        "computer_history.watchdog",
        "computer_history.status",
        "computer_history.cli",
    ),
    "sources": (
        "computer_history.synthetic",
        "computer_history.stable",
        "computer_history.watchdog",
        "computer_history.status",
        "computer_history.cli",
    ),
    "synthetic": (
        "computer_history.stable",
        "computer_history.watchdog",
        "computer_history.status",
        "computer_history.cli",
    ),
    "stable": (
        "computer_history.sources",
        "computer_history.synthetic",
        "computer_history.watchdog",
        "computer_history.status",
        "computer_history.cli",
    ),
    "watchdog": (
        "computer_history.synthetic",
        "computer_history.stable",
        "computer_history.status",
        "computer_history.cli",
    ),
    "status": ("computer_history.synthetic", "computer_history.cli"),
}
OPENERS = (
    "AWClient",
    "LiveHost",
    "connect",
    "connect_immutable",
    "connect_readonly",
    "open_store",
)
SCRATCH_DATABASE_LAYERS = ("synthetic",)
SCRATCH_OPENERS = ("connect", "connect_immutable")


@pytest.mark.parametrize("path", SOURCES, ids=_ids(SOURCES))
def test_layers_only_depend_downward(path: Path) -> None:
    forbidden = FORBIDDEN_IMPORTS.get(_layer(path), ())
    bad = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        elif isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        else:
            continue
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
        and not (scratch and node.func.id in SCRATCH_OPENERS and node.args)
    ]
    assert not calls, f"{_rel(path)}: take these as parameters instead: {calls}"


def _constants(path: Path) -> dict[str, str]:
    found = {}
    for node in _tree(path).body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        for target in targets:
            if isinstance(target, ast.Name) and target.id.isupper() and value is not None:
                found[target.id] = ast.dump(value)
    return found


SAME_BY_CHANCE = {"BROWSER": "each synthetic persona picks its own browser"}


def test_no_two_modules_define_the_same_constant() -> None:
    owners: dict[tuple[str, str], list[str]] = {}
    for path in SOURCES:
        for name, value in _constants(path).items():
            owners.setdefault((name, value), []).append(_rel(path))
    copies = sorted(
        f"{name}: {', '.join(paths)}"
        for (name, _), paths in owners.items()
        if len(paths) > 1 and name not in SAME_BY_CHANCE
    )
    assert not copies, f"define each constant once and import it: {copies}"


def test_the_cli_defines_no_constant_a_lower_layer_also_defines() -> None:
    cli = {
        name: (path, value)
        for path in SOURCES
        if _layer(path) == "cli"
        for name, value in _constants(path).items()
    }
    copies = [
        f"{name}: {_rel(cli[name][0])} and {_rel(path)}"
        for path in SOURCES
        if _layer(path) != "cli"
        for name, value in _constants(path).items()
        if name in cli and cli[name][1] == value
    ]
    assert not copies, f"import these from the lower layer instead of copying them: {copies}"


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


WORKFLOWS = REPO / ".github" / "workflows"
CHECKS_DOC = REPO / "docs" / "agents" / "checks.md"


def _jobs(workflow: Path) -> list[str]:
    text = workflow.read_text(encoding="utf-8")
    jobs = text[text.index("\njobs:\n") :]
    return re.findall(r"^  ([a-z][a-z0-9-]*):$", jobs, re.MULTILINE)


@pytest.mark.parametrize("workflow", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_the_checks_doc_names_every_ci_job(workflow: Path) -> None:
    doc = CHECKS_DOC.read_text(encoding="utf-8")

    assert _jobs(workflow)
    assert [job for job in _jobs(workflow) if f"`{job}`" not in doc] == []


TEST_FOLDERS = ("unit", "data", "perf", "e2e")


def test_every_test_file_sits_in_a_test_folder() -> None:
    stray = [
        _rel(path)
        for path in TESTS
        if (path.name.startswith("test_") or path.name.endswith("_test.py"))
        and path.relative_to(REPO / "tests").parts[0] not in TEST_FOLDERS
    ]
    assert stray == [], f"move these into one of tests/{{{','.join(TEST_FOLDERS)}}}: {stray}"


LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
LOGGING_PACKAGE = PACKAGE / "logs"
UNCONFIGURED = [path for path in SOURCES if not path.is_relative_to(LOGGING_PACKAGE)]


def _is_get_logger(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Attribute) and func.attr == "getLogger") or (
        isinstance(func, ast.Name) and func.id == "getLogger"
    )


def _logger_names(tree: ast.Module) -> set[str]:
    return {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and _is_get_logger(node.value)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def _log_calls(tree: ast.AST, loggers: set[str]):
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LOG_METHODS
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in loggers
        ):
            yield node


def test_the_log_checks_see_every_logger_whatever_its_name() -> None:
    tree = ast.parse(
        "import logging\nlogger = logging.getLogger(__name__)\n"
        "def f(x):\n    try:\n        g()\n    except E:\n"
        "        logger.error(f'bad {x}')\n        raise\n"
    )
    loggers = _logger_names(tree)
    assert loggers == {"logger"}
    assert [call.lineno for call in _log_calls(tree, loggers)] == [7]


@pytest.mark.parametrize("path", SOURCES, ids=_ids(SOURCES))
def test_log_messages_are_string_literals(path: Path) -> None:
    tree = _tree(path)
    bad = [
        f"line {call.lineno}"
        for call in _log_calls(tree, _logger_names(tree))
        if not call.args
        or not (isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str))
    ]
    assert not bad, f"{_rel(path)}: log a literal message and put the data in extra=: {bad}"


@pytest.mark.parametrize("path", SOURCES, ids=_ids(SOURCES))
def test_a_handler_that_logs_does_not_reraise(path: Path) -> None:
    tree = _tree(path)
    loggers = _logger_names(tree)
    bad = [
        f"line {handler.lineno}"
        for handler in ast.walk(tree)
        if isinstance(handler, ast.ExceptHandler)
        and any(True for _ in _log_calls(handler, loggers))
        and any(isinstance(node, ast.Raise) for node in ast.walk(handler))
    ]
    assert not bad, f"{_rel(path)}: log the exception where it is handled, or re-raise it: {bad}"


@pytest.mark.parametrize("path", UNCONFIGURED, ids=_ids(UNCONFIGURED))
def test_only_the_logs_package_configures_logging(path: Path) -> None:
    bad = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        name = node.func.attr
        if name in ("addHandler", "basicConfig", "dictConfig", "fileConfig"):
            bad.append(f"line {node.lineno}: {name}()")
        named_by_module = [a for a in node.args if isinstance(a, ast.Name) and a.id == "__name__"]
        if name == "getLogger" and not named_by_module:
            bad.append(f"line {node.lineno}: getLogger() without __name__")
    assert not bad, f"{_rel(path)}: use logging.getLogger(__name__) and leave setup to logs/: {bad}"
