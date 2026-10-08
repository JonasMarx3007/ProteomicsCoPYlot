"""Extract a dependency-closed subset of trusted notebook source, never user code."""
from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass
import symtable


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
