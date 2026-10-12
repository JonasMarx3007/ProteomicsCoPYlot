"""Build the public, offline architecture map using versioned source only.

No application imports, Graphify installation, local database or network access
are needed. Python links come from AST imports/calls; frontend links are static
API-path matches propagated through named imports, not runtime observations.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "frontend/src/lib/generated/openapi.json"
TEMPLATE = "tools/architecture_map.html"
METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def read_sources(root: Path) -> dict[str, str]:
    tracked = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "-z"], text=True,
    ).split("\0")
    sources = {}
    for name in sorted(set(tracked)):
        eligible = (
            name.startswith(("backend/app/", "proteomicscopylot/")) and name.endswith(".py")
            or name.startswith("frontend/src/") and name.endswith((".ts", ".tsx"))
            and "/generated/" not in name
            or name in {SCHEMA, TEMPLATE}
        )
        if not eligible:
            continue
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            raise ValueError(f"Source must stay inside the checkout: {name}")
        sources[name] = path.read_text(encoding="utf-8")
    return sources


def module_name(path: str) -> str:
    name = path.removeprefix("backend/").removesuffix(".py").replace("/", ".")
    return name.removesuffix(".__init__")


def python_imports(tree, modules):
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                module = node.module or ""
                target = modules.get(module + "." + alias.name) or modules.get(module)
                if target:
                    aliases[alias.asname or alias.name] = (target, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in modules:
                    aliases[alias.asname or alias.name] = (modules[alias.name], "")
    return aliases


def attribute_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return attribute_name(node.value) + "." + node.attr
    return ""


def service_calls(function, tree, aliases):
    functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    pending, visited, calls = [function], set(), set()
    while pending:
        current = pending.pop()
        if current.name in visited:
            continue
        visited.add(current.name)
        for node in ast.walk(current):
            if not isinstance(node, ast.Call):
                continue
            name = attribute_name(node.func)
            if name in functions:
                pending.append(functions[name])
            base, _, member = name.partition(".")
            if base in aliases:
                path, symbol = aliases[base]
                if path.startswith(("backend/app/services/", "proteomicscopylot/")):
                    calls.add((path, member or symbol))
    return sorted(calls)


def routes_from_sources(sources, trees, modules):
    published = {(method.upper(), path) for path, operations in json.loads(sources[SCHEMA])["paths"].items()
                 for method in operations if method in METHODS}
    routes = {}
    for path, tree in trees.items():
        if not (path.startswith("backend/app/api/") or path == "backend/app/main.py"):
            continue
        prefix = "/api/plots" if Path(path).name.startswith("plots_") else ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and attribute_name(node.func) == "APIRouter":
                prefix = next((k.value.value for k in node.keywords if k.arg == "prefix"
                               and isinstance(k.value, ast.Constant)), prefix)
        aliases = python_imports(tree, modules)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr in METHODS and decorator.args
                        and isinstance(decorator.args[0], ast.Constant)):
                    continue
                key = decorator.func.attr.upper(), prefix + decorator.args[0].value
                if key in published:
                    routes[key] = {"group": "api:" + key[1].split("/")[2], "method": key[0],
                                   "path": key[1], "handler": node.name, "where": f"{path}:{node.lineno}",
                                   "targets": service_calls(node, tree, aliases), "pages": []}
    missing = published - routes.keys()
    if missing:
        raise ValueError(f"Published routes missing from the map: {sorted(missing)}")
    return routes


def frontend_links(sources, routes):
    """Infer named-wrapper usage. Ambiguous path templates remain candidate links."""
    reach = defaultdict(set)
    imports = defaultdict(list)
    pages = {}
    export = re.compile(r"export\s+(?:async\s+)?function\s+(\w+)\s*\(")
    imported = re.compile(r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]", re.S)
    literal = re.compile(r"[\"'`](/api/[^\"'`\s]*)")
    for path, text in sources.items():
        if not path.startswith("frontend/src/") or path == SCHEMA:
            continue
        if path.startswith("frontend/src/features/"):
            pages[path] = path.split("/")[3]
        elif path.startswith("frontend/src/components/") or path == "frontend/src/App.tsx":
            pages[path] = "app shell & shared components"
        starts = [(m.start(), m.group(1)) for m in export.finditer(text)]
        for match in literal.finditer(text):
            raw = match.group(1).split("?")[0]
            pattern = "^" + re.escape(raw) + "$"
            pattern = re.sub(r"\\\$\\\{.*?\\\}", "[^/]+", pattern)
            owner = next((name for start, name in reversed(starts) if start <= match.start()), "")
            for key in routes:
                candidate = re.sub(r"\{[^}]+\}", "X", key[1])
                if re.fullmatch(pattern, candidate):
                    reach[(path, owner)].add(key)
        for match in imported.finditer(text):
            relative = match.group(2)
            if not relative.startswith("."):
                continue
            parts = list(Path(path).parent.parts)
            for part in relative.split("/"):
                if part == "..":
                    parts.pop()
                elif part != ".":
                    parts.append(part)
            stem = "/".join(parts)
            target = next((p for p in (stem + ".ts", stem + ".tsx", stem + "/index.ts") if p in sources), None)
            if target:
                imports[path].extend((target, item.strip().removeprefix("type ").split(" as ")[0])
                                     for item in match.group(1).split(",") if item.strip())
    page_routes = defaultdict(set)
    for path, page in pages.items():
        for (owner_path, _), endpoints in reach.items():
            if owner_path == path:
                page_routes[page].update(endpoints)
        for target, symbol in imports[path]:
            page_routes[page].update(reach[(target, symbol)])
    return pages, page_routes


def build_model(sources):
    trees = {path: ast.parse(text) for path, text in sources.items() if path.endswith(".py")}
    modules = {module_name(path): path for path in trees}
    routes = routes_from_sources(sources, trees, modules)
    pages, page_routes = frontend_links(sources, routes)
    dependencies = {path: {target for target, _ in python_imports(tree, modules).values() if target != path}
                    for path, tree in trees.items()}
    direct = {path for route in routes.values() for path, _ in route["targets"]}
    core = {target for path in direct for target in dependencies[path]
            if target.startswith(("backend/app/services/", "proteomicscopylot/"))} - direct
    node_id = lambda path: ("svc:" if path in direct else "core:") + path
    nodes, links = [], Counter()
    for page in sorted(set(pages.values())):
        nodes.append({"id": "page:" + page, "col": 0, "label": page,
                      "files": sorted(p for p, group in pages.items() if group == page)})
        for key in sorted(page_routes[page]):
            links[("page:" + page, routes[key]["group"])] += 1
            routes[key]["pages"].append(page)
    for group in sorted({r["group"] for r in routes.values()}):
        nodes.append({"id": group, "col": 1, "label": "/api/" + group[4:]})
    for path in sorted(direct | core):
        nodes.append({"id": node_id(path), "col": 2 if path in direct else 3, "label": Path(path).stem,
                      "file": path, "usedBy": sum(path in deps for deps in dependencies.values())})
    for route in routes.values():
        targets = route.pop("targets")
        route["calls"] = sorted({Path(path).stem + "." + symbol for path, symbol in targets})
        route["services"] = sorted({node_id(path) for path, _ in targets})
        for path, _ in targets:
            links[(route["group"], node_id(path))] += 1
    for path in sorted(direct):
        for target in sorted(dependencies[path] & core):
            links[(node_id(path), node_id(target))] += 1
    fingerprint = hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()[:12]
    return {"fingerprint": fingerprint, "counts": {"files": len(sources)}, "nodes": nodes,
            "links": [{"s": a, "t": b, "n": n} for (a, b), n in sorted(links.items())],
            "endpoints": [routes[key] for key in sorted(routes)]}


def render(sources):
    model = build_model(sources)
    # Escape HTML-significant characters even inside a JSON script element.
    data = json.dumps(model, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return sources[TEMPLATE].replace("__MODEL__", data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/architecture/index.html")
    args = parser.parse_args()
    output = render(read_sources(ROOT))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8", newline="\n")
    print(f"Wrote {args.output.name} ({len(output.encode('utf-8')):,} bytes).")


if __name__ == "__main__":
    main()
