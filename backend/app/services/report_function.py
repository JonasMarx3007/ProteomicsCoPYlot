from __future__ import annotations

import base64
import html
import re
from datetime import datetime
from typing import Any, Mapping, Callable

import pandas as pd

from app.schemas.stats import VolcanoRequest
from app.schemas.summary import (
    SummaryReportContext,
    SummaryReportRequest,
    SummaryReportResponse,
    SummaryVolcanoEntry,
)
from app.services.annotation_store import get_annotation
from app.services.dataset_store import get_current_dataset
from app.services.functions import (
    completeness_missing_value_plot,
    completeness_missing_value_plot_peptide,
    phospho_coverage_png,
    phosphosite_plot_png,
    qc_abundance_plot,
    qc_boxplot_plot,
    qc_correlation_plot,
    qc_coverage_plot,
    qc_cv_plot,
    qc_intensity_histogram_plot,
    qc_peptide_coverage_plot,
    qc_pca_plot,
    qc_pca_interactive_html,
)
from app.services.peptide_tools import (
    peptide_missed_cleavage_plot,
    peptide_modification_plot,
    peptide_rt_plot,
)
from app.services.stats_tools import volcano_html
from app.services.table_functions import (
    qc_boxplot_table,
    qc_coverage_table,
    qc_cv_table,
)

VERSION = "Proteomics CoPYlot V1.0.0"

GENERAL_COMMENTS: dict[str, list[str]] = {
    "RT": [
        "During LC-MS/MS analysis complex peptide mixtures of a given sample are separated via reversed-phase liquid chromatography (LC). The requirement for reproducible peptide and protein identification and quantification is the reproducible separation of peptides over the entire gradient length utilized for analysis in all samples of the data set.",
        "Ideally, retention times do align over the entire gradient length. Significant deviations from this pattern indicate technical problems during liquid chromatography.",
    ],
    "Modification": [
        "Amino acid modifications can occur via post-translational modifications in the investigated biological system / condition, during sample storage or protein to peptide processing for LC-MS analysis.",
        "Typically, only expected amino acid modifications will be taken into account to be present in the data set. Numbers of identified peptide modifications are expected to be in a similar range. Outliers may indicate experimental or technical abnormalities. Usually, we expect Carbamidomethylation of Cysteine residues as a constant modification - induced during sample processing - and Methionine oxidation as a dynamic modification into account, if not otherwise stipulated.",
    ],
    "MissedCleavage": [
        "Sample processing methods in proteomic bottom-up experiments include a proteolytic digestion step for peptide generation. Missed cleavages of a given protein by a specific protease can occur, nevertheless the frequency of missed cleavages should be low and comparable in all samples.",
    ],
    "CoveragePep": [
        "Numbers of peptide Identifications across all samples is a measure of non-missing measurements by replicate. Protein inference, identification and quantification are all based on reproducible peptide identification and the peptide's ion intensity.",
        "Low peptide counts in a sample / MS-run may suggest a systematic flaw in the experiment (e.g. low protein input material, protein to peptide processing errors, technical problems during LC-MS data acquisition).",
        "Ideally, numbers of peptide identifications in all samples are high and of similar count.",
    ],
    "MissingValuePep": [
        "The amount of missing values can be affected by the biological condition or by technical factors during sample processing methods or MS-measurements and it can vary largely between experiments. For a healthy experiment we expect: the distribution of available measurements by replicate to be similar across replicates, especially within the same biological/experimental condition. An unusually low value in one or more replicates can be symptomatic of technical problems and should be taken into account when interpreting the final differential protein expression results after pairwise comparison.",
        "A high frequency of zero missing peptides indicates reproducible identifications of given peptides in all samples, a prerequisite for protein quantification.",
    ],
    "CoverageProt": [
        "Identification of proteins is a measure of the number of non-missing measurements by replicate.",
        "Low protein counts in a sample / LC-MS/MS run may suggest a systematic flaw in the experiment (low protein input at the beginning, technical problems during sample processing, etc.) that needs to be addressed prior to further interpretation of the results in the statistical analysis section.",
        "Ideally, numbers of protein identifications in all samples of the data set are high and in a similar range.",
    ],
    "MissingValueProt": [
        "Missing values on protein level may depend on the experimental set-up, e.g. differences in experimental conditions or on technical flaws during sample collection, sample processing, or measurements.",
        "For technical replicates a very low level of missing values can be expected. A high frequency of zero missing values indicates high reproducibility of protein identifications in all samples in the data set.",
    ],
    "HistogramIntProt": [
        "The distributions of log2-transformed means of quantitative protein values for each experimental group are plotted in the next graph.",
        "In a healthy experiment, the distributions of protein quantitative mean values of all groups are similar, depicted by the same shape of the distribution curves.",
    ],
    "BoxplotIntProt": [
        "Protein intensity distributions - Depicted are the measured log2-raw protein intensities in a boxplot of each sample.",
        "Missing values are not considered when creating the boxplots. Zero intensity values are considered as missing values.",
        "For a healthy experiment, we expect similar log2-intensity distributions in all samples and all conditions.",
        "Significant deviations indicate unequal peptide loading during LC-MS/MS or unequal protein amounts in the starting material. Also, major contaminants in the samples can influence accurate peptide concentration measurements and, therefore, the number of protein identifications and protein quantitative values in a given sample.",
    ],
    "CovProt": [
        "The CV or relative Standard Deviation is calculated by the ratio of the standard deviation to the mean (on quantitative protein level). It is used to measure the precision of a measure, in this case protein intensity.",
        "The plot below shows the distribution of the CVs by experimental conditions (groups) in boxplots where each CV is calculated by all proteins and by experimental condition. The CV is displayed as %CV, which is the percentage of dispersion of data points around the mean for all identified proteins in the data set per experimental group.",
        "For a healthy experiment, we expect: The distribution of the %CVs across all conditions to be mostly overlapping, and of similar modes. The modes of the %CVs not to be too high, ideally not above 50%, for best results in the statistical section not above 25%. If the distributions show worryingly large %CVs, the precision of LC-MS/MS measurements across all samples in the data set is low which could affect the quality of the differential expression analysis in the statistics section, due to high variance in the data set.",
    ],
    "PCAProt": [
        "The Principal Component Analysis (PCA) plot is used to visualize differences between samples that are constituted by their protein intensity profiles. PCA transforms high-dimensional data, like thousands of measured proteins or peptides intensities, into a reduced set of dimensions. The first two dimensions explain the greatest variability between the samples and they are a useful visual tool to confirm known clustering of the samples (of the same experimental group or replicates) or to identify potential problems in the data set.",
        "For a healthy experiment, we expect: 1.) Technical replicates to cluster tightly together. 2.) Biological replicates to cluster more closely together than non-replicates. 3. Clustering of samples of the same condition of interest (or experimental group) should be visible and different experimental groups should be separated from each other.",
        "If unexpected clusters occur or replicates do not cluster together, it can be due to high individual sample variability, or extra variability introduced by factors such as technical processing, high variability of protein content in the starting material (e.g. FBS from the culture medium still present), other unexplored biological differences, or unintentional sample swaps, etc).",
        "The interpretation and trust in the differential protein expression results in the statistical section should take the above mentioned considerations into account. If you think that the samples in the experiment show largely unexpected patterns, it is advisable to request support from a data analyst to help with data interpretation.",
    ],
    "AbundanceProt": [
        "The rank plot of mean protein intensities (log10) within experimental conditions / groups illustrates the coverage of the dynamic ranges of protein intensities within the experimental conditions / groups in the data set.",
        "For a healthy experiment, we expect high similarity between the curves.",
        "If the curves look worryingly different, it could affect the quality of the differential protein expression analysis in the statistics section.",
        "Usually, the covered dynamic range of protein quantitative values should be four or more orders of magnitude. Though, the observable dynamic range is also dependent on the biological sample analyzed (e.g. body fluid or cell lysate). for example the vast dynamic range of plasma or serum proteins, estimated at 12-13 orders of magnitude, renders plasma proteome analysis based on mass spectrometry extremely challenging, as the high abundant plasma proteins hinder the identification of low abundant proteins and negatively impact the accessible dynamic range.",
    ],
    "CorrelationProt": [
        "The correlation plot shows the Pearson correlation coefficient between all samples in the experiment. Hierarchical clustering was used to order the samples in the matrix.",
        "For a healthy experiment we expect: a) technical replicates have high correlations (1 = 100% identical), b) biological replicates (samples of the same group) to have higher correlations than non-replicates.",
        "Low correlation between samples may indicate many missing values in a given sample or low similarity between different experimental conditions or groups. Low correlation between samples can also be related to normalization errors due to unequal peptide amount loading during LC-MS/MS measurements or major contaminants in the samples (please, compare with plots 2.3 Histogram Intensity and 2.4 Boxplot Intensity).",
    ],
    "Phossite": [
        "Number of Phosphosites collapsed on phosphopeptide and phosphoprotein level.",
    ],
    "Coverage(Number)Phos": [
        "Identification of phosphosites is a measure of the number of non-missing measurements by replicate.",
        "Low phosphosite counts in a sample / LC-MS/MS run may suggest technical variability, low enrichment efficiency, or sample processing issues that should be considered before downstream statistical analysis.",
        "Ideally, the numbers of confidently localized phosphosite identifications are high and comparable across all samples in the dataset.",
    ],
    "Coverage(Quality)Phos": [
        "Identification of phosphosites is a measure of the number of non-missing measurements by replicate, here qualified by their localisation probability.",
    ],
    "MissingValuePhos": [
        "The amount of missing values can be affected by biological regulation of phosphorylation or by technical factors during sample processing and MS-measurements, and it can vary substantially between experiments. For a healthy experiment we expect: the distribution of available phosphosite measurements by replicate to be similar across replicates, especially within the same biological/experimental condition. An unusually low value in one or more replicates can be symptomatic of technical problems (e.g., enrichment efficiency or instrument issues) and should be taken into account when interpreting the final differential phosphosite analysis results after pairwise comparison.",
        "A high frequency of zero missing phosphosites indicates reproducible identification of given phosphorylation sites in all samples, which is a prerequisite for reliable phosphosite quantification.",
    ],
    "HistogramIntPhos": [
        "The distributions of log2-transformed means of quantitative phosphosite values for each experimental group are plotted in the next graph.",
        "In a healthy experiment, the distributions of phosphosite quantitative mean values across all groups are expected to be similar, depicted by comparable shapes of the distribution curves.",
    ],
    "BoxplotIntPhos": [
        "Phosphosite intensity distributions - Depicted are the measured log2-raw phosphosite intensities in a boxplot of each sample.",
        "Missing values are not considered when creating the boxplots. Zero intensity values are treated as missing values.",
        "For a healthy experiment, we expect similar log2-intensity distributions of phosphosites across all samples and experimental conditions.",
        "Significant deviations may indicate unequal peptide loading during LC-MS/MS, variability in phosphopeptide enrichment efficiency, or unequal protein amounts in the starting material. In addition, major contaminants or technical issues can influence accurate phosphosite quantification and the number of confidently localized phosphosites in a given sample.",
    ],
    "CovPhos": [
        "The CV or relative Standard Deviation is calculated as the ratio of the standard deviation to the mean (on quantitative phosphosite level). It is used to measure the precision of a measure, in this case phosphosite intensity.",
        "The plot below shows the distribution of the CVs by experimental conditions (groups) in boxplots where each CV is calculated for all phosphosites within each condition. The CV is displayed as %CV, representing the percentage of dispersion of data points around the mean for all identified phosphosites in the dataset per experimental group.",
        "For a healthy experiment, we expect: the distribution of the %CVs across all conditions to be mostly overlapping, with similar modes. Because phosphosites typically show higher variance than proteins, %CVs ideally should not exceed 40%, and for robust statistical analysis preferably remain below 60%. If the distributions show worryingly large %CVs, the precision of LC-MS/MS measurements across samples is low, which could negatively affect the reliability of differential phosphosite analysis due to high variance in the dataset.",
    ],
    "PCAPhos": [
        "The Principal Component Analysis (PCA) plot is used to visualize differences between samples based on their phosphosite intensity profiles. PCA transforms high-dimensional data, such as thousands of measured phosphosite intensities, into a reduced set of dimensions. The first two dimensions explain the greatest variability between the samples and provide a useful visual tool to confirm known clustering of samples (technical or biological replicates) or to identify potential problems in the dataset.",
        "For a healthy experiment, we expect: 1.) Technical replicates to cluster tightly together. 2.) Biological replicates to cluster more closely together than non-replicates. 3.) Samples from the same experimental group (condition of interest) should cluster together, while different experimental groups should be separated.",
        "If unexpected clusters occur or replicates do not cluster together, it may be due to high individual sample variability, variable phosphopeptide enrichment efficiency, technical processing differences, high variability in protein content of the starting material, other unexplored biological differences, or unintentional sample swaps.",
        "When interpreting differential phosphosite analysis results in the statistical section, the above considerations should be taken into account. If samples show largely unexpected clustering patterns, it is advisable to seek support from a data analyst to assist with data interpretation.",
    ],
    "AbundancePhos": [
        "The rank plot of mean phosphosite intensities (log10) within experimental conditions / groups illustrates the coverage of the dynamic ranges of phosphosite intensities within the experimental conditions / groups in the dataset.",
        "For a healthy experiment, we expect high similarity between the curves across all groups.",
        "If the curves look worryingly different, it could affect the quality of the differential phosphosite analysis in the statistics section.",
        "Typically, the covered dynamic range of phosphosite quantitative values should span several orders of magnitude. However, the observable dynamic range also depends on the biological sample analyzed (e.g., cell lysate, tissue, or body fluid). For example, the vast dynamic range of plasma or serum proteins, estimated at 12-13 orders of magnitude, can hinder phosphopeptide identification and negatively impact the accessible dynamic range for phosphosite quantification.",
    ],
    "CorrelationPhos": [
        "The correlation plot shows the Pearson correlation coefficient between all samples in the experiment based on phosphosite intensities. Hierarchical clustering was used to order the samples in the matrix.",
        "For a healthy experiment we expect: a) technical replicates to have high correlations (1 = 100% identical), b) biological replicates (samples of the same group) to have higher correlations than non-replicates.",
        "Low correlation between samples may indicate many missing phosphosite values in a given sample, low enrichment efficiency, or true biological differences between experimental conditions or groups. Low correlation can also be related to normalization issues, unequal peptide amount loading during LC-MS/MS, or the presence of major contaminants in the samples (please, compare with plots 2.3 Histogram Intensity and 2.4 Boxplot Intensity).",
    ],
    "VolcanoProt": [
        "The occurrence of differential abundant proteins was tested by comparisons between two conditions (t-test). Multiple hypothesis testing was done by Benjamini-Hochberg adjustment of p-values and the false discovery rate was set to 0.05 (q-value < 0.05).",
        "Significant differentially abundant proteins are defined as proteins demonstrating a fold change of > 2 and an adjusted p-value < 0.05.",
        "The results are illustrated as volcano plots (the y-axis indicates the negative logarithm (-log10) of the adjusted p-value and the x-axis indicates the log(2) fold change; dotted lines indicate the thresholds for significance: q-value < 0.05 and FC > 2.",
    ],
    "VolcanoPhos": [
        "The occurrence of differentially abundant phosphosites was tested by comparisons between two conditions (t-test). Multiple hypothesis testing was done by Benjamini-Hochberg adjustment of p-values and the false discovery rate was set to 0.05 (q-value < 0.05).",
        "Significant differentially abundant phosphosites are defined as sites demonstrating a fold change of > 2 and an adjusted p-value < 0.05.",
        "The results are illustrated as volcano plots (the y-axis indicates the negative logarithm (-log10) of the adjusted p-value and the x-axis indicates the log2 fold change; dotted lines indicate the thresholds for significance: q-value < 0.05 and FC > 2).",
    ],
}


def _escape_multiline(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def _file_name_from_title(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", title.strip()).strip("_")
    if not slug:
        slug = "CoPYlot_report"
    return f"{slug}.html"


def _png_to_html(png_bytes: bytes) -> str:
    encoded = base64.b64encode(png_bytes).decode("utf-8")
    return f"<img src='data:image/png;base64,{encoded}' style='width:100%;height:auto;border:1px solid #d6d6d6;border-radius:8px;'/>"


def _plotly_to_iframe(plot_html: str, height_px: int = 740) -> str:
    srcdoc = html.escape(plot_html, quote=True)
    return (
        f"<iframe srcdoc=\"{srcdoc}\" "
        f"style='display:block;width:100%;height:{max(520, int(height_px))}px;border:1px solid #d6d6d6;border-radius:8px;' "
        "loading='lazy'></iframe>"
    )


def _table_to_html(title: str, frame: pd.DataFrame) -> str:
    safe = frame.copy().where(pd.notna(frame), "")
    table_html = safe.to_html(index=False, border=0, justify="left")
    return (
        f"<h3>{html.escape(title)}</h3>"
        "<div style='max-height:320px;overflow:auto;border:1px solid #d6d6d6;border-radius:8px;padding:8px;margin-bottom:16px;'>"
        f"{table_html}"
        "</div>"
    )


def _clean_text_entries(raw: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in raw.items():
        key_text = str(key).strip()
        value_text = str(value).strip()
        if not key_text or not value_text:
            continue
        cleaned[key_text] = value_text
    return cleaned


def _custom_text(text_entries: dict[str, str], key: str) -> str:
    text = text_entries.get(key, "").strip()
    if not text:
        return ""
    return f"<p>{_escape_multiline(text)}</p>"


def _safe_png(
    *,
    renderer: Callable[[], bytes],
    fallback_title: str,
    warnings: list[str],
) -> str:
    try:
        return _png_to_html(renderer())
    except Exception as exc:  # pragma: no cover - defensive runtime behavior
        warnings.append(f"{fallback_title}: {exc}")
        return (
            "<div style='padding:10px;border:1px solid #f5c2c7;background:#f8d7da;color:#842029;border-radius:8px;'>"
            f"Could not render plot: {html.escape(str(exc))}"
            "</div>"
        )


def _safe_plotly(
    *,
    renderer: Callable[[], str],
    fallback_title: str,
    warnings: list[str],
    height_px: int = 740,
) -> str:
    try:
        return _plotly_to_iframe(renderer(), height_px=height_px)
    except Exception as exc:  # pragma: no cover - defensive runtime behavior
        warnings.append(f"{fallback_title}: {exc}")
        return (
            "<div style='padding:10px;border:1px solid #f5c2c7;background:#f8d7da;color:#842029;border-radius:8px;'>"
            f"Could not render interactive plot: {html.escape(str(exc))}"
            "</div>"
        )


def _safe_table_html(
    *,
    renderer: Callable[[], pd.DataFrame],
    title: str,
    fallback_title: str,
    warnings: list[str],
) -> str:
    try:
        frame = renderer()
    except Exception as exc:  # pragma: no cover - defensive runtime behavior
        warnings.append(f"{fallback_title}: {exc}")
        return (
            "<div style='padding:10px;border:1px solid #f5c2c7;background:#f8d7da;color:#842029;border-radius:8px;'>"
            f"Could not render summary table: {html.escape(str(exc))}"
            "</div>"
        )
    if frame.empty:
        return (
            "<div style='padding:10px;border:1px solid #d6d6d6;background:#f8fafc;color:#475569;border-radius:8px;'>"
            "No summary rows available."
            "</div>"
        )
    return _table_to_html(title, frame)


def _append_plot_section(
    *,
    html_parts: list[str],
    section_id: str,
    title: str,
    description: str | None,
    general_comment_key: str | None,
    text_entries: dict[str, str],
    text_key: str,
    content_html: str,
) -> None:
    html_parts.append(f"<h2>{html.escape(section_id)} {html.escape(title)}</h2>")
    comments: list[str] = []
    if general_comment_key:
        comments.extend(GENERAL_COMMENTS.get(general_comment_key, []))
    if not comments and description:
        comments.append(description)
    for paragraph in comments:
        html_parts.append(f"<p>{html.escape(paragraph)}</p>")
    above = _custom_text(text_entries, f"{text_key}Above")
    if above:
        html_parts.append(above)
    html_parts.append(content_html)
    below = _custom_text(text_entries, f"{text_key}Below")
    if below:
        html_parts.append(below)


def _module_settings(
    context: SummaryReportContext,
    kind: str,
    module: str,
) -> dict[str, Any]:
    by_kind = context.qcSettings.get(kind, {})
    if not isinstance(by_kind, Mapping):
        return {}
    values = by_kind.get(module, {})
    if not isinstance(values, Mapping):
        return {}
    return dict(values)


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on", "y"}:
            return True
        if normalized in {"false", "0", "no", "off", "n"}:
            return False
    return default


def _to_int(
    value: Any,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _to_float(
    value: Any,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    if minimum is not None:
        parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _to_str(value: Any, default: str) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    return default


def _interactive_height_px(height_cm: float, *, min_px: int = 760, extra_px: int = 240) -> int:
    return max(min_px, int(round((height_cm * 96.0) / 2.54)) + extra_px)


def _volcano_entries(
    context: SummaryReportContext,
    kind: str,
) -> list[SummaryVolcanoEntry]:
    return [
        entry
        for entry in context.volcanoEntries
        if entry.kind == kind and not entry.control
    ]


def _volcano_block_html(
    *,
    kind: str,
    entries: list[SummaryVolcanoEntry],
    warnings: list[str],
) -> str:
    parts: list[str] = []
    for index, entry in enumerate(entries, start=1):
        parts.append(
            f"<h3>Comparison {index}: {html.escape(entry.condition1)} vs {html.escape(entry.condition2)}</h3>"
        )
        parts.append(
            _safe_plotly(
                renderer=lambda entry=entry, kind=kind: volcano_html(
                    VolcanoRequest(
                        kind=kind,
                        condition1=entry.condition1,
                        condition2=entry.condition2,
                        identifier=entry.identifier,
                        pValueThreshold=entry.pValueThreshold,
                        log2fcThreshold=entry.log2fcThreshold,
                        testType=entry.testType,
                        useUncorrected=entry.useUncorrected,
                        highlightTerms=entry.highlightTerms,
                    )
                ),
                fallback_title=f"{kind.capitalize()} Volcano Plot ({entry.condition1} vs {entry.condition2})",
                warnings=warnings,
                height_px=920,
            )
        )
    return "".join(parts)


def report_function(payload: SummaryReportRequest) -> SummaryReportResponse:
    title = payload.title.strip() or "Untitled Report"
    author = payload.author.strip() or "Unknown Author"
    date_str = datetime.now().strftime("%Y-%m-%d")
    text_entries = _clean_text_entries(payload.textEntries)
    warnings: list[str] = []

    protein_annotation = get_annotation("protein")
    phospho_annotation = get_annotation("phospho")

    has_peptide = get_current_dataset("peptide") is not None
    has_protein = (
        get_current_dataset("protein") is not None
        and protein_annotation is not None
        and not protein_annotation.metadata.empty
    )
    has_phospho = (
        get_current_dataset("phospho") is not None
        and phospho_annotation is not None
        and not phospho_annotation.metadata.empty
    )

    if get_current_dataset("protein") is not None and not has_protein:
        warnings.append("Protein dataset found but annotation metadata is missing. Generate annotation first.")
    if get_current_dataset("phospho") is not None and not has_phospho:
        warnings.append("Phospho dataset found but annotation metadata is missing. Generate annotation first.")

    report_context = payload.reportContext or SummaryReportContext()
    protein_volcano_entries = _volcano_entries(report_context, "protein")
    phospho_volcano_entries = _volcano_entries(report_context, "phospho")

    next_block = 1
    peptide_block = next_block if has_peptide else None
    if has_peptide:
        next_block += 1
    protein_block = next_block if has_protein else None
    if has_protein:
        next_block += 1
    phospho_block = next_block if has_phospho else None

    html_parts: list[str] = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'>",
        f"<title>{html.escape(title)}</title>",
        "<style>",
        "body{font-family:Arial,sans-serif;max-width:1300px;margin:0 auto;padding:24px;line-height:1.5;color:#111;}",
        "h1{margin-bottom:6px;}",
        "h2{margin-top:24px;border-top:1px solid #e8e8e8;padding-top:14px;}",
        "h3{margin-top:18px;}",
        "table{border-collapse:collapse;width:100%;font-size:14px;}",
        "th,td{border:1px solid #d6d6d6;padding:6px;text-align:left;vertical-align:top;}",
        "th{background:#f5f5f5;}",
        ".toc-group{font-size:20px;font-weight:700;margin:10px 0 4px;}",
        ".toc-item{font-size:15px;margin:2px 0 2px 14px;}",
        ".meta{color:#444;margin:2px 0;}",
        ".warn{border:1px solid #ffe69c;background:#fff3cd;color:#664d03;padding:10px;border-radius:8px;margin:8px 0;}",
        "</style>",
        "</head><body>",
        f"<h1>{html.escape(title)}</h1>",
        f"<p class='meta'><strong>Author:</strong> {html.escape(author)}</p>",
        f"<p class='meta'><strong>Date:</strong> {html.escape(date_str)}</p>",
        f"<p class='meta'><strong>Version:</strong> {html.escape(VERSION)}</p>",
    ]

    introduction = _custom_text(text_entries, "Introduction")
    if introduction:
        html_parts.append("<h2>Introduction</h2>")
        html_parts.append(introduction)

    html_parts.append("<h2>Table of Contents</h2>")
    if peptide_block is not None:
        html_parts.extend(
            [
                f"<p class='toc-group'>{peptide_block}. Peptide Level Plots</p>",
                f"<p class='toc-item'>{peptide_block}.1 Coverage Plot - Peptide Level</p>",
                f"<p class='toc-item'>{peptide_block}.2 Missing Value Plot - Peptide Level</p>",
                f"<p class='toc-item'>{peptide_block}.3 Retention Time Plot</p>",
                f"<p class='toc-item'>{peptide_block}.4 Modification Plot</p>",
                f"<p class='toc-item'>{peptide_block}.5 Missed Cleavage Plot</p>",
            ]
        )
    if protein_block is not None:
        html_parts.extend(
            [
                f"<p class='toc-group'>{protein_block}. Protein Level Plots</p>",
                f"<p class='toc-item'>{protein_block}.1 Coverage Plot</p>",
                f"<p class='toc-item'>{protein_block}.2 Missing Value Plot</p>",
                f"<p class='toc-item'>{protein_block}.3 Histogram Intensity</p>",
                f"<p class='toc-item'>{protein_block}.4 Boxplot Intensity</p>",
                f"<p class='toc-item'>{protein_block}.5 Coefficient of Variation Plot</p>",
                f"<p class='toc-item'>{protein_block}.6 PCA Plot</p>",
                f"<p class='toc-item'>{protein_block}.7 Abundance Plot</p>",
                f"<p class='toc-item'>{protein_block}.8 Correlation Plot</p>",
            ]
        )
        if protein_volcano_entries:
            html_parts.append(f"<p class='toc-item'>{protein_block}.9 Volcano Plot</p>")
    if phospho_block is not None:
        html_parts.extend(
            [
                f"<p class='toc-group'>{phospho_block}. Phosphosite Level Plots</p>",
                f"<p class='toc-item'>{phospho_block}.1 Overview Phosphosites</p>",
                f"<p class='toc-item'>{phospho_block}.2 Coverage Plot (Number)</p>",
                f"<p class='toc-item'>{phospho_block}.3 Coverage Plot (Quality)</p>",
                f"<p class='toc-item'>{phospho_block}.4 Missing Value Plot</p>",
                f"<p class='toc-item'>{phospho_block}.5 Histogram Intensity</p>",
                f"<p class='toc-item'>{phospho_block}.6 Boxplot Intensity</p>",
                f"<p class='toc-item'>{phospho_block}.7 Coefficient of Variation Plot</p>",
                f"<p class='toc-item'>{phospho_block}.8 PCA Plot</p>",
                f"<p class='toc-item'>{phospho_block}.9 Abundance Plot</p>",
                f"<p class='toc-item'>{phospho_block}.10 Correlation Plot</p>",
            ]
        )
        if phospho_volcano_entries:
            html_parts.append(f"<p class='toc-item'>{phospho_block}.11 Volcano Plot</p>")

    if peptide_block is not None:
        html_parts.append(f"<h1>{peptide_block} Peptide Level</h1>")

        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{peptide_block}.1",
            title="Coverage Plot - Peptide Level",
            description=None,
            general_comment_key="CoveragePep",
            text_entries=text_entries,
            text_key="CoveragePep",
            content_html=_safe_png(
                renderer=lambda: qc_peptide_coverage_plot(),
                fallback_title="Peptide Coverage Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{peptide_block}.2",
            title="Missing Value Plot - Peptide Level",
            description=None,
            general_comment_key="MissingValuePep",
            text_entries=text_entries,
            text_key="MissingValuePep",
            content_html=_safe_png(
                renderer=lambda: completeness_missing_value_plot_peptide(),
                fallback_title="Peptide Missing Value Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{peptide_block}.3",
            title="Retention Time Plot",
            description=None,
            general_comment_key="RT",
            text_entries=text_entries,
            text_key="RT",
            content_html=_safe_png(
                renderer=lambda: peptide_rt_plot(),
                fallback_title="Peptide RT Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{peptide_block}.4",
            title="Modification Plot",
            description=None,
            general_comment_key="Modification",
            text_entries=text_entries,
            text_key="Modification",
            content_html=_safe_png(
                renderer=lambda: peptide_modification_plot(),
                fallback_title="Peptide Modification Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{peptide_block}.5",
            title="Missed Cleavage Plot",
            description=None,
            general_comment_key="MissedCleavage",
            text_entries=text_entries,
            text_key="MissedCleavage",
            content_html=_safe_png(
                renderer=lambda: peptide_missed_cleavage_plot(),
                fallback_title="Peptide Missed Cleavage Plot",
                warnings=warnings,
            ),
        )

    if protein_block is not None:
        html_parts.append(f"<h1>{protein_block} Protein Level</h1>")
        protein_coverage = _module_settings(report_context, "protein", "coverage")
        protein_hist = _module_settings(report_context, "protein", "hist")
        protein_box = _module_settings(report_context, "protein", "box")
        protein_cv = _module_settings(report_context, "protein", "cv")
        protein_pca = _module_settings(report_context, "protein", "pca")
        protein_abundance = _module_settings(report_context, "protein", "abundance")
        protein_correlation = _module_settings(report_context, "protein", "correlation")

        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.1",
            title="Coverage Plot",
            description=None,
            general_comment_key="CoverageProt",
            text_entries=text_entries,
            text_key="CoverageProt",
            content_html=(
                _safe_png(
                    renderer=lambda: qc_coverage_plot(
                        kind="protein",
                        include_id=_to_bool(protein_coverage.get("includeId"), False),
                        header=_to_bool(protein_coverage.get("header"), True),
                        legend=_to_bool(protein_coverage.get("legend"), True),
                        summary=_to_bool(protein_coverage.get("summary"), False),
                        text=_to_bool(protein_coverage.get("text"), False),
                        text_size=_to_int(protein_coverage.get("textSize"), 9, minimum=6, maximum=24),
                        width_cm=_to_float(protein_coverage.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                        height_cm=_to_float(protein_coverage.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                        dpi=_to_int(protein_coverage.get("dpi"), 300, minimum=72, maximum=1200),
                    ),
                    fallback_title="Protein Coverage Plot",
                    warnings=warnings,
                )
                + _safe_table_html(
                    renderer=lambda: qc_coverage_table(
                        kind="protein",
                        summary=_to_bool(protein_coverage.get("summary"), False),
                    ),
                    title="Coverage Summary Table",
                    fallback_title="Protein Coverage Summary Table",
                    warnings=warnings,
                )
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.2",
            title="Missing Value Plot",
            description=None,
            general_comment_key="MissingValueProt",
            text_entries=text_entries,
            text_key="MissingValueProt",
            content_html=_safe_png(
                renderer=lambda: completeness_missing_value_plot(kind="protein"),
                fallback_title="Protein Missing Value Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.3",
            title="Histogram Intensity",
            description=None,
            general_comment_key="HistogramIntProt",
            text_entries=text_entries,
            text_key="HistogramIntProt",
            content_html=_safe_png(
                renderer=lambda: qc_intensity_histogram_plot(
                    kind="protein",
                    header=_to_bool(protein_hist.get("header"), True),
                    legend=_to_bool(protein_hist.get("legend"), True),
                    width_cm=_to_float(protein_hist.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                    height_cm=_to_float(protein_hist.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                    dpi=_to_int(protein_hist.get("dpi"), 300, minimum=72, maximum=1200),
                ),
                fallback_title="Protein Histogram Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.4",
            title="Boxplot Intensity",
            description=None,
            general_comment_key="BoxplotIntProt",
            text_entries=text_entries,
            text_key="BoxplotIntProt",
            content_html=(
                _safe_png(
                    renderer=lambda: qc_boxplot_plot(
                        kind="protein",
                        mode=_to_str(protein_box.get("mode"), "Mean"),
                        outliers=_to_bool(protein_box.get("outliers"), False),
                        include_id=_to_bool(protein_box.get("includeId"), False),
                        header=_to_bool(protein_box.get("header"), True),
                        legend=_to_bool(protein_box.get("legend"), True),
                        text=_to_bool(protein_box.get("text"), False),
                        text_size=_to_int(protein_box.get("textSize"), 9, minimum=6, maximum=24),
                        width_cm=_to_float(protein_box.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                        height_cm=_to_float(protein_box.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                        dpi=_to_int(protein_box.get("dpi"), 300, minimum=72, maximum=1200),
                    ),
                    fallback_title="Protein Boxplot",
                    warnings=warnings,
                )
                + _safe_table_html(
                    renderer=lambda: qc_boxplot_table(
                        kind="protein",
                        mode=_to_str(protein_box.get("mode"), "Mean"),
                    ),
                    title="Boxplot Summary Table",
                    fallback_title="Protein Boxplot Summary Table",
                    warnings=warnings,
                )
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.5",
            title="Coefficient of Variation Plot",
            description=None,
            general_comment_key="CovProt",
            text_entries=text_entries,
            text_key="CovProt",
            content_html=(
                _safe_png(
                    renderer=lambda: qc_cv_plot(
                        kind="protein",
                        outliers=_to_bool(protein_cv.get("outliers"), False),
                        header=_to_bool(protein_cv.get("header"), True),
                        legend=_to_bool(protein_cv.get("legend"), True),
                        text=_to_bool(protein_cv.get("text"), False),
                        text_size=_to_int(protein_cv.get("textSize"), 9, minimum=6, maximum=24),
                        width_cm=_to_float(protein_cv.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                        height_cm=_to_float(protein_cv.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                        dpi=_to_int(protein_cv.get("dpi"), 300, minimum=72, maximum=1200),
                    ),
                    fallback_title="Protein CV Plot",
                    warnings=warnings,
                )
                + _safe_table_html(
                    renderer=lambda: qc_cv_table(kind="protein"),
                    title="Coefficient of Variation Summary Table",
                    fallback_title="Protein CV Summary Table",
                    warnings=warnings,
                )
            ),
        )
        protein_pca_height_cm = _to_float(protein_pca.get("heightCm"), 10.0, minimum=4.0, maximum=60.0)
        protein_pca_interactive = _to_str(protein_pca.get("type"), "Normal").lower() == "interactive"
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.6",
            title="PCA Plot",
            description=None,
            general_comment_key="PCAProt",
            text_entries=text_entries,
            text_key="PCAProt",
            content_html=(
                _safe_plotly(
                    renderer=lambda: qc_pca_interactive_html(
                        kind="protein",
                        header=_to_bool(protein_pca.get("header"), True),
                        legend=_to_bool(protein_pca.get("legend"), True),
                        plot_dim=_to_str(protein_pca.get("plotDim"), "2D"),
                        add_ellipses=_to_bool(protein_pca.get("addEllipses"), False),
                        dot_size=_to_int(protein_pca.get("dotSize"), 5, minimum=1, maximum=60),
                        width_cm=_to_float(protein_pca.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                        height_cm=protein_pca_height_cm,
                    ),
                    fallback_title="Protein PCA Interactive Plot",
                    warnings=warnings,
                    height_px=_interactive_height_px(protein_pca_height_cm),
                )
                if protein_pca_interactive
                else _safe_png(
                    renderer=lambda: qc_pca_plot(
                        kind="protein",
                        header=_to_bool(protein_pca.get("header"), True),
                        legend=_to_bool(protein_pca.get("legend"), True),
                        plot_dim=_to_str(protein_pca.get("plotDim"), "2D"),
                        add_ellipses=_to_bool(protein_pca.get("addEllipses"), False),
                        dot_size=_to_int(protein_pca.get("dotSize"), 5, minimum=1, maximum=60),
                        width_cm=_to_float(protein_pca.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                        height_cm=protein_pca_height_cm,
                        dpi=_to_int(protein_pca.get("dpi"), 300, minimum=72, maximum=1200),
                    ),
                    fallback_title="Protein PCA Plot",
                    warnings=warnings,
                )
            ),
        )
        protein_abundance_height_cm = _to_float(protein_abundance.get("heightCm"), 10.0, minimum=4.0, maximum=60.0)
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.7",
            title="Abundance Plot",
            description=None,
            general_comment_key="AbundanceProt",
            text_entries=text_entries,
            text_key="AbundanceProt",
            content_html=_safe_png(
                renderer=lambda: qc_abundance_plot(
                    kind="protein",
                    header=_to_bool(protein_abundance.get("header"), True),
                    legend=_to_bool(protein_abundance.get("legend"), True),
                    condition="All Conditions",
                    width_cm=_to_float(protein_abundance.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                    height_cm=protein_abundance_height_cm,
                    dpi=_to_int(protein_abundance.get("dpi"), 300, minimum=72, maximum=1200),
                ),
                fallback_title="Protein Abundance Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.8",
            title="Correlation Plot",
            description=None,
            general_comment_key="CorrelationProt",
            text_entries=text_entries,
            text_key="CorrelationProt",
            content_html=_safe_png(
                renderer=lambda: qc_correlation_plot(
                    kind="protein",
                    method=_to_str(protein_correlation.get("method"), "Matrix"),
                    include_id=_to_bool(protein_correlation.get("includeId"), False),
                    full_range=_to_bool(protein_correlation.get("fullRange"), False),
                    width_cm=_to_float(protein_correlation.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                    height_cm=_to_float(protein_correlation.get("heightCm"), 16.0, minimum=4.0, maximum=60.0),
                    dpi=_to_int(protein_correlation.get("dpi"), 400, minimum=72, maximum=1200),
                ),
                fallback_title="Protein Correlation Plot",
                warnings=warnings,
            ),
        )

        if protein_volcano_entries:
            _append_plot_section(
                html_parts=html_parts,
                section_id=f"{protein_block}.9",
                title="Volcano Plot",
                description=None,
                general_comment_key="VolcanoProt",
                text_entries=text_entries,
                text_key="VolcanoProt",
                content_html=_volcano_block_html(
                    kind="protein",
                    entries=protein_volcano_entries,
                    warnings=warnings,
                ),
            )

    if phospho_block is not None:
        html_parts.append(f"<h1>{phospho_block} Phosphosite Level</h1>")
        phospho_coverage = _module_settings(report_context, "phospho", "coverage")
        phospho_hist = _module_settings(report_context, "phospho", "hist")
        phospho_box = _module_settings(report_context, "phospho", "box")
        phospho_cv = _module_settings(report_context, "phospho", "cv")
        phospho_pca = _module_settings(report_context, "phospho", "pca")
        phospho_abundance = _module_settings(report_context, "phospho", "abundance")
        phospho_correlation = _module_settings(report_context, "phospho", "correlation")

        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.1",
            title="Overview Phosphosites",
            description=None,
            general_comment_key="Phossite",
            text_entries=text_entries,
            text_key="Phossite",
            content_html=_safe_png(
                renderer=lambda: phosphosite_plot_png(),
                fallback_title="Phosphosite Overview Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.2",
            title="Coverage Plot (Number)",
            description=None,
            general_comment_key="Coverage(Number)Phos",
            text_entries=text_entries,
            text_key="Coverage(Number)Phos",
            content_html=(
                _safe_png(
                    renderer=lambda: phospho_coverage_png(mode="Normal"),
                    fallback_title="Phospho Coverage Number Plot",
                    warnings=warnings,
                )
                + _safe_table_html(
                    renderer=lambda: qc_coverage_table(
                        kind="phospho",
                        summary=_to_bool(phospho_coverage.get("summary"), False),
                    ),
                    title="Coverage Summary Table",
                    fallback_title="Phospho Coverage Summary Table",
                    warnings=warnings,
                )
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.3",
            title="Coverage Plot (Quality)",
            description=None,
            general_comment_key="Coverage(Quality)Phos",
            text_entries=text_entries,
            text_key="Coverage(Quality)Phos",
            content_html=_safe_png(
                renderer=lambda: phospho_coverage_png(mode="Summary"),
                fallback_title="Phospho Coverage Quality Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.4",
            title="Missing Value Plot",
            description=None,
            general_comment_key="MissingValuePhos",
            text_entries=text_entries,
            text_key="MissingValuePhos",
            content_html=_safe_png(
                renderer=lambda: completeness_missing_value_plot(kind="phospho"),
                fallback_title="Phospho Missing Value Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.5",
            title="Histogram Intensity",
            description=None,
            general_comment_key="HistogramIntPhos",
            text_entries=text_entries,
            text_key="HistogramIntPhos",
            content_html=_safe_png(
                renderer=lambda: qc_intensity_histogram_plot(
                    kind="phospho",
                    header=_to_bool(phospho_hist.get("header"), True),
                    legend=_to_bool(phospho_hist.get("legend"), True),
                    width_cm=_to_float(phospho_hist.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                    height_cm=_to_float(phospho_hist.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                    dpi=_to_int(phospho_hist.get("dpi"), 300, minimum=72, maximum=1200),
                ),
                fallback_title="Phospho Histogram Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.6",
            title="Boxplot Intensity",
            description=None,
            general_comment_key="BoxplotIntPhos",
            text_entries=text_entries,
            text_key="BoxplotIntPhos",
            content_html=(
                _safe_png(
                    renderer=lambda: qc_boxplot_plot(
                        kind="phospho",
                        mode=_to_str(phospho_box.get("mode"), "Mean"),
                        outliers=_to_bool(phospho_box.get("outliers"), False),
                        include_id=_to_bool(phospho_box.get("includeId"), False),
                        header=_to_bool(phospho_box.get("header"), True),
                        legend=_to_bool(phospho_box.get("legend"), True),
                        text=_to_bool(phospho_box.get("text"), False),
                        text_size=_to_int(phospho_box.get("textSize"), 9, minimum=6, maximum=24),
                        width_cm=_to_float(phospho_box.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                        height_cm=_to_float(phospho_box.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                        dpi=_to_int(phospho_box.get("dpi"), 300, minimum=72, maximum=1200),
                    ),
                    fallback_title="Phospho Boxplot",
                    warnings=warnings,
                )
                + _safe_table_html(
                    renderer=lambda: qc_boxplot_table(
                        kind="phospho",
                        mode=_to_str(phospho_box.get("mode"), "Mean"),
                    ),
                    title="Boxplot Summary Table",
                    fallback_title="Phospho Boxplot Summary Table",
                    warnings=warnings,
                )
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.7",
            title="Coefficient of Variation Plot",
            description=None,
            general_comment_key="CovPhos",
            text_entries=text_entries,
            text_key="CovPhos",
            content_html=(
                _safe_png(
                    renderer=lambda: qc_cv_plot(
                        kind="phospho",
                        outliers=_to_bool(phospho_cv.get("outliers"), False),
                        header=_to_bool(phospho_cv.get("header"), True),
                        legend=_to_bool(phospho_cv.get("legend"), True),
                        text=_to_bool(phospho_cv.get("text"), False),
                        text_size=_to_int(phospho_cv.get("textSize"), 9, minimum=6, maximum=24),
                        width_cm=_to_float(phospho_cv.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                        height_cm=_to_float(phospho_cv.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                        dpi=_to_int(phospho_cv.get("dpi"), 300, minimum=72, maximum=1200),
                    ),
                    fallback_title="Phospho CV Plot",
                    warnings=warnings,
                )
                + _safe_table_html(
                    renderer=lambda: qc_cv_table(kind="phospho"),
                    title="Coefficient of Variation Summary Table",
                    fallback_title="Phospho CV Summary Table",
                    warnings=warnings,
                )
            ),
        )
        phospho_pca_height_cm = _to_float(phospho_pca.get("heightCm"), 10.0, minimum=4.0, maximum=60.0)
        phospho_pca_interactive = _to_str(phospho_pca.get("type"), "Normal").lower() == "interactive"
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.8",
            title="PCA Plot",
            description=None,
            general_comment_key="PCAPhos",
            text_entries=text_entries,
            text_key="PCAPhos",
            content_html=(
                _safe_plotly(
                    renderer=lambda: qc_pca_interactive_html(
                        kind="phospho",
                        header=_to_bool(phospho_pca.get("header"), True),
                        legend=_to_bool(phospho_pca.get("legend"), True),
                        plot_dim=_to_str(phospho_pca.get("plotDim"), "2D"),
                        add_ellipses=_to_bool(phospho_pca.get("addEllipses"), False),
                        dot_size=_to_int(phospho_pca.get("dotSize"), 5, minimum=1, maximum=60),
                        width_cm=_to_float(phospho_pca.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                        height_cm=phospho_pca_height_cm,
                    ),
                    fallback_title="Phospho PCA Interactive Plot",
                    warnings=warnings,
                    height_px=_interactive_height_px(phospho_pca_height_cm),
                )
                if phospho_pca_interactive
                else _safe_png(
                    renderer=lambda: qc_pca_plot(
                        kind="phospho",
                        header=_to_bool(phospho_pca.get("header"), True),
                        legend=_to_bool(phospho_pca.get("legend"), True),
                        plot_dim=_to_str(phospho_pca.get("plotDim"), "2D"),
                        add_ellipses=_to_bool(phospho_pca.get("addEllipses"), False),
                        dot_size=_to_int(phospho_pca.get("dotSize"), 5, minimum=1, maximum=60),
                        width_cm=_to_float(phospho_pca.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                        height_cm=phospho_pca_height_cm,
                        dpi=_to_int(phospho_pca.get("dpi"), 300, minimum=72, maximum=1200),
                    ),
                    fallback_title="Phospho PCA Plot",
                    warnings=warnings,
                )
            ),
        )
        phospho_abundance_height_cm = _to_float(phospho_abundance.get("heightCm"), 10.0, minimum=4.0, maximum=60.0)
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.9",
            title="Abundance Plot",
            description=None,
            general_comment_key="AbundancePhos",
            text_entries=text_entries,
            text_key="AbundancePhos",
            content_html=_safe_png(
                renderer=lambda: qc_abundance_plot(
                    kind="phospho",
                    header=_to_bool(phospho_abundance.get("header"), True),
                    legend=_to_bool(phospho_abundance.get("legend"), True),
                    condition="All Conditions",
                    width_cm=_to_float(phospho_abundance.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                    height_cm=phospho_abundance_height_cm,
                    dpi=_to_int(phospho_abundance.get("dpi"), 300, minimum=72, maximum=1200),
                ),
                fallback_title="Phospho Abundance Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.10",
            title="Correlation Plot",
            description=None,
            general_comment_key="CorrelationPhos",
            text_entries=text_entries,
            text_key="CorrelationPhos",
            content_html=_safe_png(
                renderer=lambda: qc_correlation_plot(
                    kind="phospho",
                    method=_to_str(phospho_correlation.get("method"), "Matrix"),
                    include_id=_to_bool(phospho_correlation.get("includeId"), False),
                    full_range=_to_bool(phospho_correlation.get("fullRange"), False),
                    width_cm=_to_float(phospho_correlation.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                    height_cm=_to_float(phospho_correlation.get("heightCm"), 16.0, minimum=4.0, maximum=60.0),
                    dpi=_to_int(phospho_correlation.get("dpi"), 400, minimum=72, maximum=1200),
                ),
                fallback_title="Phospho Correlation Plot",
                warnings=warnings,
            ),
        )

        if phospho_volcano_entries:
            _append_plot_section(
                html_parts=html_parts,
                section_id=f"{phospho_block}.11",
                title="Volcano Plot",
                description=None,
                general_comment_key="VolcanoPhos",
                text_entries=text_entries,
                text_key="VolcanoPhos",
                content_html=_volcano_block_html(
                    kind="phospho",
                    entries=phospho_volcano_entries,
                    warnings=warnings,
                ),
            )

    # Keep translated features only for now; dedicated log section is intentionally omitted.
    if warnings:
        html_parts.append("<h2>Report Warnings</h2>")
        for warning in warnings:
            html_parts.append(f"<div class='warn'>{html.escape(warning)}</div>")

    html_parts.append("</body></html>")
    html_doc = "\n".join(html_parts)
    return SummaryReportResponse(
        fileName=_file_name_from_title(title),
        html=html_doc,
        warnings=warnings,
    )
