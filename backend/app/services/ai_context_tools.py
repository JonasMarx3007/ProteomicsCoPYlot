from __future__ import annotations

import inspect
from typing import Any
from app.schemas.assistant import ContextMode
from app.services import ai_functions

_MODULE_SPECIFIC_AI_FUNCTIONS: dict[str, list[str]] = {
    "data.distribution": ["data_distribution_summary"],
    "stats.simulation": ["stats_simulation_plot"],
    "phospho.ksea": ["phospho_ksea_export"],
    "analysis.canvas": ["analysis_canvas_context"],
    "peptide.rtPlot": ["peptide_rt_plot"],
    "peptide.modification": ["peptide_modification_plot"],
    "peptide.missedCleavage": ["peptide_missed_cleavage_plot"],
    "peptide.sequenceCoverage": ["peptide_sequence_coverage"],
    "completeness.missingPlot": ["completeness_missing_value_plot"],
    "completeness.heatmap": ["completeness_missing_value_heatmap"],
    "completeness.tables": ["completeness_missing_value_tables"],
    "stats.volcano": ["stats_volcano_plot"],
    "stats.anova": ["stats_anova_plot"],
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


def _function_payload(
    function_name: str,
    workflow: str,
    mode: ContextMode | None,
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
    except Exception:
        kwargs = {}
    try:
        payload = source_func(**kwargs)
    except Exception as exc:
        return None, f"{function_name}: {exc}"
    if isinstance(payload, dict):
        return payload, None
    return {"function": function_name, "data": payload}, None
