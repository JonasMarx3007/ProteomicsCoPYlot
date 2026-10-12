"""Extract a dependency-closed subset of trusted notebook source, never user code."""
from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass
from pathlib import Path
import re
import symtable
import sys


@dataclass(frozen=True)
class NotebookSource:
    code: str
    functions: tuple[str, ...]
    imports: tuple[str, ...]


def _bindings(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    if isinstance(node, ast.Import):
        return {alias.asname or alias.name.split(".")[0] for alias in node.names}
    if isinstance(node, ast.ImportFrom):
        if any(alias.name == "*" for alias in node.names):
            raise ValueError("Wildcard imports cannot be exported reproducibly.")
        return {alias.asname or alias.name for alias in node.names}
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return {part.id for target in targets for part in ast.walk(target) if isinstance(part, ast.Name)}
    if isinstance(node, (ast.Try, ast.If)):
        return set().union(*(_bindings(child) for child in ast.iter_child_nodes(node)))
    if isinstance(node, ast.ExceptHandler):
        return set().union(*(_bindings(child) for child in node.body))
    return set()


def _global_references(code: str) -> set[str]:
    def visit(scope):
        names = {s.get_name() for s in scope.get_symbols() if s.is_referenced() and s.is_global()}
        for child in scope.get_children():
            names.update(visit(child))
        return names
    return visit(symtable.symtable(code, "functions.py", "exec"))


def _segment(source: str, node: ast.stmt) -> str:
    start = min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])
    return "\n".join(source.splitlines()[start - 1:node.end_lineno])


def extract_notebook_source(source: str, entry_points: tuple[str, ...]) -> NotebookSource:
    """Select definitions, constants and imports without executing the source.

    Unsupported dynamic dependencies fail closed. Callers supply trusted,
    installed CoPYlot source and server-owned entry-point names only.
    """
    tree = ast.parse(source)
    definitions: dict[str, ast.stmt] = {}
    for node in tree.body:
        for name in _bindings(node):
            if name in definitions:
                raise ValueError(f"Ambiguous notebook definition: {name}")
            definitions[name] = node
    selected: set[ast.stmt] = set()
    required = set(entry_points)
    allowed = set(dir(builtins)) | {"__name__"}
    while required:
        name = required.pop()
        if name in allowed:
            continue
        found = definitions.get(name)
        if found is None:
            raise ValueError(f"Notebook dependency is not portable: {name}")
        node = found
        if node in selected:
            continue
        selected.add(node)
        segment = _segment(source, node)
        for child in ast.walk(node):
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id in {
                "eval", "exec", "globals", "locals", "__import__", "compile",
            }:
                raise ValueError("Dynamic code is not supported in portable notebooks.")
            if isinstance(child, ast.ImportFrom) and (child.level or (child.module or "").startswith("app.")):
                raise ValueError("A notebook export must not depend on the application server.")
            if isinstance(child, ast.Import) and any(alias.name.split(".")[0] == "app" for alias in child.names):
                raise ValueError("A notebook export must not depend on the application server.")
        required.update(_global_references(segment) - _bindings(node))
    ordered = [node for node in tree.body if node in selected]
    imports: set[str] = set()
    for node in ordered:
        for part in ast.walk(node):
            if isinstance(part, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in part.names)
            elif isinstance(part, ast.ImportFrom) and part.module:
                imports.add(part.module.split(".")[0])
    code = "from __future__ import annotations\n\n" + "\n\n".join(
        _segment(source, node) for node in ordered
        if not (isinstance(node, ast.ImportFrom) and node.module == "__future__")
    ) + "\n"
    compile(code, "functions.py", "exec")
    return NotebookSource(code, tuple(sorted(
        node.name for node in ordered if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )), tuple(sorted(imports - {"__future__"})))


def module_source(name: str) -> str:
    """Read a trusted CoPYlot module's source with the shared core inlined.

    `name` is a file in `backend/app/services` or, for `notebook_functions.py`
    and `_core.py`, in the pip package. Frozen builds ship them as
    `notebook_sources`.
    """
    if getattr(sys, "frozen", False):
        path = Path(getattr(sys, "_MEIPASS")) / "notebook_sources" / name
    else:
        root = Path(__file__).resolve().parents[3]
        package = name in {"notebook_functions.py", "_core.py"}
        path = root / ("proteomicscopylot" if package else "backend/app/services") / name
    return _inline_core(path.read_text(encoding="utf-8"))


# A module may import part of another trusted module inside a marked block.
# Notebook exports must not import the application or the package, so the
# source they are extracted from carries those definitions in place of the
# block. Tag -> (file holding the definitions, suffixes its module name may have).
_INLINED_BLOCKS: dict[str, tuple[str, tuple[str, ...]]] = {
    "shared-core": ("_core.py", ("_core", "copylot_core")),
    "plot-vocabulary": ("plot_vocabulary.py", ("plot_vocabulary",)),
}
_BLOCK_PATTERN = r"^# <{tag}>.*?^# </{tag}>\n"


def _inline_core(text: str) -> str:
    """Replace each marked import block with the definitions it uses.

    `functions.py`, `stats_core.py` and `notebook_functions.py` import part of
    `proteomicscopylot/_core.py` inside a `# <shared-core>` block; `plot_styling.py`
    imports its vocabularies inside a `# <plot-vocabulary>` block. Whatever the
    inlined definitions need from their module comes along. Imports the module
    already makes are not repeated.
    """
    for tag, (file_name, suffixes) in _INLINED_BLOCKS.items():
        match = re.search(_BLOCK_PATTERN.format(tag=tag), text, re.MULTILINE | re.DOTALL)
        if match is None:
            continue
        wanted = {
            alias.asname or alias.name
            for node in ast.walk(ast.parse(match.group(0)))
            if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(suffixes)
            for alias in node.names
        }
        host = text[:match.start()] + text[match.end():]
        bound = set().union(*(_bindings(node) for node in ast.parse(host).body))
        core = module_source(file_name)
        core_body = ast.parse(core).body
        definitions: dict[str, ast.stmt] = {}
        for node in core_body:
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            for bound_name in _bindings(node):
                definitions[bound_name] = node
        selected: set[ast.stmt] = set()
        required = set(wanted)
        while required:
            wanted_node = definitions.get(required.pop())
            if wanted_node is None or wanted_node in selected:
                continue
            if isinstance(wanted_node, (ast.Import, ast.ImportFrom)) and _bindings(wanted_node) <= bound:
                continue
            selected.add(wanted_node)
            if not isinstance(wanted_node, (ast.Import, ast.ImportFrom)):
                required.update(_global_references(_segment(core, wanted_node)) - _bindings(wanted_node))
        inlined = "\n\n".join(_segment(core, node) for node in core_body if node in selected)
        text = text[:match.start()] + inlined + "\n" + text[match.end():]
    return text


def function_definition(source: str, name: str) -> str:
    """The source of top-level function `name` in `source`."""
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    segment = ast.get_source_segment(source, node)
    assert segment is not None  # a parsed function always has a source segment
    return segment


def replace_once(source: str, before: str, after: str) -> str:
    """Replace `before`, which must occur exactly once, so a renderer change is noticed."""
    if source.count(before) != 1:
        raise ValueError("The QC renderer changed; update its notebook adapter before exporting.")
    return source.replace(before, after, 1)


def merge_source(*sources: str) -> str:
    """Merge trusted subsets, omitting structurally identical statements."""
    seen = set()
    nodes = []
    for source in sources:
        for node in ast.parse(source).body:
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            key = ast.dump(node, include_attributes=False)
            if key not in seen:
                seen.add(key)
                nodes.append(_segment(source, node))
    return "\n\n".join(nodes)
