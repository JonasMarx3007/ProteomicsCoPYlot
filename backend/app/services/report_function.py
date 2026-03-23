from __future__ import annotations

import base64
import html
import re
from datetime import datetime
from typing import Callable

import pandas as pd

from app.schemas.stats import VolcanoRequest
from app.schemas.summary import SummaryReportRequest, SummaryReportResponse
from app.services.annotation_store import get_annotation
from app.services.dataset_store import get_current_dataset
from app.services.functions import (
    completeness_missing_value_plot,
    phospho_coverage_png,
    phosphosite_plot_png,
    qc_abundance_interactive_html,
    qc_boxplot_plot,
    qc_correlation_plot,
    qc_coverage_plot,
    qc_cv_plot,
    qc_intensity_histogram_plot,
    qc_pca_interactive_html,
)
from app.services.peptide_tools import (
    peptide_missed_cleavage_plot,
    peptide_modification_plot,
    peptide_rt_plot,
)
from app.services.stats_tools import volcano_html

VERSION = "Proteomics CoPYlot V1.0.0"


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


def _plotly_to_iframe(plot_html: str, height_px: int = 620) -> str:
    srcdoc = html.escape(plot_html, quote=True)
    return (
        f"<iframe srcdoc=\"{srcdoc}\" "
        f"style='width:100%;height:{max(360, int(height_px))}px;border:1px solid #d6d6d6;border-radius:8px;' "
        "loading='lazy'></iframe>"
    )


def _table_to_html(title: str, frame: pd.DataFrame) -> str:
    safe = frame.copy().where(pd.notna(frame), "")
    table_html = safe.to_html(index=False, border=0, justify="left")
    return (
        f"<h3>{html.escape(title)}</h3>"
        "<div style='max-height:360px;overflow:auto;border:1px solid #d6d6d6;border-radius:8px;padding:8px;margin-bottom:16px;'>"
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
    height_px: int = 620,
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


def _append_plot_section(
    *,
    html_parts: list[str],
    section_id: str,
    title: str,
    description: str,
    text_entries: dict[str, str],
    text_key: str,
    content_html: str,
) -> None:
    html_parts.append(f"<h2>{html.escape(section_id)} {html.escape(title)}</h2>")
    html_parts.append(f"<p>{html.escape(description)}</p>")
    above = _custom_text(text_entries, f"{text_key}Above")
    if above:
        html_parts.append(above)
    html_parts.append(content_html)
    below = _custom_text(text_entries, f"{text_key}Below")
    if below:
        html_parts.append(below)


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
                f"<p>{peptide_block}. Peptide Level Plots</p>",
                f"<p>{peptide_block}.1 Retention Time Plot</p>",
                f"<p>{peptide_block}.2 Modification Plot</p>",
                f"<p>{peptide_block}.3 Missed Cleavage Plot</p>",
            ]
        )
    if protein_block is not None:
        html_parts.extend(
            [
                f"<p>{protein_block}. Protein Level Plots</p>",
                f"<p>{protein_block}.1 Coverage Plot</p>",
                f"<p>{protein_block}.2 Missing Value Plot</p>",
                f"<p>{protein_block}.3 Histogram Intensity</p>",
                f"<p>{protein_block}.4 Boxplot Intensity</p>",
                f"<p>{protein_block}.5 Coefficient of Variation Plot</p>",
                f"<p>{protein_block}.6 PCA Plot (Interactive)</p>",
                f"<p>{protein_block}.7 Abundance Plot (Interactive)</p>",
                f"<p>{protein_block}.8 Correlation Plot</p>",
                f"<p>{protein_block}.9 Volcano Plot (Interactive)</p>",
            ]
        )
    if phospho_block is not None:
        html_parts.extend(
            [
                f"<p>{phospho_block}. Phosphosite Level Plots</p>",
                f"<p>{phospho_block}.1 Overview Phosphosites</p>",
                f"<p>{phospho_block}.2 Coverage Plot (Number)</p>",
                f"<p>{phospho_block}.3 Coverage Plot (Quality)</p>",
                f"<p>{phospho_block}.4 Missing Value Plot</p>",
                f"<p>{phospho_block}.5 Histogram Intensity</p>",
                f"<p>{phospho_block}.6 Boxplot Intensity</p>",
                f"<p>{phospho_block}.7 Coefficient of Variation Plot</p>",
                f"<p>{phospho_block}.8 PCA Plot (Interactive)</p>",
                f"<p>{phospho_block}.9 Abundance Plot (Interactive)</p>",
                f"<p>{phospho_block}.10 Correlation Plot</p>",
                f"<p>{phospho_block}.11 Volcano Plot (Interactive)</p>",
            ]
        )

    html_parts.append("<h2>Metadata Tables</h2>")
    if protein_annotation is not None and not protein_annotation.metadata.empty:
        html_parts.append(_table_to_html("Protein Metadata", protein_annotation.metadata))
    else:
        html_parts.append("<p>Protein metadata not available.</p>")
    if phospho_annotation is not None and not phospho_annotation.metadata.empty:
        html_parts.append(_table_to_html("Phospho Metadata", phospho_annotation.metadata))
    else:
        html_parts.append("<p>Phospho metadata not available.</p>")

    if peptide_block is not None:
        html_parts.append(f"<h1>{peptide_block} Peptide Level</h1>")

        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{peptide_block}.1",
            title="Retention Time Plot",
            description="Retention time alignment quality across peptide measurements.",
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
            section_id=f"{peptide_block}.2",
            title="Modification Plot",
            description="Distribution of peptide modifications across samples.",
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
            section_id=f"{peptide_block}.3",
            title="Missed Cleavage Plot",
            description="Percentage distribution of missed cleavages per sample.",
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

        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.1",
            title="Coverage Plot",
            description="Protein identification coverage across samples.",
            text_entries=text_entries,
            text_key="CoverageProt",
            content_html=_safe_png(
                renderer=lambda: qc_coverage_plot(kind="protein"),
                fallback_title="Protein Coverage Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.2",
            title="Missing Value Plot",
            description="Distribution of missing values per protein.",
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
            description="Protein intensity distribution quality check.",
            text_entries=text_entries,
            text_key="HistogramIntProt",
            content_html=_safe_png(
                renderer=lambda: qc_intensity_histogram_plot(kind="protein"),
                fallback_title="Protein Histogram Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.4",
            title="Boxplot Intensity",
            description="Protein intensity spread by condition.",
            text_entries=text_entries,
            text_key="BoxplotIntProt",
            content_html=_safe_png(
                renderer=lambda: qc_boxplot_plot(kind="protein"),
                fallback_title="Protein Boxplot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.5",
            title="Coefficient of Variation Plot",
            description="CV distribution for reproducibility assessment.",
            text_entries=text_entries,
            text_key="CovProt",
            content_html=_safe_png(
                renderer=lambda: qc_cv_plot(kind="protein"),
                fallback_title="Protein CV Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.6",
            title="PCA Plot (Interactive)",
            description="Interactive PCA representation of sample clustering.",
            text_entries=text_entries,
            text_key="PCAProt",
            content_html=_safe_plotly(
                renderer=lambda: qc_pca_interactive_html(kind="protein"),
                fallback_title="Protein PCA Interactive Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.7",
            title="Abundance Plot (Interactive)",
            description="Interactive abundance ranking by condition.",
            text_entries=text_entries,
            text_key="AbundanceProt",
            content_html=_safe_plotly(
                renderer=lambda: qc_abundance_interactive_html(kind="protein"),
                fallback_title="Protein Abundance Interactive Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.8",
            title="Correlation Plot",
            description="Sample-to-sample correlation overview.",
            text_entries=text_entries,
            text_key="CorrelationProt",
            content_html=_safe_png(
                renderer=lambda: qc_correlation_plot(kind="protein"),
                fallback_title="Protein Correlation Plot",
                warnings=warnings,
            ),
        )

        protein_conditions = (
            protein_annotation.metadata["condition"].dropna().astype(str).drop_duplicates().tolist()
            if protein_annotation is not None
            else []
        )
        volcano_content = (
            _safe_plotly(
                renderer=lambda: volcano_html(
                    VolcanoRequest(
                        kind="protein",
                        condition1=protein_conditions[0],
                        condition2=protein_conditions[1],
                        identifier="workflow",
                        pValueThreshold=0.05,
                        log2fcThreshold=1.0,
                        testType="unpaired",
                        useUncorrected=False,
                        highlightTerms=[],
                    )
                ),
                fallback_title="Protein Volcano Plot",
                warnings=warnings,
            )
            if len(protein_conditions) >= 2
            else (
                "<div class='warn'>Volcano plot skipped: at least two protein conditions are required.</div>"
            )
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.9",
            title="Volcano Plot (Interactive)",
            description="Differential abundance visualization between two conditions.",
            text_entries=text_entries,
            text_key="VolcanoProt",
            content_html=volcano_content,
        )

    if phospho_block is not None:
        html_parts.append(f"<h1>{phospho_block} Phosphosite Level</h1>")

        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.1",
            title="Overview Phosphosites",
            description="Overview count of phosphosite terms.",
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
            description="Phosphosite coverage by condition and class.",
            text_entries=text_entries,
            text_key="Coverage(Number)Phos",
            content_html=_safe_png(
                renderer=lambda: phospho_coverage_png(mode="Normal"),
                fallback_title="Phospho Coverage Number Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.3",
            title="Coverage Plot (Quality)",
            description="Quality-focused phosphosite coverage summary.",
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
            description="Missing-value profile for phosphosite measurements.",
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
            description="Phosphosite intensity distribution quality check.",
            text_entries=text_entries,
            text_key="HistogramIntPhos",
            content_html=_safe_png(
                renderer=lambda: qc_intensity_histogram_plot(kind="phospho"),
                fallback_title="Phospho Histogram Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.6",
            title="Boxplot Intensity",
            description="Phosphosite intensity spread by condition.",
            text_entries=text_entries,
            text_key="BoxplotIntPhos",
            content_html=_safe_png(
                renderer=lambda: qc_boxplot_plot(kind="phospho"),
                fallback_title="Phospho Boxplot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.7",
            title="Coefficient of Variation Plot",
            description="CV distribution for phosphosite reproducibility.",
            text_entries=text_entries,
            text_key="CovPhos",
            content_html=_safe_png(
                renderer=lambda: qc_cv_plot(kind="phospho"),
                fallback_title="Phospho CV Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.8",
            title="PCA Plot (Interactive)",
            description="Interactive PCA representation for phosphosite data.",
            text_entries=text_entries,
            text_key="PCAPhos",
            content_html=_safe_plotly(
                renderer=lambda: qc_pca_interactive_html(kind="phospho"),
                fallback_title="Phospho PCA Interactive Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.9",
            title="Abundance Plot (Interactive)",
            description="Interactive phosphosite abundance ranking.",
            text_entries=text_entries,
            text_key="AbundancePhos",
            content_html=_safe_plotly(
                renderer=lambda: qc_abundance_interactive_html(kind="phospho"),
                fallback_title="Phospho Abundance Interactive Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.10",
            title="Correlation Plot",
            description="Phosphosite sample correlation overview.",
            text_entries=text_entries,
            text_key="CorrelationPhos",
            content_html=_safe_png(
                renderer=lambda: qc_correlation_plot(kind="phospho"),
                fallback_title="Phospho Correlation Plot",
                warnings=warnings,
            ),
        )

        phospho_conditions = (
            phospho_annotation.metadata["condition"].dropna().astype(str).drop_duplicates().tolist()
            if phospho_annotation is not None
            else []
        )
        phospho_volcano = (
            _safe_plotly(
                renderer=lambda: volcano_html(
                    VolcanoRequest(
                        kind="phospho",
                        condition1=phospho_conditions[0],
                        condition2=phospho_conditions[1],
                        identifier="workflow",
                        pValueThreshold=0.05,
                        log2fcThreshold=1.0,
                        testType="unpaired",
                        useUncorrected=False,
                        highlightTerms=[],
                    )
                ),
                fallback_title="Phospho Volcano Plot",
                warnings=warnings,
            )
            if len(phospho_conditions) >= 2
            else (
                "<div class='warn'>Volcano plot skipped: at least two phospho conditions are required.</div>"
            )
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.11",
            title="Volcano Plot (Interactive)",
            description="Differential phosphosite abundance between two conditions.",
            text_entries=text_entries,
            text_key="VolcanoPhos",
            content_html=phospho_volcano,
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
