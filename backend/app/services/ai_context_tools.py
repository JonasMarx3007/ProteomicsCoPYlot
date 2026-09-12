from __future__ import annotations

import inspect
import re
from typing import Any

import pandas as pd

from app.schemas.chat import ModelContextTier, ModuleContextResponse
from app.services import ai_functions
from app.services.dataset_store import get_all_current_datasets
from app.services import table_functions as _table_functions
from app.services.runtime_cache import cached_call

_MODULE_SPECIFIC_AI_FUNCTIONS: dict[str, list[str]] = {
    "peptide.rtPlot": ["peptide_rt_plot"],
    "peptide.modification": ["peptide_modification_plot"],
    "peptide.missedCleavage": ["peptide_missed_cleavage_plot"],
    "peptide.sequenceCoverage": ["peptide_sequence_coverage"],
    "completeness.missingPlot": ["completeness_missing_value_plot"],
    "completeness.heatmap": ["completeness_missing_value_heatmap"],
    "completeness.tables": ["completeness_missing_value_tables"],
    "stats.volcano": ["stats_volcano_plot"],
    "stats.ora": ["stats_ora_plot"],
    "stats.pathwayHeatmap": ["stats_pathway_heatmap_plot"],
    "singleProtein.boxplot": ["single_protein_boxplot"],
    "singleProtein.lineplot": ["single_protein_lineplot"],
    "singleProtein.heatmap": ["single_protein_phosphosite_heatmap"],
    "comparison.pearson": ["comparison_pearson_correlation"],
    "comparison.venn": ["comparison_venn_diagram"],
    "phospho.phosphositePlot": ["phospho_phosphosite_plot"],
    "phospho.coverage": ["phospho_phosphosite_coverage_plot"],
    "phospho.distribution": ["phospho_phosphosite_distribution_plot"],
    "phospho.sty": ["phospho_sty_plot"],
    "phospho.phosprotRegulation": ["phospho_phosprot_regulation_plot"],
    "qc.coverage": ["qc_coverage_plot"],
    "qc.histogram": ["qc_histogram_intensity"],
    "qc.boxplot": ["qc_boxplot_intensity"],
    "qc.cv": ["qc_cov_plot"],
    "qc.pca": ["qc_pca_plot"],
    "qc.abundance": ["qc_abundance_plot"],
    "qc.correlation": ["qc_correlation_plot"],
}

_WORKFLOW_ENTITY_LABELS: dict[str, tuple[str, str]] = {
    "protein": ("protein", "proteins"),
    "phosphosite": ("phosphosite", "phosphosites"),
    "phosphoprotein": ("phosphoprotein", "phosphoproteins"),
    "peptide": ("peptide", "peptides"),
}

_CONTEXT_TIER_REPEAT_LIMITS: dict[str, int | None] = {
    "compact": 2,
    "standard": 6,
    "extended": None,
}


def _humanize_segment(segment: str) -> str:
    text = str(segment or "").strip()
    if not text:
        return ""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return " ".join(word.capitalize() for word in text.split(" "))


def _module_title_from_key(module_key: str) -> str:
    normalized = str(module_key or "").strip()
    if not normalized:
        return "Unknown Module"
    parts = [_humanize_segment(part) for part in normalized.split(".") if str(part).strip()]
    if not parts:
        return "Unknown Module"
    return " / ".join(parts)


def _workflow_terms(workflow: str) -> tuple[str, str]:
    return _WORKFLOW_ENTITY_LABELS.get(workflow, _WORKFLOW_ENTITY_LABELS["protein"])


def _normalize_context_tier(value: str | None) -> ModelContextTier:
    key = str(value or "").strip().lower()
    if key in {"compact", "standard", "extended"}:
        return key  # type: ignore[return-value]
    return "compact"


def _stage_context_text(
    text: str,
    *,
    context_tier: ModelContextTier,
    workflow: str,
    function_name: str,
) -> list[str]:
    raw_lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not raw_lines:
        return []
    repeat_limit = _CONTEXT_TIER_REPEAT_LIMITS[context_tier]
    workflow_kind = {
        "protein": "protein",
        "phosphosite": "phospho",
        "phosphoprotein": "phosprot",
        "peptide": "peptide",
    }.get(workflow, "protein")
    counts: dict[str, int] = {}
    staged: list[str] = []
    for line in raw_lines:
        label = line.split("|", 1)[0].strip().lower()
        if function_name == "general_proteomics_context" and label == "project_dataset":
            is_active_workflow = f"kind={workflow_kind}" in line.lower()
            if context_tier == "compact" and not is_active_workflow:
                continue
            if context_tier == "standard" and "status=not_loaded" in line.lower() and not is_active_workflow:
                continue
        if context_tier == "compact" and label.endswith(
            ("_quality_guidance", "_usage", "_color_rule", "_functions")
        ):
            continue
        repeat_bucket = label
        if label in {"abundance_top_entity", "volcano_term"}:
            subgroup = re.search(r"\|(condition|group)=([^|]+)", line, re.I)
            if subgroup:
                repeat_bucket = f"{label}|{subgroup.group(1).lower()}={subgroup.group(2).lower()}"
        count = counts.get(repeat_bucket, 0)
        if repeat_limit is not None and count >= repeat_limit:
            continue
        counts[repeat_bucket] = count + 1
        staged.append(line)
    return staged


def _readable_context_line(line: str) -> str:
    text = str(line or "").strip()
    if not text or "|" not in text:
        return text
    parts = [part.strip() for part in text.split("|") if part.strip()]
    if not parts:
        return ""
    raw_label = parts[0]
    if raw_label.endswith("_answer_summary"):
        label = "Direct answer evidence"
    elif raw_label.endswith(("_response_rule", "_quality_rule", "_inference_rule", "_evidence_limit")):
        label = "Interpretation constraint"
    else:
        label = _humanize_segment(raw_label)
    fields: list[str] = []
    for part in parts[1:]:
        if "=" not in part:
            fields.append(_humanize_segment(part).lower())
            continue
        key, value = part.split("=", 1)
        readable_key = re.sub(r"[_-]+", " ", key).strip().lower()
        readable_value = value.strip()
        preserve_identifier = any(
            token in readable_key
            for token in ("identifier", "term", "sample", "pair", "filename", "column", "path", "model")
        ) or "_HUMAN" in readable_value.upper()
        if not preserve_identifier:
            readable_value = readable_value.replace("_", " ")
        fields.append(f"{readable_key}: {readable_value}")
    if not fields:
        return f"{label}."
    return f"{label}: {'; '.join(fields)}."


def _normalize_workflow_hint(workflow_hint: str | None) -> str | None:
    key = str(workflow_hint or "").strip().lower()
    if not key:
        return None
    if key in _WORKFLOW_ENTITY_LABELS:
        return key
    if "peptide" in key:
        return "peptide"
    if "phosphosite" in key or key == "phospho":
        return "phosphosite"
    if "phosprot" in key or "phosphoprotein" in key:
        return "phosphoprotein"
    if "protein" in key:
        return "protein"
    return None


def _normalize_mode_hint(mode_hint: str | None) -> str | None:
    text = str(mode_hint or "").strip()
    if not text:
        return None
    key = text.lower()
    if key == "single":
        return "Single"
    if key == "mean":
        return "Mean"
    return text


def _context_prompt(
    module_title: str,
    function_payloads: list[dict[str, Any]],
    *,
    workflow: str,
    mode: str | None,
    context_tier: ModelContextTier,
) -> tuple[str, str]:
    function_names = [str(item.get("function", "")).strip() for item in function_payloads]
    function_names = [name for name in function_names if name]
    functions_line = ", ".join(function_names) if function_names else "none"
    _, entity_plural = _workflow_terms(workflow)
    context_texts: list[tuple[str, str]] = []
    for payload in function_payloads:
        data = payload.get("data")
        if isinstance(data, dict):
            text = str(data.get("text", "")).strip()
            if text:
                context_texts.append((str(payload.get("function", "")), text))
    lines = [
        f"Current analysis module: {module_title}.",
        f"Workflow scope for this module context: {workflow} ({entity_plural}).",
        f"Use {entity_plural} terminology for this module.",
        (
            f"Evidence detail profile: {context_tier}. "
            "This profile changes the amount of supplied evidence, not the scientific calculations."
        ),
    ]
    if mode:
        lines.append(f"Active parameters: {mode}" if mode.lstrip().startswith("{")
                     else _readable_context_line(f"active_parameters|{mode}"))
    if context_texts:
        lines.append("Calculated module evidence and interpretation constraints:")
        for function_name, context_text in context_texts:
            staged_lines = _stage_context_text(
                context_text,
                context_tier=context_tier,
                workflow=workflow,
                function_name=function_name,
            )
            lines.extend(_readable_context_line(line) for line in staged_lines)
    return "\n".join(lines), " / ".join(function_names) if function_names else "no_functions"


def _infer_workflow_scope(module_key: str, workflow_hint: str | None = None) -> str:
    hint = _normalize_workflow_hint(workflow_hint)
    if hint:
        return hint

    key = str(module_key or "").strip().lower()
    if key == "qc.coverage":
        try:
            datasets = get_all_current_datasets()
        except Exception:
            datasets = {}
        candidates: list[tuple[str, int, int]] = []

        def _condition_count(frame: pd.DataFrame) -> int:
            if frame.empty or "Condition" not in frame.columns:
                return 0
            values = frame["Condition"].astype(str).str.strip()
            values = values[values != ""]
            return int(values.nunique())

        for kind, workflow in (
            ("protein", "protein"),
            ("phospho", "phosphosite"),
            ("phosprot", "phosphoprotein"),
        ):
            if datasets.get(kind) is None:
                continue
            try:
                table = _table_functions.qc_coverage_table(kind, summary=False).copy()
            except Exception:
                continue
            if table.empty or "Sample" not in table.columns:
                continue
            table["Sample"] = table["Sample"].astype(str)
            mask = ~table["Sample"].str.lower().str.startswith("all sample")
            filtered = table.loc[mask].copy()
            sample_count = int(filtered["Sample"].nunique())
            if sample_count <= 0:
                continue
            filtered["Condition"] = filtered["Sample"].map(
                lambda sample: str(sample).split("_", 1)[0] if "_" in str(sample) else str(sample)
            )
            condition_count = _condition_count(filtered)
            candidates.append((workflow, sample_count, condition_count))

        if candidates:
            candidates.sort(key=lambda item: (item[1], item[2]), reverse=True)
            return candidates[0][0]
        if datasets.get("peptide") is not None:
            return "peptide"
    if key.startswith("peptide.") or "peptide" in key:
        return "peptide"
    if "phosprot" in key or "phosphoprotein" in key:
        return "phosphoprotein"
    if key.startswith("phospho.") or "phosphosite" in key:
        return "phosphosite"
    return "protein"


def _function_payload(
    function_name: str,
    workflow: str,
    mode: str | None,
    context_tier: ModelContextTier,
) -> tuple[dict[str, Any] | None, str | None]:
    source_func = getattr(ai_functions, function_name, None)
    if not callable(source_func):
        return None, f"AI function '{function_name}' is not available."
    kwargs: dict[str, Any] = {}
    try:
        signature = inspect.signature(source_func)
        if "workflow" in signature.parameters:
            kwargs["workflow"] = workflow
        if "mode" in signature.parameters and mode is not None:
            kwargs["mode"] = mode
        if "context_tier" in signature.parameters:
            kwargs["context_tier"] = context_tier
    except Exception:
        kwargs = {}
    try:
        payload = source_func(**kwargs)
    except Exception as exc:
        return None, f"{function_name}: {exc}"
    if isinstance(payload, dict):
        return payload, None
    return {"function": function_name, "data": payload}, None


def build_module_context(
    module_key: str,
    workflow_hint: str | None = None,
    mode_hint: str | None = None,
    context_tier: str | None = None,
) -> ModuleContextResponse:
    normalized_key = str(module_key or "").strip() or "unknown"
    workflow = _infer_workflow_scope(normalized_key, workflow_hint)
    mode = _normalize_mode_hint(mode_hint)
    tier = _normalize_context_tier(context_tier)
    return cached_call(
        "ai-module-context",
        (normalized_key, workflow, mode, tier),
        lambda: _build_module_context(normalized_key, workflow, mode, tier),
    )


def _build_module_context(
    normalized_key: str, workflow: str, mode: str | None, tier: ModelContextTier,
) -> ModuleContextResponse:
    module_title = _module_title_from_key(normalized_key)
    function_names = [
        "general_proteomics_context",
        *_MODULE_SPECIFIC_AI_FUNCTIONS.get(normalized_key, []),
    ]

    warnings: list[str] = []
    function_payloads: list[dict[str, Any]] = []
    for function_name in function_names:
        payload, warning = _function_payload(function_name, workflow, mode, tier)
        if warning:
            warnings.append(warning)
            continue
        if payload is not None:
            function_payloads.append(payload)

    context_prompt, context_summary = _context_prompt(
        module_title=module_title,
        function_payloads=function_payloads,
        workflow=workflow,
        mode=mode,
        context_tier=tier,
    )
    return ModuleContextResponse(
        moduleKey=normalized_key,
        moduleTitle=module_title,
        manualTitle=None,
        manualPath=None,
        contextPrompt=context_prompt,
        contextSummary=context_summary,
        contextTier=tier,
        contextData={"functions": function_payloads, "contextTier": tier},
        warnings=warnings,
    )
