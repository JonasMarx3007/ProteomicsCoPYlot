from __future__ import annotations

import inspect
import json
import time
from typing import Any

from app.schemas.annotation import AnnotationKind
from app.schemas.chat import ModuleContextResponse
from app.services import ai_functions
from app.services.ai_manual import manual_entry_for_module
from app.services.comparison_tools import comparison_options
from app.services.dataset_store import get_all_current_datasets, get_current_dataset
from app.services.single_protein_tools import single_protein_options

_ALL_KINDS: list[AnnotationKind] = ["protein", "phospho", "phosprot"]
_CONTEXT_CACHE_TTL_SECONDS = 30.0
_CONTEXT_CACHE: dict[str, tuple[float, ModuleContextResponse]] = {}


def _available_kinds() -> list[AnnotationKind]:
    available: list[AnnotationKind] = []
    for kind in _ALL_KINDS:
        try:
            current = get_current_dataset(kind)
        except Exception:
            current = None
        if current is not None:
            available.append(kind)
    return available


def _pick_kind(preferred_kinds: list[str]) -> AnnotationKind:
    available = _available_kinds()
    preferred = [str(kind).strip() for kind in preferred_kinds if str(kind).strip()]
    for kind in preferred:
        if kind in available:
            return kind  # type: ignore[return-value]
    if available:
        return available[0]
    return "protein"


def _single_protein_defaults(kind: AnnotationKind, tab: str) -> tuple[str, list[str]]:
    try:
        options = single_protein_options(kind, tab=tab, identifier="workflow")
    except Exception:
        return "", []
    proteins = [str(value) for value in options.get("proteins", []) if str(value).strip()]
    conditions = [str(value) for value in options.get("conditions", []) if str(value).strip()]
    protein = proteins[0] if proteins else ""
    if len(conditions) >= 2:
        return protein, [conditions[0], conditions[1]]
    return protein, conditions


def _comparison_defaults(kind: AnnotationKind) -> dict[str, str]:
    try:
        options = comparison_options(kind)
    except Exception:
        return {}
    samples = [str(value) for value in options.get("samples", []) if str(value).strip()]
    conditions = [str(value) for value in options.get("conditions", []) if str(value).strip()]
    defaults: dict[str, str] = {}
    if len(samples) >= 2:
        defaults["sample1"] = samples[0]
        defaults["sample2"] = samples[1]
        defaults["first"] = samples[0]
        defaults["second"] = samples[1]
    if len(conditions) >= 2:
        defaults["condition1"] = conditions[0]
        defaults["condition2"] = conditions[1]
    return defaults


def _resolve_ai_call_args(
    func_name: str,
    source_func: Any,
    preferred_kinds: list[str],
    argument_defaults: dict[str, Any],
) -> dict[str, Any]:
    signature = inspect.signature(source_func)
    resolved: dict[str, Any] = {}
    required: list[str] = []
    for name, parameter in signature.parameters.items():
        if name in argument_defaults:
            resolved[name] = argument_defaults[name]
            continue
        if parameter.default is not inspect._empty:
            resolved[name] = parameter.default
            continue
        required.append(name)

    selected_kind = _pick_kind(preferred_kinds)
    if "kind" in signature.parameters:
        resolved["kind"] = resolved.get("kind", selected_kind)

    if func_name in {"single_protein_boxplot_plot", "single_protein_lineplot_plot"}:
        protein, conditions = _single_protein_defaults(selected_kind, tab="boxplot" if "boxplot" in func_name else "lineplot")
        if "protein" in signature.parameters:
            resolved["protein"] = resolved.get("protein", protein)
        if "proteins" in signature.parameters:
            resolved["proteins"] = resolved.get("proteins", [protein] if protein else [])
        if "conditions" in signature.parameters:
            resolved["conditions"] = resolved.get("conditions", conditions)
    elif func_name == "single_protein_heatmap_plot":
        heatmap_kind = _pick_kind(["phospho", *preferred_kinds])
        resolved["kind"] = heatmap_kind
        protein, conditions = _single_protein_defaults(heatmap_kind, tab="heatmap")
        if "protein" in signature.parameters:
            resolved["protein"] = resolved.get("protein", protein)
        if "conditions" in signature.parameters:
            resolved["conditions"] = resolved.get("conditions", conditions)
    elif func_name in {"comparison_pearson_png", "comparison_venn_png"}:
        defaults = _comparison_defaults(selected_kind)
        for key, value in defaults.items():
            if key in signature.parameters and key not in resolved:
                resolved[key] = value

    for name in required:
        if name in resolved:
            continue
        if name == "kind":
            resolved[name] = selected_kind
            continue
        if name == "protein":
            resolved[name] = ""
            continue
        if name == "proteins":
            resolved[name] = []
            continue
        if name == "conditions":
            resolved[name] = []
            continue
        if name in {"sample1", "sample2", "condition1", "condition2", "first", "second"}:
            resolved[name] = ""
            continue
        raise ValueError(f"Could not resolve required argument '{name}' for {func_name}.")

    return resolved


def _json_snippet(value: Any, max_chars: int = 12000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except Exception:
        text = str(value)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]} ... [truncated {len(text) - max_chars} chars]"


def _compact_data_shape(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        dtype = str(data.get("type", "dict"))
        out: dict[str, Any] = {"type": dtype}
        if dtype == "table":
            out["rows"] = data.get("rows")
            out["columns"] = data.get("columns")
            out["truncated"] = data.get("truncated")
            return out
        if dtype in {"ndarray", "sequence", "binary"}:
            for key in ("shape", "length", "byteLength", "truncated"):
                if key in data:
                    out[key] = data.get(key)
            return out
        out["keys"] = list(data.keys())[:20]
        return out
    if isinstance(data, list):
        return {"type": "list", "length": len(data)}
    return {"type": type(data).__name__}


def _compact_function_payload(payload: dict[str, Any]) -> dict[str, Any]:
    function_name = str(payload.get("function", "")).strip()
    summary = str(payload.get("summary", "")).strip()
    data = payload.get("data")
    return {
        "function": function_name,
        "summary": summary,
        "dataShape": _compact_data_shape(data),
    }


def _domain_scope_for_module(module_key: str, preferred_kinds: list[str]) -> str:
    key = str(module_key or "").strip().lower()
    preferred = [str(item or "").strip().lower() for item in preferred_kinds if str(item or "").strip()]

    if key.startswith("peptide.") or "peptide" in key:
        return (
            "Peptide pipeline scope: discuss peptide-level results only. "
            "Do not switch to protein/phosphosite/phosphoprotein terminology unless explicitly requested."
        )
    if "phosprot" in key:
        return (
            "Phosphoprotein workflow scope: discuss phosphoprotein-level results only. "
            "Do not describe phosphosite or peptide-level findings unless explicitly requested."
        )
    if key.startswith("phospho."):
        return (
            "Phospho workflow scope: discuss phosphorylation-site/phosphosite results only. "
            "Do not switch to peptide-only or phosphoprotein-only wording unless explicitly requested."
        )

    if preferred and all(item == "phosprot" for item in preferred):
        return (
            "Phosphoprotein workflow scope: discuss phosphoprotein-level results only. "
            "Do not describe phosphosite or peptide-level findings unless explicitly requested."
        )
    if preferred and all(item == "phospho" for item in preferred):
        return (
            "Phospho workflow scope: discuss phosphorylation-site/phosphosite results only. "
            "Do not switch to peptide-only or phosphoprotein-only wording unless explicitly requested."
        )
    if preferred and all(item == "protein" for item in preferred):
        return (
            "Proteomics workflow scope: discuss protein-level results only. "
            "Do not switch to phosphosite/peptide/phosphoprotein wording unless explicitly requested."
        )

    return (
        "Proteomics workflow scope: discuss protein-level results by default. "
        "Only use phosphosite/peptide/phosphoprotein wording when the active module clearly indicates it."
    )


def _context_prompt(
    module_title: str,
    module_key: str,
    domain_scope: str,
    manual_title: str | None,
    manual_path: str | None,
    manual_digest: str,
    function_payloads: list[dict[str, Any]],
    warnings: list[str],
) -> tuple[str, str]:
    lines: list[str] = []
    lines.append(f"Current analysis module: {module_title}.")
    lines.append("Domain context: proteomics mass-spectrometry analysis (not DNA/RNA sequencing).")
    lines.append(domain_scope)
    if manual_title or manual_path:
        title = manual_title or "Module Manual"
        path = manual_path or ""
        lines.append(f"Manual reference: {title} {path}".strip())
    if manual_digest:
        lines.append(f"Manual guidance: {manual_digest}")

    summary_items: list[str] = []
    for payload in function_payloads:
        function_name = str(payload.get("function", "")).strip()
        summary = str(payload.get("summary", "")).strip()
        if summary:
            summary_items.append(f"{function_name}: {summary}")
            lines.append(f"{function_name} summary: {summary}")
    if warnings:
        lines.append("Warnings: " + " | ".join(str(item) for item in warnings))

    context_summary = " ; ".join(summary_items) if summary_items else "No module AI-function payload available."
    context_prompt = "\n".join(lines)
    return context_prompt, context_summary


def _dataset_snapshot_token() -> str:
    try:
        all_data = get_all_current_datasets()
    except Exception:
        return "snapshot:unknown"
    parts: list[str] = []
    for kind in sorted(all_data.keys()):
        item = all_data.get(kind)
        if item is None:
            parts.append(f"{kind}:none")
            continue
        filename = str(getattr(item, "filename", "") or "")
        rows = str(getattr(item, "rows", "") or "")
        cols = str(getattr(item, "columns", "") or "")
        parts.append(f"{kind}:{filename}:{rows}:{cols}")
    return "|".join(parts)


def _context_cache_key(module_key: str) -> str:
    return f"{module_key}::{_dataset_snapshot_token()}"


def _get_cached_context(cache_key: str) -> ModuleContextResponse | None:
    hit = _CONTEXT_CACHE.get(cache_key)
    if hit is None:
        return None
    ts, payload = hit
    if (time.time() - ts) > _CONTEXT_CACHE_TTL_SECONDS:
        _CONTEXT_CACHE.pop(cache_key, None)
        return None
    return payload


def _store_cached_context(cache_key: str, payload: ModuleContextResponse) -> None:
    _CONTEXT_CACHE[cache_key] = (time.time(), payload)


def build_module_context(module_key: str) -> ModuleContextResponse:
    cache_key = _context_cache_key(module_key)
    cached = _get_cached_context(cache_key)
    if cached is not None:
        return cached

    entry = manual_entry_for_module(module_key)
    warnings: list[str] = []
    function_payloads: list[dict[str, Any]] = []

    for function_name in entry.ai_functions:
        source_func = getattr(ai_functions, function_name, None)
        if not callable(source_func):
            warnings.append(f"AI function '{function_name}' is not available.")
            continue
        try:
            kwargs = _resolve_ai_call_args(
                function_name,
                source_func,
                preferred_kinds=entry.preferred_kinds,
                argument_defaults=entry.argument_defaults,
            )
            payload = source_func(**kwargs)
            function_payloads.append(payload if isinstance(payload, dict) else {"function": function_name, "data": payload})
        except Exception as exc:
            warnings.append(f"{function_name}: {exc}")

    domain_scope = _domain_scope_for_module(entry.module_key, entry.preferred_kinds)
    context_prompt, context_summary = _context_prompt(
        module_title=entry.module_title,
        module_key=entry.module_key,
        domain_scope=domain_scope,
        manual_title=entry.manual_title,
        manual_path=entry.manual_path,
        manual_digest=entry.manual_digest,
        function_payloads=function_payloads,
        warnings=warnings,
    )
    compact_payloads = [_compact_function_payload(payload) for payload in function_payloads]
    response = ModuleContextResponse(
        moduleKey=entry.module_key,
        moduleTitle=entry.module_title,
        manualTitle=entry.manual_title,
        manualPath=entry.manual_path,
        contextPrompt=context_prompt,
        contextSummary=context_summary,
        contextData={"functions": compact_payloads},
        warnings=warnings,
    )
    _store_cached_context(cache_key, response)
    return response
