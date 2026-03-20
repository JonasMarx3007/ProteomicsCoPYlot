from __future__ import annotations

import base64
import io
import html
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import pandas as pd

from app.schemas.stats import VolcanoRequest
from app.schemas.summary import (
    SummaryOverviewResponse,
    SummaryReportRequest,
    SummarySectionInfo,
    SummaryTableBlock,
)
from app.services.annotation_store import get_annotation
from app.services.dataset_store import get_current_dataset
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

DEFAULT_REPORT_TITLE = "Proteomics CoPYlot Summary Report"
DEFAULT_REPORT_FILENAME = "proteomicscopylot_summary_report.html"


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
    if not cleaned.lower().endswith(".html"):
        cleaned = f"{cleaned}.html"
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


def _html_text_block(text: str, *, css_class: str = "report-copy") -> str:
    cleaned = _sanitize_text(text)
    if not cleaned:
        return ""
    parts = []
    for paragraph in cleaned.splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        parts.append(f'<p class="{css_class}">{html.escape(paragraph)}</p>')
    return "".join(parts)


def _png_data_url(image_bytes: bytes) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _table_html(frame: pd.DataFrame) -> str:
    if frame.empty:
        return '<div class="empty-state">No rows available.</div>'

    safe = frame.copy()
    safe.columns = [str(column) for column in safe.columns]
    safe = safe.fillna("")
    for column in safe.columns:
        safe[column] = safe[column].map(lambda value: "" if value is None else str(value).replace("\n", " "))
    return safe.to_html(index=False, escape=True, classes="report-table", border=0)


def _section_anchor(spec: ReportSectionSpec) -> str:
    return f"section-{spec.key}"


def _render_title_block(*, title: str, author: str) -> str:
    author_line = f"<p><strong>Author:</strong> {html.escape(author)}</p>" if author else ""
    return f"""
    <section class="hero">
      <div class="hero-card">
        <div class="hero-kicker">Proteomics CoPYlot</div>
        <h1>{html.escape(title)}</h1>
        {author_line}
        <p><strong>Date:</strong> {datetime.now().strftime("%Y-%m-%d")}</p>
      </div>
    </section>
    """


def _render_contents_block(*, sections: list[ReportSectionSpec], include_metadata: bool) -> str:
    items: list[str] = []
    for spec in sections:
        items.append(
            f'<li><a href="#{_section_anchor(spec)}">{html.escape(spec.group)} - {html.escape(spec.title)}</a></li>'
        )
    if include_metadata:
        items.append('<li><a href="#metadata-appendix">Appendix - Metadata Tables</a></li>')
    if not items:
        items.append("<li>No report sections are available yet.</li>")

    return f"""
    <section class="report-panel">
      <h2>Table of Contents</h2>
      <ol class="toc-list">
        {''.join(items)}
      </ol>
    </section>
    """


def _render_introduction_block(text: str) -> str:
    cleaned = _sanitize_text(text)
    if not cleaned:
        return ""
    return f"""
    <section class="report-panel">
      <div class="section-label">Summary</div>
      <h2>Introduction</h2>
      {_html_text_block(cleaned)}
    </section>
    """


def _render_section_block(
    spec: ReportSectionSpec,
    *,
    image_bytes: bytes,
    above_note: str,
    below_note: str,
) -> str:
    return f"""
    <section class="report-panel" id="{_section_anchor(spec)}">
      <div class="section-label">{html.escape(spec.group)}</div>
      <h2>{html.escape(spec.title)}</h2>
      {_html_text_block(spec.description)}
      {_html_text_block(above_note, css_class="report-note")}
      <div class="plot-frame">
        <img src="{_png_data_url(image_bytes)}" alt="{html.escape(spec.title)}" />
      </div>
      {_html_text_block(below_note, css_class="report-note")}
    </section>
    """


def _render_metadata_block(blocks: list[SummaryTableBlock]) -> str:
    rendered_blocks: list[str] = []
    for block in blocks:
        if not block.available:
            continue
        frame = pd.DataFrame(block.rows)
        rendered_blocks.append(
            f"""
            <section class="report-panel">
              <div class="section-label">Appendix</div>
              <h2>{html.escape(block.title)}</h2>
              <div class="table-wrap">
                {_table_html(frame)}
              </div>
            </section>
            """
        )

    if not rendered_blocks:
        rendered_blocks.append(
            """
            <section class="report-panel">
              <div class="section-label">Appendix</div>
              <h2>Metadata Tables</h2>
              <div class="empty-state">No metadata tables are available yet.</div>
            </section>
            """
        )

    return f'<div id="metadata-appendix">{"".join(rendered_blocks)}</div>'


def _render_warning_block(warnings: list[str]) -> str:
    if not warnings:
        return ""
    items = "".join(f"<li>{html.escape(warning)}</li>" for warning in warnings)
    return f"""
    <section class="report-panel warning-panel">
      <div class="section-label">Notes</div>
      <h2>Report Notes</h2>
      <ul class="warning-list">{items}</ul>
    </section>
    """


def generate_summary_html(payload: SummaryReportRequest) -> tuple[bytes, str]:
    title = _sanitize_text(payload.title, DEFAULT_REPORT_TITLE)
    author = _sanitize_text(payload.author, "Unknown Author")
    notes = payload.notes or {}
    sections = _available_sections()
    warnings: list[str] = []
    rendered_sections: list[str] = []

    for spec in sections:
        note = notes.get(spec.key)
        above = note.above if note is not None else ""
        below = note.below if note is not None else ""
        try:
            rendered_sections.append(
                _render_section_block(
                    spec,
                    image_bytes=spec.render(),
                    above_note=above,
                    below_note=below,
                )
            )
        except Exception as exc:
            warnings.append(f"Skipped {spec.group} - {spec.title}: {exc}")

    if not rendered_sections:
        rendered_sections.append(
            """
            <section class="report-panel">
              <div class="section-label">Summary</div>
              <h2>No Sections Available</h2>
              <div class="empty-state">
                Load datasets and generate annotations where needed to populate the summary report.
              </div>
            </section>
            """
        )

    metadata_html = ""
    if payload.includeMetadataTables:
        metadata_html = _render_metadata_block(_summary_table_blocks())

    html_report = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(title)}</title>
    <style>
      :root {{
        color-scheme: light;
        --page-bg: #f4f7fb;
        --card-bg: #ffffff;
        --border: #d9e1ea;
        --text: #102033;
        --muted: #526273;
        --accent: #1d4ed8;
        --accent-soft: #dbeafe;
        --warning-bg: #fff7ed;
        --warning-border: #fdba74;
      }}
      * {{
        box-sizing: border-box;
      }}
      body {{
        margin: 0;
        font-family: "Segoe UI", Arial, sans-serif;
        background:
          radial-gradient(circle at top right, rgba(29, 78, 216, 0.1), transparent 28rem),
          linear-gradient(180deg, #f8fbff 0%, var(--page-bg) 100%);
        color: var(--text);
      }}
      .page {{
        width: min(1100px, calc(100vw - 32px));
        margin: 0 auto;
        padding: 32px 0 64px;
      }}
      .hero-card,
      .report-panel {{
        background: var(--card-bg);
        border: 1px solid var(--border);
        border-radius: 24px;
        box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
      }}
      .hero-card {{
        padding: 32px;
      }}
      .hero-kicker,
      .section-label {{
        display: inline-block;
        padding: 6px 10px;
        border-radius: 999px;
        background: var(--accent-soft);
        color: var(--accent);
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}
      .hero h1 {{
        margin: 16px 0 20px;
        font-size: clamp(32px, 5vw, 46px);
        line-height: 1.05;
      }}
      .hero p {{
        margin: 8px 0;
        color: var(--muted);
      }}
      .report-panel {{
        margin-top: 24px;
        padding: 24px;
      }}
      .report-panel h2 {{
        margin: 14px 0 12px;
        font-size: 28px;
        line-height: 1.15;
      }}
      .report-copy,
      .report-note {{
        margin: 12px 0;
        line-height: 1.65;
      }}
      .report-copy {{
        color: var(--muted);
      }}
      .report-note {{
        color: #334155;
      }}
      .toc-list,
      .warning-list {{
        margin: 16px 0 0;
        padding-left: 22px;
      }}
      .toc-list li,
      .warning-list li {{
        margin: 10px 0;
        line-height: 1.5;
      }}
      .toc-list a {{
        color: var(--accent);
        text-decoration: none;
      }}
      .toc-list a:hover {{
        text-decoration: underline;
      }}
      .plot-frame {{
        margin-top: 18px;
        padding: 18px;
        border: 1px solid var(--border);
        border-radius: 18px;
        background: #fbfdff;
      }}
      .plot-frame img {{
        display: block;
        width: 100%;
        height: auto;
      }}
      .table-wrap {{
        margin-top: 16px;
        overflow: auto;
        border: 1px solid var(--border);
        border-radius: 18px;
      }}
      table.report-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
      }}
      table.report-table th,
      table.report-table td {{
        padding: 10px 12px;
        border-bottom: 1px solid #e5ebf2;
        text-align: left;
        vertical-align: top;
        white-space: nowrap;
      }}
      table.report-table th {{
        position: sticky;
        top: 0;
        background: #eff6ff;
      }}
      .empty-state {{
        padding: 18px;
        border: 1px dashed var(--border);
        border-radius: 16px;
        background: #f8fafc;
        color: var(--muted);
      }}
      .warning-panel {{
        background: var(--warning-bg);
        border-color: var(--warning-border);
      }}
      @media print {{
        body {{
          background: white;
        }}
        .page {{
          width: 100%;
          padding: 0;
        }}
        .hero-card,
        .report-panel {{
          box-shadow: none;
          break-inside: avoid;
        }}
      }}
    </style>
  </head>
  <body>
    <main class="page">
      {_render_title_block(title=title, author=author)}
      {_render_introduction_block(payload.introduction)}
      {_render_contents_block(sections=sections, include_metadata=payload.includeMetadataTables)}
      {''.join(rendered_sections)}
      {metadata_html}
      {_render_warning_block(warnings)}
    </main>
  </body>
</html>
"""

    return html_report.encode("utf-8"), _report_filename(title)
