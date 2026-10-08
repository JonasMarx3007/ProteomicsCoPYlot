"""Code-shape rules for the backend that ruff has no rule for.

    python tools/check_backend_rules.py     # exit 1 and list the violations

The backend counterpart of the `no-restricted-syntax` rules in
frontend/eslint.config.js: each rule is about how code is written, not what it
does, so it is checked on the syntax tree rather than by running anything. CI
runs it beside ruff, and tests/repo/test_backend_code_rules.py runs it too and
checks each rule against a snippet that breaks it.

These replaced line-by-line string searches in tests/unit/security, which a
reformatted line slipped past.
"""
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Names a service uses for a filesystem location. A user-facing message that
# prints one tells whoever triggered it how the server is laid out; printing
# just the file's own name (`path.name`) does not.
PATH_NAMES = {"path", "searched", "candidate", "full_path"}
FILE_NAME_PARTS = {"name", "stem", "suffix"}


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.message}"


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def _is_call_to(node: ast.AST, name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return (isinstance(func, ast.Name) and func.id == name) or (
        isinstance(func, ast.Attribute) and func.attr == name
    )


def _names_in(node: ast.AST) -> set[str]:
    return {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}


def _formatted_names(text: ast.JoinedStr) -> set[str]:
    """The variables an f-string prints, including through str()/repr()."""
    names: set[str] = set()
    for part in text.values:
        if isinstance(part, ast.FormattedValue):
            names |= _names_in(part.value)
    return names


def _prints_a_path(text: ast.JoinedStr) -> bool:
    for part in text.values:
        if not isinstance(part, ast.FormattedValue):
            continue
        value = part.value
        # str(path), repr(path), os.fspath(path) print the same thing.
        while isinstance(value, ast.Call) and len(value.args) == 1:
            value = value.args[0]
        if isinstance(value, ast.Name) and value.id in PATH_NAMES:
            return True
        if (
            isinstance(value, ast.Attribute)
            and value.attr not in FILE_NAME_PARTS
            and isinstance(value.value, ast.Name)
            and value.value.id in PATH_NAMES
        ):
            return True
    return False


def _http_exceptions(body: list[ast.stmt]) -> list[ast.Call]:
    return [
        node for statement in body for node in ast.walk(statement) if _is_call_to(node, "HTTPException")
    ]


def check_route_module(source: str, path: str) -> list[Violation]:
    """Exception text stays out of responses, and every 500 is logged."""
    tree = ast.parse(source)
    found: list[Violation] = []
    has_logger = any(
        isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "LOGGER" for target in node.targets)
        and _is_call_to(node.value, "getLogger")
        for node in tree.body
    )
    for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)):
        caught = handler.name
        for call in _http_exceptions(handler.body):
            detail = _keyword(call, "detail")
            if caught and isinstance(detail, ast.JoinedStr) and caught in _formatted_names(detail):
                found.append(Violation(
                    path, call.lineno, "exception-in-detail",
                    f"the response detail prints the caught exception `{caught}`; say what failed, "
                    "and log the exception instead",
                ))
            status = _keyword(call, "status_code")
            if isinstance(status, ast.Constant) and status.value == 500:
                logged = any(
                    _is_call_to(node, "exception")
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "LOGGER"
                    and node.lineno <= call.lineno
                    for statement in handler.body
                    for node in ast.walk(statement)
                )
                if not logged:
                    found.append(Violation(
                        path, call.lineno, "unlogged-500",
                        "a 500 is answered without LOGGER.exception(...) in the same handler, so the "
                        "only record of why is the generic message the user saw",
                    ))
                elif not has_logger:
                    found.append(Violation(
                        path, call.lineno, "unlogged-500", "the module has no LOGGER = logging.getLogger(__name__)",
                    ))
    return found


def check_service_module(source: str, path: str) -> list[Violation]:
    """User-facing ValueErrors do not print a filesystem location."""
    found: list[Violation] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Raise) and node.exc is not None and _is_call_to(node.exc, "ValueError")):
            continue
        for argument in node.exc.args:  # type: ignore[union-attr]
            if isinstance(argument, ast.JoinedStr) and _prints_a_path(argument):
                found.append(Violation(
                    path, node.lineno, "path-in-message",
                    "a ValueError message prints a filesystem path; ValueErrors reach the user as a 400",
                ))
    return found


def violations(root: Path = ROOT) -> list[Violation]:
    found: list[Violation] = []
    for path in sorted((root / "backend" / "app" / "api").glob("routes_*.py")):
        found += check_route_module(path.read_text(encoding="utf-8"), str(path.relative_to(root)))
    for path in sorted((root / "backend" / "app" / "services").glob("*.py")):
        found += check_service_module(path.read_text(encoding="utf-8"), str(path.relative_to(root)))
    return found


if __name__ == "__main__":
    problems = violations()
    for problem in problems:
        print(problem)
    sys.exit(1 if problems else 0)
