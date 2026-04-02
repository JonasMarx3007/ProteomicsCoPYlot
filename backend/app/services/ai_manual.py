from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AiManualEntry:
    module_key: str
    module_title: str
    manual_title: str | None = None
    manual_path: str | None = None
    manual_digest: str = ""
    ai_functions: list[str] = field(default_factory=list)
    preferred_kinds: list[str] = field(default_factory=lambda: ["protein", "phospho", "phosprot"])
    argument_defaults: dict[str, Any] = field(default_factory=dict)


def _entry(
    module_key: str,
    module_title: str,
    *,
    manual_title: str | None = None,
    manual_path: str | None = None,
    manual_digest: str = "",
    ai_functions: list[str] | None = None,
    preferred_kinds: list[str] | None = None,
    argument_defaults: dict[str, Any] | None = None,
) -> AiManualEntry:
    return AiManualEntry(
        module_key=module_key,
        module_title=module_title,
        manual_title=manual_title,
        manual_path=manual_path,
        manual_digest=manual_digest,
        ai_functions=ai_functions or [],
        preferred_kinds=preferred_kinds or ["protein", "phospho", "phosprot"],
        argument_defaults=argument_defaults or {},
    )


AI_MANUAL: dict[str, AiManualEntry] = {
    "data.imputation": _entry(
        "data.imputation",
        "Data Imputation",
        ai_functions=["imputation_before_plot", "imputation_overall_fit_plot", "imputation_after_plot"],
        manual_digest="Review missing-value burden, imputation distribution shift, and fit quality before interpretation.",
    ),
    "data.distribution": _entry(
        "data.distribution",
        "Data Distribution",
        ai_functions=["distribution_qqnorm_plot"],
        manual_digest="Use QQ behavior and summary statistics to evaluate data-shape assumptions.",
    ),
    "data.verification": _entry(
        "data.verification",
        "Data Verification",
        manual_title="Data Information Manual",
        manual_path="/manuals/DataInfoManual.pdf",
        ai_functions=["verification_first_digit_plot", "verification_duplicate_pattern_plot"],
        manual_digest="Use first-digit and duplicate-frequency checks for plausibility and potential artifacts.",
    ),
    "completeness.missingPlot": _entry(
        "completeness.missingPlot",
        "Missing Value Plot",
        manual_title="Missing Value Plot Manual",
        manual_path="/manuals/MissingValuePlotManual.pdf",
        ai_functions=["completeness_missing_value_plot"],
        manual_digest="Focus on missing-value frequency profile across features and whether missingness is concentrated.",
    ),
    "completeness.heatmap": _entry(
        "completeness.heatmap",
        "Missing Value Heatmap",
        manual_title="Missing Value Heatmap Manual",
        manual_path="/manuals/MissingValueHeatmapManual.pdf",
        ai_functions=["completeness_missing_value_heatmap"],
        manual_digest="Inspect per-sample/per-feature missingness structure and clusters of problematic samples.",
    ),
    "completeness.tables": _entry(
        "completeness.tables",
        "Missing Value Tables",
        manual_title="Missing Value Tables Manual",
        manual_path="/manuals/MissingValueTablesManual.pdf",
        ai_functions=["completeness_tables"],
        manual_digest="Use outlier and summary tables to identify high-missingness samples and fragile features.",
    ),
    "qc.coverage": _entry(
        "qc.coverage",
        "Coverage Plot",
        manual_title="Coverage Plot Manual",
        manual_path="/manuals/CoveragePlotManual.pdf",
        ai_functions=["qc_coverage_plot"],
        manual_digest=(
            "Coverage plot quantifies data completeness per sample. "
            "For each sample, count missing values (NA), determine total features as dataframe rows, "
            "and compute detected features = total features - missing values. "
            "Bars show detected features per sample with condition colors and a red line marking total features. "
            "Summary mode shows mean per condition with individual sample points and SD error bars. "
            "For condition comparisons, report min/max/median detected features and interpret higher values as better completeness."
        ),
    ),
    "qc.histogram": _entry(
        "qc.histogram",
        "Histogram Intensity",
        manual_title="Histogram Intensity Manual",
        manual_path="/manuals/HistogramIntensityManual.pdf",
        ai_functions=["qc_intensity_histogram_plot"],
        manual_digest="Assess overall intensity distribution shape and shifts between samples/conditions.",
    ),
    "qc.boxplot": _entry(
        "qc.boxplot",
        "Boxplot Intensity",
        manual_title="Boxplot Intensity Manual",
        manual_path="/manuals/BoxplotIntensityManual.pdf",
        ai_functions=["qc_boxplot_plot"],
        manual_digest="Track median/IQR and outlier behavior to judge normalization and sample comparability.",
    ),
    "qc.cv": _entry(
        "qc.cv",
        "Coefficient of Variation Plot",
        manual_title="Coefficient of Variation Plot Manual",
        manual_path="/manuals/CoefficientofVariationPlotManual.pdf",
        ai_functions=["qc_cv_plot"],
        manual_digest="Lower CV indicates better replicate stability; compare CV distributions between conditions.",
    ),
    "qc.pca": _entry(
        "qc.pca",
        "Principal Component Analysis Plot",
        manual_title="Principal Component Analysis Plot Manual",
        manual_path="/manuals/PrincipalComponentAnalysisPlotManual.pdf",
        ai_functions=["qc_pca_plot"],
        manual_digest="Use component separation to evaluate condition structure, batch effects, and outliers.",
    ),
    "qc.abundance": _entry(
        "qc.abundance",
        "Abundance Plot",
        manual_title="Abundance Plot Manual",
        manual_path="/manuals/AbundancePlotManual.pdf",
        ai_functions=["qc_abundance_plot"],
        manual_digest="Inspect ranked abundance trends and condition-specific curve differences.",
    ),
    "qc.correlation": _entry(
        "qc.correlation",
        "Correlation Plot",
        manual_title="Correlation Plot Manual",
        manual_path="/manuals/CorrelationPlotManual.pdf",
        ai_functions=["qc_correlation_plot"],
        manual_digest="High within-condition and expected between-condition correlation supports data quality.",
    ),
    "singleProtein.boxplot": _entry(
        "singleProtein.boxplot",
        "Protein Boxplot",
        manual_title="Protein Boxplot Manual",
        manual_path="/manuals/ProteinBoxplotManual.pdf",
        ai_functions=["single_protein_boxplot_plot"],
        manual_digest="Interpret per-condition distribution of a selected feature and spread differences.",
        preferred_kinds=["protein", "phospho", "phosprot"],
    ),
    "singleProtein.lineplot": _entry(
        "singleProtein.lineplot",
        "Protein Lineplot",
        manual_title="Protein Lineplot Manual",
        manual_path="/manuals/ProteinLineplotManual.pdf",
        ai_functions=["single_protein_lineplot_plot"],
        manual_digest="Track feature trajectories across samples and condition transitions.",
        preferred_kinds=["protein", "phospho", "phosprot"],
    ),
    "singleProtein.heatmap": _entry(
        "singleProtein.heatmap",
        "Phosphosites on Protein Heatmap",
        ai_functions=["single_protein_heatmap_plot"],
        manual_digest="Inspect phosphosite/sample matrix patterns for a selected phosphoprotein context.",
        preferred_kinds=["phospho", "protein", "phosprot"],
    ),
    "phospho.phosphositePlot": _entry(
        "phospho.phosphositePlot",
        "Phosphosite Plot",
        manual_title="Phosphosite Plot Manual",
        manual_path="/manuals/PhossitePlotManual.pdf",
        ai_functions=["phosphosite_plot_png"],
        manual_digest="Use phosphosite/phosphopeptide/phosphoprotein count summary as baseline coverage context.",
    ),
    "phospho.coverage": _entry(
        "phospho.coverage",
        "Phosphosite Coverage Plot",
        manual_title="Phosphosite Coverage Plot Manual",
        manual_path="/manuals/PhossiteCoveragePlotManual.pdf",
        ai_functions=["phospho_coverage_png"],
        manual_digest="Assess phosphosite detection completeness per sample and class-specific split.",
    ),
    "phospho.distribution": _entry(
        "phospho.distribution",
        "Phosphosite Distribution",
        manual_title="Phosphosite Distribution Manual",
        manual_path="/manuals/PhossiteDistributionPlotManual.pdf",
        ai_functions=["phospho_distribution_png"],
        manual_digest="Use localization/cutoff-aware phosphosite distribution to evaluate phospho data quality.",
    ),
    "phospho.sty": _entry(
        "phospho.sty",
        "STY Plot",
        ai_functions=["phospho_sty_png"],
        manual_digest="Interpret S/T/Y proportions to validate expected phosphosite composition.",
    ),
    "comparison.pearson": _entry(
        "comparison.pearson",
        "Pearson Correlation",
        manual_title="Pearson Correlation Plot Manual",
        manual_path="/manuals/PearsonCorrelationPlotManual.pdf",
        ai_functions=["comparison_pearson_png"],
        manual_digest="Use pairwise correlation metrics for selected samples/conditions to assess concordance.",
    ),
    "comparison.venn": _entry(
        "comparison.venn",
        "Venn Diagram",
        manual_title="Venn Diagram Manual",
        manual_path="/manuals/VennDiagramManual.pdf",
        ai_functions=["comparison_venn_png"],
        manual_digest="Use overlap-region counts to compare shared/unique feature sets.",
    ),
    "stats.volcano": _entry(
        "stats.volcano",
        "Volcano Plot",
        manual_title="Volcano Plot Manual",
        manual_path="/manuals/VolcanoPlotManual.pdf",
        ai_functions=["stats_volcano_targets"],
        manual_digest=(
            "Interpret significance vs fold-change thresholds and up/down-regulated partitions. "
            "When asked for interesting targets, prioritize significant features and report both effect size "
            "(log2FC) and statistical strength (-log10 adjusted p-value, p-value context)."
        ),
    ),
}


def manual_entry_for_module(module_key: str) -> AiManualEntry:
    normalized = str(module_key or "").strip()
    if not normalized:
        return _entry("unknown", "Unknown Module", manual_digest="No module context provided.")
    entry = AI_MANUAL.get(normalized)
    if entry is not None:
        return entry
    return _entry(
        normalized,
        normalized.replace(".", " / ").title(),
        manual_digest="No curated AI manual entry yet for this module.",
    )
