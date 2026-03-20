from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from datetime import datetime
from textwrap import wrap
from typing import Callable

import pandas as pd

from app.schemas.stats import VolcanoRequest
from app.schemas.summary import (
    SummaryLogRow,
    SummaryOverviewResponse,
    SummaryReportRequest,
    SummarySectionInfo,
    SummaryTableBlock,
)
from app.services.annotation_store import get_annotation
from app.services.dataset_store import get_all_current_datasets, get_current_dataset
from app.services.functions import (
    completeness_missing_value_plot,
    qc_abundance_plot,
    qc_boxplot_plot,
    qc_correlation_plot,
    qc_coverage_plot,
    qc_cv_plot,
    qc_intensity_histogram_plot,
    qc_pca_plot,
)
from app.services.metadata_upload_store import get_uploaded_metadata
from app.services.peptide_metadata_store import get_peptide_metadata
from app.services.peptide_tools import (
    peptide_missed_cleavage_plot,
    peptide_modification_plot,
    peptide_rt_plot,
)
from app.services.phospho_tools import (
    phospho_coverage_png,
    phospho_distribution_png,
    phospho_sty_png,
    phosphosite_plot_png,
)
from app.services.stats_tools import run_volcano, statistical_options

A4_SIZE = (8.27, 11.69)
DEFAULT_REPORT_TITLE = "Proteomics CoPYlot Summary Report"
DEFAULT_REPORT_FILENAME = "proteomicscopylot_summary_report.pdf"


@dataclass(frozen=True)
class ReportSectionSpec:
    key: str
    title: str
    group: str
    description: str
    is_available: Callable[[], bool]
    render: Callable[[], bytes]


def _get_plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _sanitize_text(value: str | None, fallback: str = "") -> str:
    return (value or "").strip() or fallback


def _safe_frame_rows(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return []
    return frame.where(pd.notna(frame), None).to_dict(orient="records")


def _report_filename(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", title.strip()).strip("._")
    if not cleaned:
        cleaned = "proteomicscopylot_summary_report"
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned


def _annotation_metadata_frame(kind: str) -> tuple[pd.DataFrame, str | None]:
    annotation = get_annotation(kind)  # type: ignore[arg-type]
    if annotation is not None and not annotation.metadata.empty:
        return annotation.metadata.copy(), None

    uploaded = get_uploaded_metadata(kind)  # type: ignore[arg-type]
    if uploaded is not None and not uploaded.frame.empty:
        return uploaded.frame.copy(), "Showing uploaded metadata because annotation has not been generated yet."

    return pd.DataFrame(), "No metadata available yet."


def _peptide_metadata_frame() -> tuple[pd.DataFrame, str | None]:
    metadata = get_peptide_metadata()
    if metadata is not None and not metadata.frame.empty:
        return metadata.frame.copy(), None
    return pd.DataFrame(), "No peptide metadata available yet."


def _summary_table_blocks() -> list[SummaryTableBlock]:
    protein_frame, protein_message = _annotation_metadata_frame("protein")
    phospho_frame, phospho_message = _annotation_metadata_frame("phospho")
    peptide_frame, peptide_message = _peptide_metadata_frame()

    return [
        SummaryTableBlock(
            key="proteinMetadata",
            title="Protein Metadata",
            rows=_safe_frame_rows(protein_frame),
            rowCount=int(len(protein_frame)),
            available=not protein_frame.empty,
            message=protein_message,
        ),
        SummaryTableBlock(
            key="phosphoMetadata",
            title="Phospho Metadata",
            rows=_safe_frame_rows(phospho_frame),
            rowCount=int(len(phospho_frame)),
            available=not phospho_frame.empty,
            message=phospho_message,
        ),
        SummaryTableBlock(
            key="peptideMetadata",
            title="Peptide Metadata",
            rows=_safe_frame_rows(peptide_frame),
            rowCount=int(len(peptide_frame)),
            available=not peptide_frame.empty,
            message=peptide_message,
        ),
    ]


def _append_log_row(rows: list[SummaryLogRow], variable: str, value: object) -> None:
    rows.append(SummaryLogRow(variable=variable, value=str(value)))


def _summary_log_rows() -> list[SummaryLogRow]:
    current = get_all_current_datasets()
    rows: list[SummaryLogRow] = []

    for kind in ("protein", "phospho"):
        stored = current.get(kind)
        annotation = get_annotation(kind)  # type: ignore[arg-type]
        uploaded = get_uploaded_metadata(kind)  # type: ignore[arg-type]

        _append_log_row(rows, f"{kind}_dataset_loaded", stored is not None)
        if stored is not None and hasattr(stored, "filename") and hasattr(stored, "frame"):
            _append_log_row(rows, f"{kind}_filename", stored.filename)
            _append_log_row(rows, f"{kind}_rows", len(stored.frame))
            _append_log_row(rows, f"{kind}_columns", len(stored.frame.columns))

        _append_log_row(rows, f"{kind}_uploaded_metadata_loaded", uploaded is not None)
        if uploaded is not None:
            _append_log_row(rows, f"{kind}_uploaded_metadata_filename", uploaded.filename)
            _append_log_row(rows, f"{kind}_uploaded_metadata_rows", len(uploaded.frame))

        _append_log_row(rows, f"{kind}_annotation_ready", annotation is not None)
        if annotation is not None:
            _append_log_row(rows, f"{kind}_metadata_rows", len(annotation.metadata))
            _append_log_row(rows, f"{kind}_sample_count", int(annotation.metadata["sample"].nunique()))
            _append_log_row(rows, f"{kind}_condition_count", int(annotation.metadata["condition"].nunique()))
            _append_log_row(rows, f"{kind}_metadata_source", annotation.metadata_source)
            _append_log_row(rows, f"{kind}_auto_detected", annotation.auto_detected)
            _append_log_row(rows, f"{kind}_is_log2_transformed", annotation.is_log2_transformed)
            _append_log_row(rows, f"{kind}_filter_min_present", annotation.filter_config.minPresent)
            _append_log_row(rows, f"{kind}_filter_mode", annotation.filter_config.mode)
            _append_log_row(rows, f"{kind}_log2_rows", len(annotation.log2_data))
            _append_log_row(rows, f"{kind}_filtered_rows", len(annotation.filtered_data))
            _append_log_row(rows, f"{kind}_warning_count", len(annotation.warnings))
            gene_names_available = (
                "GeneNames" in annotation.filtered_data.columns
                or "GeneNames" in annotation.log2_data.columns
                or "GeneNames" in annotation.source_data.columns
            )
            _append_log_row(rows, f"{kind}_gene_names_available", gene_names_available)

    peptide = current.get("peptide")
    peptide_metadata = get_peptide_metadata()
    _append_log_row(rows, "peptide_dataset_loaded", peptide is not None)
    if peptide is not None and hasattr(peptide, "path"):
        _append_log_row(rows, "peptide_path", peptide.path)
    _append_log_row(rows, "peptide_metadata_loaded", peptide_metadata is not None)
    if peptide_metadata is not None:
        _append_log_row(rows, "peptide_metadata_filename", peptide_metadata.filename)
        _append_log_row(rows, "peptide_metadata_rows", len(peptide_metadata.frame))

    _append_log_row(rows, "available_report_sections", len(_available_sections()))
    return sorted(rows, key=lambda row: row.variable)


def _has_table_dataset(kind: str) -> bool:
    return get_current_dataset(kind) is not None


def _has_peptide_dataset() -> bool:
    return get_current_dataset("peptide") is not None


def _has_peptide_metadata() -> bool:
    metadata = get_peptide_metadata()
    return metadata is not None and not metadata.frame.empty


def _has_condition_pair(kind: str) -> bool:
    try:
        options = statistical_options(kind)  # type: ignore[arg-type]
    except Exception:
        return False
    return len(options.availableConditions) >= 2


def _default_volcano_request(kind: str) -> VolcanoRequest:
    options = statistical_options(kind)  # type: ignore[arg-type]
    if len(options.availableConditions) < 2:
        raise ValueError("At least two conditions are required for volcano plots.")

    identifier = "workflow"
    for option in options.availableIdentifiers:
        if option.key == "genes":
            identifier = "genes"
            break

    return VolcanoRequest(
        kind=kind,  # type: ignore[arg-type]
        condition1=options.availableConditions[0],
        condition2=options.availableConditions[1],
        identifier=identifier,  # type: ignore[arg-type]
        pValueThreshold=0.05,
        log2fcThreshold=1.0,
        testType="unpaired",
        useUncorrected=False,
        highlightTerms=[],
    )


def _volcano_png(kind: str) -> bytes:
    plt = _get_plt()
    payload = _default_volcano_request(kind)
    result = run_volcano(payload)
    frame = pd.DataFrame(result.rows)
    if frame.empty:
        raise ValueError("No volcano rows available for the report.")

    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    color_mapping = {
        "Downregulated": "#2563eb",
        "Not significant": "#94a3b8",
        "Upregulated": "#dc2626",
    }
    for significance, color in color_mapping.items():
        subset = frame[frame["significance"] == significance]
        if subset.empty:
            continue
        ax.scatter(
            pd.to_numeric(subset["log2FC"], errors="coerce"),
            pd.to_numeric(subset["neg_log10_adj_pval"], errors="coerce"),
            s=12,
            alpha=0.75,
            color=color,
            label=significance,
        )

    ax.axvline(1.0, color="black", linestyle="--", linewidth=1)
    ax.axvline(-1.0, color="black", linestyle="--", linewidth=1)
    ax.axhline(-math.log10(0.05), color="black", linestyle="--", linewidth=1)
    ax.set_title(f"{payload.condition1} vs {payload.condition2}")
    ax.set_xlabel(f"log2 fold change ({payload.condition2} - {payload.condition1})")
    ax.set_ylabel("-log10 adj. p-value")
    ax.legend(loc="best")
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    buffer.seek(0)
    return buffer.getvalue()


SECTION_SPECS: tuple[ReportSectionSpec, ...] = (
    ReportSectionSpec(
        key="peptideRt",
        title="Retention Time Plot",
        group="Peptide Level",
        description="Retention time agreement across the peptide dataset.",
        is_available=_has_peptide_dataset,
        render=lambda: peptide_rt_plot(method="Hexbin Plot", add_line=False, bins=1000, header=True, width_cm=20, height_cm=15, dpi=100),
    ),
    ReportSectionSpec(
        key="peptideModification",
        title="Modification Plot",
        group="Peptide Level",
        description="Observed peptide modification counts across the loaded peptide metadata.",
        is_available=lambda: _has_peptide_dataset() and _has_peptide_metadata(),
        render=lambda: peptide_modification_plot(include_id=False, header=True, legend=True, width_cm=25, height_cm=15, dpi=100),
    ),
    ReportSectionSpec(
        key="peptideMissedCleavage",
        title="Missed Cleavage Plot",
        group="Peptide Level",
        description="Missed-cleavage distribution across peptide-level samples.",
        is_available=lambda: _has_peptide_dataset() and _has_peptide_metadata(),
        render=lambda: peptide_missed_cleavage_plot(include_id=False, text=True, text_size=8, header=True, width_cm=25, height_cm=15, dpi=100),
    ),
    ReportSectionSpec(
        key="proteinMissingValue",
        title="Missing Value Plot",
        group="Protein Level",
        description="Distribution of missing protein measurements by sample.",
        is_available=lambda: _has_table_dataset("protein"),
        render=lambda: completeness_missing_value_plot(kind="protein", bin_count=0, header=True, text=True, text_size=8, color="#2563eb", width_cm=20, height_cm=10, dpi=300),
    ),
    ReportSectionSpec(
        key="proteinCoverage",
        title="Coverage Plot",
        group="Protein Level",
        description="Protein identification counts across all protein samples.",
        is_available=lambda: _has_table_dataset("protein"),
        render=lambda: qc_coverage_plot(kind="protein", include_id=False, header=True, legend=True, summary=False, text=False, text_size=9, width_cm=20, height_cm=10, dpi=300),
    ),
    ReportSectionSpec(
        key="proteinHistogram",
        title="Histogram Intensity",
        group="Protein Level",
        description="Distribution of protein intensities across samples.",
        is_available=lambda: _has_table_dataset("protein"),
        render=lambda: qc_intensity_histogram_plot(kind="protein", header=True, legend=True, width_cm=20, height_cm=10, dpi=300),
    ),
    ReportSectionSpec(
        key="proteinBoxplot",
        title="Boxplot Intensity",
        group="Protein Level",
        description="Protein intensity distribution by condition.",
        is_available=lambda: _has_table_dataset("protein"),
        render=lambda: qc_boxplot_plot(kind="protein", mode="Mean", outliers=False, include_id=False, header=True, legend=True, text=False, text_size=9, width_cm=20, height_cm=10, dpi=300),
    ),
    ReportSectionSpec(
        key="proteinCv",
        title="Cov Plot",
        group="Protein Level",
        description="Coefficient of variation across the protein dataset.",
        is_available=lambda: _has_table_dataset("protein"),
        render=lambda: qc_cv_plot(kind="protein", outliers=False, header=True, legend=True, width_cm=20, height_cm=10, dpi=300),
    ),
    ReportSectionSpec(
        key="proteinPca",
        title="Principal Component Analysis",
        group="Protein Level",
        description="Principal-component overview of the protein samples.",
        is_available=lambda: _has_table_dataset("protein"),
        render=lambda: qc_pca_plot(kind="protein", header=True, legend=True, plot_dim="2D", add_ellipses=False, dot_size=5, width_cm=20, height_cm=10, dpi=300),
    ),
    ReportSectionSpec(
        key="proteinAbundance",
        title="Abundance Plot",
        group="Protein Level",
        description="Condition-level abundance rank plot for proteins.",
        is_available=lambda: _has_table_dataset("protein"),
        render=lambda: qc_abundance_plot(kind="protein", header=True, legend=True, condition="All Conditions", width_cm=20, height_cm=10, dpi=300),
    ),
    ReportSectionSpec(
        key="proteinCorrelation",
        title="Correlation Plot",
        group="Protein Level",
        description="Sample-to-sample protein correlation heatmap.",
        is_available=lambda: _has_table_dataset("protein"),
        render=lambda: qc_correlation_plot(kind="protein", method="Matrix", include_id=False, full_range=False, width_cm=20, height_cm=16, dpi=400),
    ),
    ReportSectionSpec(
        key="proteinVolcano",
        title="Volcano Plot (First Condition Pair)",
        group="Protein Level",
        description="Default protein volcano comparison using the first two annotated conditions.",
        is_available=lambda: _has_condition_pair("protein"),
        render=lambda: _volcano_png("protein"),
    ),
    ReportSectionSpec(
        key="phosphoMissingValue",
        title="Missing Value Plot",
        group="Phospho Level",
        description="Distribution of missing phosphosite measurements by sample.",
        is_available=lambda: _has_table_dataset("phospho"),
        render=lambda: completeness_missing_value_plot(kind="phospho", bin_count=0, header=True, text=True, text_size=8, color="#2563eb", width_cm=20, height_cm=10, dpi=300),
    ),
    ReportSectionSpec(
        key="phosphoCoverage",
        title="Coverage Plot",
        group="Phospho Level",
        description="Phosphosite identification counts across phospho samples.",
        is_available=lambda: _has_table_dataset("phospho"),
        render=lambda: qc_coverage_plot(kind="phospho", include_id=False, header=True, legend=True, summary=False, text=False, text_size=9, width_cm=20, height_cm=10, dpi=300),
    ),
    ReportSectionSpec(
        key="phosphoHistogram",
        title="Histogram Intensity",
        group="Phospho Level",
        description="Distribution of phosphosite intensities across samples.",
        is_available=lambda: _has_table_dataset("phospho"),
        render=lambda: qc_intensity_histogram_plot(kind="phospho", header=True, legend=True, width_cm=20, height_cm=10, dpi=300),
    ),
    ReportSectionSpec(
        key="phosphoBoxplot",
        title="Boxplot Intensity",
        group="Phospho Level",
        description="Phosphosite intensity distribution by condition.",
        is_available=lambda: _has_table_dataset("phospho"),
        render=lambda: qc_boxplot_plot(kind="phospho", mode="Mean", outliers=False, include_id=False, header=True, legend=True, text=False, text_size=9, width_cm=20, height_cm=10, dpi=300),
    ),
    ReportSectionSpec(
        key="phosphoCv",
        title="Cov Plot",
        group="Phospho Level",
        description="Coefficient of variation across the phospho dataset.",
        is_available=lambda: _has_table_dataset("phospho"),
        render=lambda: qc_cv_plot(kind="phospho", outliers=False, header=True, legend=True, width_cm=20, height_cm=10, dpi=300),
    ),
    ReportSectionSpec(
        key="phosphoPca",
        title="Principal Component Analysis",
        group="Phospho Level",
        description="Principal-component overview of the phospho samples.",
        is_available=lambda: _has_table_dataset("phospho"),
        render=lambda: qc_pca_plot(kind="phospho", header=True, legend=True, plot_dim="2D", add_ellipses=False, dot_size=5, width_cm=20, height_cm=10, dpi=300),
    ),
    ReportSectionSpec(
        key="phosphoAbundance",
        title="Abundance Plot",
        group="Phospho Level",
        description="Condition-level abundance rank plot for phosphosites.",
        is_available=lambda: _has_table_dataset("phospho"),
        render=lambda: qc_abundance_plot(kind="phospho", header=True, legend=True, condition="All Conditions", width_cm=20, height_cm=10, dpi=300),
    ),
    ReportSectionSpec(
        key="phosphoCorrelation",
        title="Correlation Plot",
        group="Phospho Level",
        description="Sample-to-sample phosphosite correlation heatmap.",
        is_available=lambda: _has_table_dataset("phospho"),
        render=lambda: qc_correlation_plot(kind="phospho", method="Matrix", include_id=False, full_range=False, width_cm=20, height_cm=16, dpi=400),
    ),
    ReportSectionSpec(
        key="phosphositePlot",
        title="Phosphosite Plot",
        group="Phospho-specific",
        description="Distribution of phosphosite counts per phosphoprotein.",
        is_available=lambda: _has_table_dataset("phospho"),
        render=lambda: phosphosite_plot_png(cutoff=0.0, color="#87CEEB", width_cm=15, height_cm=10, dpi=100),
    ),
    ReportSectionSpec(
        key="phosphoSpecificCoverage",
        title="Phosphosite Coverage Plot",
        group="Phospho-specific",
        description="Class I and non-Class I phosphosite coverage across conditions.",
        is_available=lambda: _has_table_dataset("phospho"),
        render=lambda: phospho_coverage_png(include_id=False, header=True, legend=True, mode="Normal", color_class_i="#2563eb", color_not_class_i="#f59e0b", width_cm=20, height_cm=10, dpi=300, conditions=[]),
    ),
    ReportSectionSpec(
        key="phosphoDistribution",
        title="Phosphosite Distribution",
        group="Phospho-specific",
        description="Observed phosphosite-per-protein distribution.",
        is_available=lambda: _has_table_dataset("phospho"),
        render=lambda: phospho_distribution_png(cutoff=0.0, header=True, color="#87CEEB", width_cm=20, height_cm=15, dpi=300),
    ),
    ReportSectionSpec(
        key="phosphoSty",
        title="STY Plot",
        group="Phospho-specific",
        description="STY residue composition across localized phosphosites.",
        is_available=lambda: _has_table_dataset("phospho"),
        render=lambda: phospho_sty_png(header=True, width_cm=17.78, height_cm=11.43, dpi=140),
    ),
    ReportSectionSpec(
        key="phosphoVolcano",
        title="Volcano Plot (First Condition Pair)",
        group="Phospho Level",
        description="Default phospho volcano comparison using the first two annotated conditions.",
        is_available=lambda: _has_condition_pair("phospho"),
        render=lambda: _volcano_png("phospho"),
    ),
)


def _available_sections() -> list[ReportSectionSpec]:
    return [spec for spec in SECTION_SPECS if spec.is_available()]


def build_summary_overview() -> SummaryOverviewResponse:
    sections = _available_sections()
    warnings: list[str] = []
    if not sections:
        warnings.append("Load datasets to unlock report sections.")

    return SummaryOverviewResponse(
        tables=_summary_table_blocks(),
        logRows=_summary_log_rows(),
        availableSections=[
            SummarySectionInfo(
                key=spec.key,
                title=spec.title,
                group=spec.group,
                description=spec.description,
            )
            for spec in sections
        ],
        warnings=warnings,
        suggestedFilename=DEFAULT_REPORT_FILENAME,
    )


def _draw_paragraph(
    fig,
    text: str,
    *,
    top: float,
    x: float = 0.08,
    width: int = 98,
    fontsize: int = 10,
    color: str = "#334155",
) -> float:
    cleaned = _sanitize_text(text)
    if not cleaned:
        return top

    lines: list[str] = []
    for paragraph in cleaned.splitlines():
        wrapped = wrap(paragraph.strip() or " ", width=width)
        lines.extend(wrapped or [" "])
        lines.append("")
    if lines and not lines[-1]:
        lines.pop()

    fig.text(x, top, "\n".join(lines), ha="left", va="top", fontsize=fontsize, color=color)
    return top - (0.024 * max(1, len(lines)))


def _add_title_page(pdf, plt, *, title: str, author: str) -> None:
    fig = plt.figure(figsize=A4_SIZE)
    fig.patch.set_facecolor("white")
    fig.text(0.08, 0.9, title, fontsize=24, fontweight="bold", color="#0f172a")
    fig.text(0.08, 0.84, f"Author: {author}", fontsize=12, color="#334155")
    fig.text(0.08, 0.8, f"Date: {datetime.now().strftime('%Y-%m-%d')}", fontsize=12, color="#334155")
    fig.text(0.08, 0.76, "Generated with Proteomics CoPYlot", fontsize=12, color="#475569")
    fig.text(
        0.08,
        0.62,
        "This report combines the currently available translated pipelines into a single PDF appendix.",
        fontsize=12,
        color="#334155",
    )
    fig.text(0.08, 0.1, "Proteomics CoPYlot", fontsize=10, color="#94a3b8")
    pdf.savefig(fig)
    plt.close(fig)


def _add_text_page(pdf, plt, *, title: str, body: str) -> None:
    fig = plt.figure(figsize=A4_SIZE)
    fig.patch.set_facecolor("white")
    fig.text(0.08, 0.95, title, fontsize=18, fontweight="bold", color="#0f172a")
    _draw_paragraph(fig, body, top=0.9, width=100, fontsize=11)
    pdf.savefig(fig)
    plt.close(fig)


def _add_contents_page(
    pdf,
    plt,
    *,
    sections: list[ReportSectionSpec],
    include_metadata: bool,
    include_log: bool,
) -> None:
    lines = []
    for index, spec in enumerate(sections, start=1):
        lines.append(f"{index}. {spec.group} - {spec.title}")
    if include_metadata:
        lines.append(f"{len(lines) + 1}. Appendix - Metadata Tables")
    if include_log:
        lines.append(f"{len(lines) + 1}. Appendix - System Log")
    body = "\n".join(lines) if lines else "No report sections are available yet."
    _add_text_page(pdf, plt, title="Table of Contents", body=body)


def _add_image_page(
    pdf,
    plt,
    *,
    title: str,
    description: str,
    image_bytes: bytes,
    above_note: str,
    below_note: str,
) -> None:
    fig = plt.figure(figsize=A4_SIZE)
    fig.patch.set_facecolor("white")
    fig.text(0.08, 0.96, title, fontsize=18, fontweight="bold", color="#0f172a")
    _draw_paragraph(fig, description, top=0.92, width=100, fontsize=10)
    if above_note.strip():
        _draw_paragraph(fig, above_note, top=0.83, width=100, fontsize=9, color="#475569")

    image = plt.imread(io.BytesIO(image_bytes), format="png")
    bottom = 0.18 if below_note.strip() else 0.1
    ax = fig.add_axes([0.08, bottom, 0.84, 0.58])
    ax.imshow(image)
    ax.axis("off")

    if below_note.strip():
        _draw_paragraph(fig, below_note, top=0.14, width=100, fontsize=9, color="#475569")

    pdf.savefig(fig)
    plt.close(fig)


def _table_page_slices(frame: pd.DataFrame, rows_per_page: int = 24) -> list[pd.DataFrame]:
    if frame.empty:
        return [frame]
    return [frame.iloc[start:start + rows_per_page].copy() for start in range(0, len(frame), rows_per_page)]


def _truncate_cell(value: object, limit: int = 48) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ")
    if len(text) <= limit:
        return text
    return f"{text[:limit - 3]}..."


def _add_table_pages(pdf, plt, *, title: str, frame: pd.DataFrame) -> None:
    safe = frame.copy()
    if safe.empty:
        _add_text_page(pdf, plt, title=title, body="No rows available.")
        return

    safe.columns = [str(column) for column in safe.columns]
    safe = safe.fillna("")
    safe = safe.applymap(_truncate_cell)
    page_chunks = _table_page_slices(safe)

    for index, chunk in enumerate(page_chunks, start=1):
        fig = plt.figure(figsize=A4_SIZE)
        fig.patch.set_facecolor("white")
        heading = title if len(page_chunks) == 1 else f"{title} ({index}/{len(page_chunks)})"
        fig.text(0.08, 0.95, heading, fontsize=18, fontweight="bold", color="#0f172a")
        ax = fig.add_axes([0.05, 0.06, 0.9, 0.84])
        ax.axis("off")
        table = ax.table(
            cellText=chunk.values.tolist(),
            colLabels=chunk.columns.tolist(),
            loc="center",
            cellLoc="left",
            colLoc="left",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(7 if len(chunk.columns) <= 8 else 6)
        table.scale(1, 1.35)
        pdf.savefig(fig)
        plt.close(fig)


def generate_summary_pdf(payload: SummaryReportRequest) -> tuple[bytes, str]:
    plt = _get_plt()
    title = _sanitize_text(payload.title, DEFAULT_REPORT_TITLE)
    author = _sanitize_text(payload.author, "Unknown Author")
    notes = payload.notes or {}
    sections = _available_sections()
    warnings: list[str] = []

    buffer = io.BytesIO()
    from matplotlib.backends.backend_pdf import PdfPages

    with PdfPages(buffer) as pdf:
        _add_title_page(pdf, plt, title=title, author=author)

        if _sanitize_text(payload.introduction):
            _add_text_page(pdf, plt, title="Introduction", body=payload.introduction)

        _add_contents_page(
            pdf,
            plt,
            sections=sections,
            include_metadata=payload.includeMetadataTables,
            include_log=payload.includeLogAppendix,
        )

        if not sections:
            _add_text_page(
                pdf,
                plt,
                title="No Sections Available",
                body="Load datasets and generate annotations where needed to populate the summary report.",
            )

        for spec in sections:
            note = notes.get(spec.key)
            above = note.above if note is not None else ""
            below = note.below if note is not None else ""
            try:
                _add_image_page(
                    pdf,
                    plt,
                    title=f"{spec.group} - {spec.title}",
                    description=spec.description,
                    image_bytes=spec.render(),
                    above_note=above,
                    below_note=below,
                )
            except Exception as exc:
                warnings.append(f"Skipped {spec.group} - {spec.title}: {exc}")

        if payload.includeMetadataTables:
            for block in _summary_table_blocks():
                if block.available:
                    _add_table_pages(pdf, plt, title=block.title, frame=pd.DataFrame(block.rows))

        if payload.includeLogAppendix:
            log_frame = pd.DataFrame(
                [{"Variable": row.variable, "Value": row.value} for row in _summary_log_rows()]
            )
            _add_table_pages(pdf, plt, title="System Log", frame=log_frame)

        if warnings:
            _add_text_page(pdf, plt, title="Report Notes", body="\n".join(warnings))

        info = pdf.infodict()
        info["Title"] = title
        info["Author"] = author
        info["Creator"] = "Proteomics CoPYlot"
        info["CreationDate"] = datetime.now()

    buffer.seek(0)
    return buffer.getvalue(), _report_filename(title)
