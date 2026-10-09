from __future__ import annotations

from app.services.method_references import cite
from app.services.html_security import GENERATED_HTML_META
from app.services.notebook_report import report_plot, report_table, record_sample_mapping

import base64
import logging
import math
import json
import html
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Callable

import pandas as pd

from app.app_version import APP_VERSION
from app.schemas.stats import VolcanoRequest
from app.schemas.summary import (
    SummaryReportContext,
    SummaryReportRequest,
    SummaryReportResponse,
    SummaryVolcanoEntry,
)
from app.services.column_labels import HIDDEN_TABLE_COLUMNS, display_labels
from app.services.annotation_store import get_annotation
from app.services.dataset_store import get_current_dataset
from app.services.peptide_metadata_store import get_peptide_metadata
from app.services.completeness_tools import completeness_excluded_feature_count
from app.services.completeness_tools import (
    completeness_missing_value_plot,
    completeness_missing_value_plot_peptide,
)
from app.services.phospho_tools import (
    phospho_coverage_png,
    phosphosite_plot_png,
)
from app.services.plot_images import (
    qc_abundance_interactive_html,
    qc_abundance_plot,
    qc_boxplot_plot,
    qc_correlation_plot,
    qc_coverage_plot,
    qc_cv_plot,
    qc_intensity_histogram_plot,
    qc_pca_interactive_html,
    qc_pca_plot,
    qc_peptide_coverage_plot,
)
from app.services.functions import (
    entity_labels_for_kind,
    sample_label_frame,)
from app.services.plot_images import qc_pca_feature_summary
from app.services.functions import resolve_feature_scaling
from app.services.plot_styling import migrate_advanced_plot_settings
from app.services.peptide_tools import (
    normalize_protease,
    peptide_missed_cleavage_plot,
    peptide_modification_plot,
    peptide_rt_plot,
)
from app.services.stats_tools import run_volcano, volcano_html, volcano_png
from app.services.table_functions import (
    qc_boxplot_table,
    qc_coverage_table,
    qc_cv_table,
)

LOGGER = logging.getLogger(__name__)

# One version number for the application, read the same way everywhere. Held as
# its own literal here, the report kept printing whatever the constant said long
# after the application had moved on.
VERSION = f"Proteomics CoPYlot V{APP_VERSION}"

def _report_comment_candidates() -> list[Path]:
    here = Path(__file__).resolve()
    project_root = here.parents[3]
    sibling_root = project_root.parent / "proteomics-copylot"
    local_appdata = os.getenv("LOCALAPPDATA", "").strip()

    roots: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    if local_appdata:
        roots.append(Path(local_appdata) / "proteomics-copylot")
    roots.extend([project_root, sibling_root])

    candidates = [root / "data" / "report" / "report_general_comments.json" for root in roots]
    unique_candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique_candidates.append(candidate)
    return unique_candidates


def _load_general_comments() -> dict[str, list[str]]:
    for candidate in _report_comment_candidates():
        if not candidate.exists():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception as exc:
            LOGGER.error("Failed to parse %s: %s", candidate, exc)
            raise ValueError(
                "Failed to parse report_general_comments.json. "
                "The file location and parse error are recorded in the server log."
            ) from exc
        if not isinstance(payload, dict):
            LOGGER.error("Report comments file is not a JSON object: %s", candidate)
            raise ValueError(
                "report_general_comments.json must contain a JSON object."
            )
        normalized: dict[str, list[str]] = {}
        for key, value in payload.items():
            key_text = str(key).strip()
            if not key_text:
                continue
            if not isinstance(value, list):
                raise ValueError(
                    f"Report comments entry '{key_text}' must be a JSON array."
                )
            normalized[key_text] = [str(item).strip() for item in value if str(item).strip()]
        return normalized

    searched = ", ".join(str(path) for path in _report_comment_candidates())
    LOGGER.error("report_general_comments.json not found. Searched: %s", searched)
    raise ValueError(
        "Could not find report_general_comments.json. "
        "The searched locations are recorded in the server log."
    )


GENERAL_COMMENTS = _load_general_comments()


def _escape_multiline(text: str) -> str:
    return html.escape(text).replace("\n", "<br>")


def _file_name_from_title(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", title.strip()).strip("_")
    if not slug:
        slug = "CoPYlot_report"
    return f"{slug}.html"


def _png_to_html(png_bytes: bytes) -> str:
    encoded = base64.b64encode(png_bytes).decode("utf-8")
    image = f"<img src='data:image/png;base64,{encoded}' style='width:100%;height:auto;border:1px solid #d6d6d6;border-radius:8px;'/>"
    notice = getattr(png_bytes, "notice", "")
    return image + (f"<p>{html.escape(notice)}</p>" if notice else "")


def _plotly_to_iframe(plot_html: str, height_px: int = 740) -> str:
    srcdoc = html.escape(plot_html, quote=True)
    return (
        f"<iframe sandbox='allow-scripts allow-downloads' srcdoc=\"{srcdoc}\" "
        f"style='display:block;width:100%;height:{max(520, int(height_px))}px;border:1px solid #d6d6d6;border-radius:8px;' "
        "loading='lazy'></iframe>"
    )


def _table_to_html(title: str, frame: pd.DataFrame) -> str:
    # The frame's columns are the data contract (CSV, API, notebooks); the
    # reader gets the display label, and numbers rounded to two decimals.
    shown = frame.drop(columns=[c for c in HIDDEN_TABLE_COLUMNS if c in frame.columns])
    safe = shown.rename(columns=display_labels(shown.columns))
    safe = safe.where(pd.notna(safe), "")
    table_html = safe.to_html(index=False, border=0, justify="left", float_format=lambda v: f"{v:.2f}")
    return (
        f"<h3>{html.escape(title)}</h3>"
        "<div style='max-height:320px;overflow:auto;border:1px solid #d6d6d6;border-radius:8px;padding:8px;margin-bottom:16px;'>"
        f"{table_html}"
        "</div>"
    )


def _sample_mapping_rows_html(frame: pd.DataFrame, *, show_pairs: bool) -> str:
    header = ["Plot label", "Original sample name", "Condition"]
    if show_pairs:
        header.append("Pair")
    head = "".join(f"<th>{html.escape(name)}</th>" for name in header)

    body_rows: list[str] = []
    for row in frame.itertuples(index=False):
        cells = [
            f"<td class='map-label'>{html.escape(str(row.label))}</td>",
            # The original run name is the point of the table, so it is never
            # shortened: it wraps inside its cell instead of being clipped or
            # pushing the table into horizontal scroll.
            f"<td class='map-name'>{html.escape(str(row.sample))}</td>",
            f"<td>{html.escape(str(row.condition))}</td>",
        ]
        if show_pairs:
            cells.append(f"<td>{html.escape(str(row.pair_id))}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    return (
        "<div class='map-scroll'>"
        f"<table class='map-table'><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
        "</div>"
    )


def _peptide_mapping_metadata() -> pd.DataFrame | None:
    """The metadata the peptide plots label with.

    Mirrors `peptide_tools._prepare_metadata`: a loaded protein dataset means the
    peptide plots reuse the protein annotation, and only a peptide-only session
    falls back to the dedicated peptide metadata.
    """
    if get_current_dataset("protein") is not None:
        stored = get_annotation("protein")
        if stored is None or stored.metadata.empty:
            return None
        return stored.metadata.copy()
    peptide_metadata = get_peptide_metadata()
    if peptide_metadata is None or peptide_metadata.frame.empty:
        return None
    return peptide_metadata.frame.copy()



def _report_failure(warnings: list[str], what: str, exc: Exception) -> None:
    """Note a part of the report that could not be built, for the person who asked.

    The message goes back to the page that requested the report, never into the
    report itself. A `ValueError` is a renderer refusing the request -- an
    empty selection, a comparison that cannot be formed -- so its message is
    the answer, as on the plot pages. Anything else is logged with its
    traceback and named only, because an exception string can carry a file
    path or a column of someone's data.
    """
    if isinstance(exc, ValueError) and str(exc).strip():
        warnings.append(f"{what} could not be rendered: {exc}")
        return
    LOGGER.exception("Report: %s could not be rendered", what)
    warnings.append(f"{what} could not be rendered.")

def _sample_mapping_html(
    *,
    levels: list[tuple[str, pd.DataFrame | None]],
    warnings: list[str],
) -> str:
    """Per-level tables mapping original run names to their plot labels."""
    parts: list[str] = [
        "<p>Plots label every sample as <code>condition_number</code>. "
        "The tables below give the original sample name behind each label, as it "
        "appears in the uploaded data.</p>"
    ]

    rendered: list[tuple[str, pd.DataFrame]] = []
    for level_name, metadata in levels:
        if metadata is None:
            continue
        try:
            mapping = sample_label_frame(metadata)
        except Exception as exc:  # pragma: no cover - defensive runtime behavior
            _report_failure(warnings, f"Sample mapping ({level_name})", exc)
            continue
        if mapping.empty:
            continue

        # Peptide plots reuse the protein annotation whenever a protein dataset
        # is loaded, so the two tables would be byte-identical. Name both above
        # one table rather than printing it twice.
        duplicate_of = next(
            (name for name, existing in rendered if existing.equals(mapping)),
            None,
        )
        if duplicate_of is not None:
            rendered = [
                (f"{name} and {level_name}" if name == duplicate_of else name, existing)
                for name, existing in rendered
            ]
            continue
        rendered.append((level_name, mapping))

    if not rendered:
        return (
            "<div style='padding:10px;border:1px solid #d6d6d6;background:#f8fafc;"
            "color:#475569;border-radius:8px;'>No annotated samples available.</div>"
        )

    for level_name, mapping in rendered:
        record_sample_mapping(level_name, mapping)
        show_pairs = bool((mapping["pair_id"].astype(str).str.strip() != "").any())
        parts.append(
            f"<h3>{html.escape(level_name)} "
            f"<span class='map-count'>({len(mapping)} samples)</span></h3>"
        )
        parts.append(_sample_mapping_rows_html(mapping, show_pairs=show_pairs))
    return "".join(parts)


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
        _report_failure(warnings, fallback_title, exc)
        return (
            "<div style='padding:10px;border:1px solid #f5c2c7;background:#f8d7da;color:#842029;border-radius:8px;'>"
            "Could not render this plot."
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
        _report_failure(warnings, fallback_title, exc)
        return (
            "<div style='padding:10px;border:1px solid #f5c2c7;background:#f8d7da;color:#842029;border-radius:8px;'>"
            "Could not render this interactive plot."
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
        _report_failure(warnings, fallback_title, exc)
        return (
            "<div style='padding:10px;border:1px solid #f5c2c7;background:#f8d7da;color:#842029;border-radius:8px;'>"
            "Could not render this summary table."
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
    comments_override: list[str] | None = None,
) -> None:
    html_parts.append(f"<h2>{html.escape(section_id)} {html.escape(title)}</h2>")
    comments: list[str] = []
    if comments_override is not None:
        comments.extend(comments_override)
    elif general_comment_key:
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


_BOXPLOT_NORMALIZATION_WORDS = {
    "median": "median-normalized log2",
    "quantile": "quantile-normalized log2",
    "vsn": "VSN-transformed",
}


def _boxplot_comment_paragraphs(kind: str, mode: str, general_comment_key: str) -> list[str]:
    """The boxplot section's text, written from the figure that was drawn.

    The general comment used to say "log2-raw intensities in a boxplot of each
    sample" whatever was rendered: the default mode draws one box per condition
    of per-feature means, the matrix is the normalized one, and zeros are only
    treated as missing for linear uploads. The first two sentences now follow
    the mode, the normalization (unmentioned when none was applied) and the
    upload scale; the interpretation sentences of the general comment follow.
    """
    singular, plural = entity_labels_for_kind(kind)
    annotation = get_annotation(kind)
    filter_config = getattr(annotation, "filter_config", None) if annotation is not None else None
    normalization = str(getattr(filter_config, "normalization", "none") or "none").strip().lower()
    scale = _BOXPLOT_NORMALIZATION_WORDS.get(normalization, "log2")
    if str(mode).strip().lower() == "single":
        depicted = f"Depicted are the {scale} {singular} intensities, one box per sample."
    else:
        depicted = (
            f"Depicted are the mean {scale} intensities of each {singular} within each condition, "
            "one box per condition; the per-sample mode shows each sample separately."
        )
    missing = "Missing values are not considered when creating the boxplots."
    uploaded_log2 = bool(getattr(annotation, "is_log2_transformed", False)) if annotation is not None else False
    if annotation is not None and not uploaded_log2:
        missing += " Zero intensities in the upload were treated as missing values."
    heading = f"{singular.capitalize()} intensity distributions - {depicted}"
    return [heading, missing, *GENERAL_COMMENTS.get(general_comment_key, [])[2:]]


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


def _advanced_settings_from_map(values: Mapping[str, Any], key: str) -> dict[str, Any] | None:
    item = values.get(key)
    if not isinstance(item, Mapping):
        return None
    # A report built from an older saved session carries the older keys.
    return migrate_advanced_plot_settings(dict(item))


def _global_advanced_settings(context: SummaryReportContext, key: str) -> dict[str, Any] | None:
    return _advanced_settings_from_map(context.advancedPlotSettingsByKey, key)


def _qc_advanced_settings(context: SummaryReportContext, tab: str) -> dict[str, Any] | None:
    return _advanced_settings_from_map(context.qcAdvancedSettingsByTab, tab)


def _completeness_advanced_settings(context: SummaryReportContext, tab: str) -> dict[str, Any] | None:
    return _advanced_settings_from_map(context.completenessAdvancedSettingsByTab, tab)


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


def _format_imputation_value(value: Any, *, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def _imputation_paragraphs(kind: str) -> list[str]:
    """How this level's missing values were imputed, as plain sentences.

    Shared so every block that describes this level's imputation -- a volcano's
    own statistics block and a PCA built on imputed data -- uses the same
    settings in the same words. There is no level-wide imputation note; the
    level preamble describes filtering and normalization only.
    """
    if kind not in {"protein", "phospho", "phosprot"}:
        return []

    q_value = "n/a"
    adjust_std = "n/a"
    down_shift = "n/a"
    width = "n/a"
    sample_wise = False
    imputation_mode = "none"
    annotation = get_annotation(kind)
    imputation = getattr(annotation, "imputation", None) if annotation is not None else None
    if imputation is not None:
        imputation_mode = str(getattr(imputation, "mode", "none")).strip().lower()
        # A configured-but-refused imputation keeps its mode on the annotation so
        # the refusal can be reported; describing it here would tell a reader
        # that values were imputed when they were not.
        if not bool(getattr(imputation, "applied", True)):
            imputation_mode = "none"
        if imputation_mode != "none":
            q_value = _format_imputation_value(getattr(imputation, "qValue", None))
            adjust_std = _format_imputation_value(getattr(imputation, "adjustStd", None))
            down_shift = _format_imputation_value(getattr(imputation, "downShift", None))
            width = _format_imputation_value(getattr(imputation, "width", None))
            sample_wise = bool(getattr(imputation, "sampleWise", False))
    if imputation_mode == "none":
        return []
    if imputation_mode not in {"numerical", "quantile"}:
        return [
            "The saved imputed matrix was restored, but its imputation method and parameters "
            "are unknown. The sampling distribution and draw scope cannot be reported."
        ]

    template_paragraphs = GENERAL_COMMENTS.get("Imputation", [])
    if imputation_mode == "numerical":
        rendered = [
            (
                "For analyses based on imputed data, missing values were sampled from a shifted normal "
                f"distribution with a downshift of {down_shift} standard deviations and width "
                f"{width} times the observed standard deviation ({cite('imputation_downshift')})."
            )
        ]
    elif template_paragraphs:
        rendered = [
            paragraph.replace("{qValue}", q_value).replace("{adjustStd}", adjust_std)
            .replace("{citation}", cite("imputation_quantile"))
            for paragraph in template_paragraphs
            if paragraph.strip()
        ]
    else:
        rendered = [
            (
                "For analyses based on imputed data, missing values were sampled from a normal "
                f"distribution centred on the q = {q_value} quantile of the observed values, with "
                f"{adjust_std} times their standard deviation ({cite('imputation_quantile')})."
            )
        ]

    # Random seeds are not reported: they carry no scientific information.
    rendered.append(
        f"The values were drawn with {'sample-wise' if sample_wise else 'dataset-wide'} parameters."
    )

    return rendered


_NORMALIZATION_REPORT_LABELS = {
    "none": (
        "None; sample loading and instrument drift are uncorrected unless the upload "
        "was already normalized upstream."
    ),
    "median": "Samples were median-centred on the log2 values (applied globally, before filtering).",
    "quantile": (
        "Samples were quantile-normalized on the log2 values (applied globally, before "
        f"filtering; {cite('quantile_normalization')})."
    ),
    "vsn": (
        f"Variance-stabilizing normalization (VSN, Bioconductor vsn; {cite('vsn')}) replaced "
        "the plain log2 transform (applied globally, before filtering). The CV and abundance "
        "plots use the unnormalized data, because VSN output is not on a linear intensity scale."
    ),
}

# A volcano plot is uninterpretable without the test that produced it. These
# labels name the design and the variance model, since the plot itself looks
# identical whichever was used.
_TEST_TYPE_REPORT_LABELS = {
    "unpaired": "unpaired two-sample t-test (pooled variance)",
    "unpaired_welch": f"unpaired two-sample t-test (Welch, unequal variance; {cite('welch_t')})",
    "paired": "paired t-test (on within-pair differences)",
}


def _normalization_description(annotation) -> str | None:
    """What was done to every sample's values, on its own line.

    Normalization is applied to the whole log2 matrix before any row filter, so
    it holds for every data source -- including plots that skip the filter.
    It used to be the last sentence of the filtering description, where a
    "Not applied to this plot" prefix made it read as not applied either.
    """
    if annotation is None:
        return None
    filter_config = getattr(annotation, "filter_config", None)
    if filter_config is None:
        return None
    normalization = str(getattr(filter_config, "normalization", "none")).strip().lower()
    if normalization in {"", "none"}:
        # Nothing to describe: "none" usually means the upload was normalized
        # upstream, and a line saying so reads as though a step was skipped.
        return None
    return _NORMALIZATION_REPORT_LABELS.get(normalization, f"{normalization}.")


def _filter_is_applied(filter_config) -> bool:
    """A threshold of zero keeps every row, so it is no filter at all.

    The default configuration is zero; a report that describes it as "rows with
    at least 0 valid values were retained" is true and useless. It is stated as
    no filtering, which is what requiring nothing means.
    """
    if filter_config is None:
        return False
    method = str(getattr(filter_config, "method", "at_least_n")).strip().lower()
    if method == "percentage":
        return float(getattr(filter_config, "minPercentage", 0.0) or 0.0) > 0.0
    return int(getattr(filter_config, "minPresent", 0) or 0) > 0


def _filter_description(annotation) -> str | None:
    """How this level's rows were filtered, as one sentence.

    Shared so the level-wide filtering note and a volcano's own statistics block
    cannot describe the same filtering differently.
    """
    if annotation is None:
        return None
    filter_config = getattr(annotation, "filter_config", None)
    if filter_config is None:
        return None
    if not _filter_is_applied(filter_config):
        return (
            f"No completeness filter was applied (all {len(annotation.source_data)} rows retained)."
        )

    method = str(getattr(filter_config, "method", "at_least_n")).strip().lower()
    mode = str(getattr(filter_config, "mode", "per_group")).strip().lower()
    if mode == "overall":
        scope = "across all annotated samples, independent of condition groups"
    elif mode == "in_at_least_one_group":
        scope = "in at least one condition group"
    else:
        scope = "in every condition group"
    if method == "percentage":
        threshold = float(getattr(filter_config, "minPercentage", 70.0))
        threshold_text = f"{threshold:.4f}".rstrip("0").rstrip(".")
        description = (
            f"Rows with at least {threshold_text}% completeness {scope} were retained"
        )
    else:
        threshold = int(getattr(filter_config, "minPresent", 0))
        description = (
            f"Rows with at least {threshold} valid values {scope} were retained"
        )
    description += (
        f" ({len(annotation.filtered_data)} of {len(annotation.source_data)} rows)."
    )
    return description


def _filter_not_applied_description(annotation) -> str | None:
    """The filtering line for a plot that ran on the unfiltered matrix.

    Says only what the reader needs here: that this plot skipped the filter,
    how many rows it therefore used, and how many the filtered sections keep --
    so the two counts side by side in one report are explained. The full filter
    recipe appears where the filter was actually applied.
    """
    if annotation is None or getattr(annotation, "filter_config", None) is None:
        return None
    if not _filter_is_applied(annotation.filter_config):
        return f"No completeness filter was applied (all {len(annotation.source_data)} rows retained)."
    return (
        f"Not applied to this plot; it uses all {len(annotation.source_data)} rows. "
        f"(The filtered matrix used by other sections of this report keeps "
        f"{len(annotation.filtered_data)} rows.)"
    )


IMPUTED_AS_OBSERVED_SENTENCE = (
    "Imputed values were treated as observed values in the statistical test: they count towards "
    "each group's size and the degrees of freedom. Counts distinguish measured-only, fully imputed and "
    "partially imputed values (n_measured__, n_fully_imputed__, n_partially_imputed__). For collapsed "
    "phosphoproteins this describes direct site contributions in each sample, not cross-sample centering effects. "
    "The n_imputed__<condition> and imputed_values "
    "columns count values with either fully or partially imputed contributions behind every feature."
)


def _imputation_html(
    *, kind: str, imputed: bool, subject: str = "this comparison", tested: bool = False
) -> str:
    """Whether this plot ran on imputed values, and on what settings.

    Shared by every block whose numbers depend on which matrix reached it, so
    two blocks can never describe the same imputation differently.
    """
    if not imputed:
        return (
            f"<p><strong>Imputation:</strong> Not applied; {subject} uses the "
            "non-imputed data.</p>"
        )
    paragraphs = _imputation_paragraphs(kind)
    if not paragraphs:
        return (
            "<p><strong>Imputation:</strong> Imputed data was selected, but no "
            "imputation settings are recorded for this dataset.</p>"
        )
    head, *rest = paragraphs
    if tested:
        rest = [*rest, IMPUTED_AS_OBSERVED_SENTENCE]
    return f"<p><strong>Imputation:</strong> {html.escape(head)}</p>" + "".join(
        f"<p>{html.escape(paragraph)}</p>" for paragraph in rest
    )


# The same words the selector offers, so a report and the panel that produced
# it name the matrix identically. Keep in step with DATA_SOURCE_LABELS in
# frontend/src/lib/types.ts.
_DATA_SOURCE_LABELS = {"data": "Unfiltered Data", "filtered": "Filtered Data", "imputed": "Imputed Data"}


def _report_data_source(value: Any) -> str:
    """A saved data source, or "data" when it is not one of the three.

    This used to be a boolean -- imputed or not -- which was right while those
    were the only two choices. Once `filtered` existed, every `filtered` plot
    was described as "Data", and the PCA was *re-rendered* on the unfiltered
    matrix to match the label.
    """
    text = _to_str(value, "data").strip().lower()
    return text if text in _DATA_SOURCE_LABELS else "data"


# What the two colours of the phosphosite coverage plots mean. The threshold is
# fixed, unlike the session's localization cutoff.
CLASS_I_SENTENCE = (
    f"Class I sites have a localization probability of at least 0.75 ({cite('localization_class_i')}); "
    "sites without a localization probability are shown as Unclassified."
)


def _localization_html(kind: str) -> str:
    """The phosphosite localization cutoff every phosphosite plot was drawn with."""
    if kind != "phospho":
        return ""
    from app.services.phospho_localization import localization_cutoff_description

    return f"<p><strong>Localization:</strong> {html.escape(localization_cutoff_description())}</p>"


def _data_provenance_html(
    *, kind: str, data_source: str, subject: str, completeness: str = "", tested: bool = False
) -> str:
    """Which matrix reached this plot: source, filtering and imputation.

    Every figure whose numbers depend on the rows and values behind it carries
    this block, in one voice and one order. A reader checking a single volcano
    or PCA should not have to scroll back to the level preamble to learn which
    rows survived the filter or whether the values were drawn rather than
    measured.

    `completeness` is for plots that drop rows of their own after the filter --
    a projection cannot use a feature with a missing value -- so the block can
    say how much of the matrix actually reached the figure.
    """
    source = _report_data_source(data_source)
    parts = [
        f"<p><strong>Data source:</strong> {_DATA_SOURCE_LABELS[source]}</p>"
    ]
    annotation = get_annotation(kind)
    normalization_description = _normalization_description(annotation)
    if normalization_description:
        parts.append(
            f"<p><strong>Normalization:</strong> {html.escape(normalization_description)}</p>"
        )
    filter_description = (
        _filter_not_applied_description(annotation)
        if source == "data"
        else _filter_description(annotation)
    )
    if filter_description:
        parts.append(
            f"<p><strong>Filtering:</strong> {html.escape(filter_description)}</p>"
        )
    parts.append(_localization_html(kind))
    parts.append(
        _imputation_html(kind=kind, imputed=source == "imputed", subject=subject, tested=tested)
    )
    if completeness:
        parts.append(f"<p><strong>Features used:</strong> {html.escape(completeness)}</p>")
    return "".join(parts)


def _completeness_exclusion_html(kind: str) -> str:
    """One line naming the rows the completeness page leaves out, if any.

    Features with no value in any selected sample carry no information about
    those samples' completeness; the missing-value plot, heatmap and tables all
    exclude them. Nothing is written when there are none.
    """
    try:
        excluded = int(completeness_excluded_feature_count(kind))
    except Exception:
        return ""
    if excluded <= 0:
        return ""
    noun = "feature was" if excluded == 1 else "features were"
    return (
        f"<p><strong>Features used:</strong> {excluded} {noun} excluded because they have "
        "no value in any selected sample; the plot and the completeness tables count the remaining rows.</p>"
    )


def _pca_completeness_description(kind: str, data_source: str) -> str:
    """How much of the selected matrix was complete and variable for PCA."""
    try:
        summary = qc_pca_feature_summary(kind, data_source=data_source)
        total = _to_int(summary.get("featuresTotal"), 0, minimum=0)
        used = _to_int(summary.get("featuresUsed"), 0, minimum=0)
    except Exception:
        # A level without an annotation, a source this project does not hold, or
        # a stubbed renderer: say nothing rather than a number from elsewhere.
        return ""
    if not total:
        return ""
    share = used / total * 100.0
    sentence = (
        f"{used:,} of {total:,} features ({share:.1f}%) were complete across every "
        "sample, showed variation and entered the projection"
    )
    if used < total:
        sentence += (
            f"; the remaining {total - used:,} were excluded because of missing "
            "values or no variation"
        )
    return sentence + "."


def _level_imputation_html(kind: str) -> str:
    """The imputation available at this level, stated with the filtering.

    Filtering and normalization were described in the level preamble while
    imputation was not, so a project that imputes at load time and whose report
    contains no volcano or imputed PCA never mentioned it at all.
    """
    if get_annotation(kind) is None:
        return ""
    paragraphs = _imputation_paragraphs(kind)
    if not paragraphs:
        return (
            "<p><strong>Imputation:</strong> No imputation was applied; every plot "
            "below states its own data source.</p>"
        )
    head, *rest = paragraphs
    return (
        f"<p><strong>Imputation:</strong> {html.escape(head)}</p>"
        + "".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in rest)
        + "<p>Imputed values are used only where a plot names Imputed Data as its "
        "source; every plot below states its own source.</p>"
    )


def _volcano_counts_html(
    *,
    entry: SummaryVolcanoEntry,
    kind: str,
    warnings: list[str],
) -> str:
    """How many entities the thresholds just described actually selected.

    Counted with `run_volcano`, the same routine the Statistical Analysis page
    reports, so the report cannot disagree with the screen. Named by entity --
    proteins, phosphosites -- because "features" tells a reader nothing.
    """
    singular, plural = entity_labels_for_kind(kind)
    try:
        result = run_volcano(
            VolcanoRequest(
                kind=kind,
                dataSource=entry.dataSource,
                condition1=entry.condition1,
                condition2=entry.condition2,
                identifier=entry.identifier,
                pValueThreshold=entry.pValueThreshold,
                log2fcThreshold=entry.log2fcThreshold,
                testType=entry.testType,
                useUncorrected=entry.useUncorrected,
                highlightTerms=entry.highlightTerms,
            )
        )
    except Exception as exc:  # pragma: no cover - defensive runtime behavior
        _report_failure(
            warnings, f"{kind.capitalize()} volcano counts ({entry.condition1} vs {entry.condition2})", exc
        )
        return ""

    up = int(result.upregulatedCount)
    down = int(result.downregulatedCount)
    total = int(result.totalRows)
    not_significant = int(result.notSignificantCount)
    unavailable = int(getattr(result, "unavailableCount", 0) or 0)
    # log2FC is condition1 - condition2, so "up" means higher in condition1.
    description = (
        f"{up:,} {plural if up != 1 else singular} upregulated in "
        f"{entry.condition1} and {down:,} downregulated "
        f"(higher in {entry.condition2}), out of {total:,} tested "
        f"{plural if total != 1 else singular}; {not_significant:,} not significant"
        + (f"; {unavailable:,} without a p-value." if unavailable else ".")
    )
    significant = [
        row
        for row in (getattr(result, "rows", None) or [])
        if row.get("significance") in {"Upregulated", "Downregulated"}
    ]
    if significant and all("imputed_values" in row for row in significant):
        with_imputed = sum(1 for row in significant if (row.get("imputed_values") or 0) > 0)
        description += (
            f" {with_imputed:,} of the {len(significant):,} significant "
            f"{plural if len(significant) != 1 else singular} include at least one imputed value."
        )
    return f"<p><strong>Result:</strong> {html.escape(description)}</p>"


def _volcano_statistics_html(entry: SummaryVolcanoEntry) -> str:
    """State the test, thresholds and correction alongside every volcano."""
    test_type = str(getattr(entry, "testType", "unpaired")).strip().lower()
    test_label = _TEST_TYPE_REPORT_LABELS.get(test_type, test_type)
    uncorrected = bool(getattr(entry, "useUncorrected", False))
    correction = (
        "uncorrected p-values (no multiple-testing correction)"
        if uncorrected
        else f"Benjamini-Hochberg adjusted p-values ({cite('benjamini_hochberg')})"
    )
    threshold_name = "p" if uncorrected else "adjusted p"
    description = (
        f"{test_label}; significance at {threshold_name} < "
        f"{entry.pValueThreshold:g} and |log2 fold change| > {entry.log2fcThreshold:g}; "
        f"{correction}."
    )
    return f"<p><strong>Statistics:</strong> {html.escape(description)}</p>"


def _volcano_block_html(
    *,
    kind: str,
    entries: list[SummaryVolcanoEntry],
    warnings: list[str],
    advanced: dict[str, Any] | None = None,
) -> str:
    parts: list[str] = []
    for index, entry in enumerate(entries, start=1):
        parts.append(
            f"<h3>Comparison {index}: {html.escape(entry.condition1)} vs {html.escape(entry.condition2)}</h3>"
        )
        parts.append(
            _data_provenance_html(
                kind=kind,
                # The figure below is rendered with entry.dataSource, so the
                # block has to name the same matrix. It used to collapse to a
                # boolean, and every `filtered` comparison was headed "Data".
                data_source=entry.dataSource,
                subject="this comparison",
                tested=True,
            )
        )
        parts.append(_volcano_statistics_html(entry))
        parts.append(_volcano_counts_html(entry=entry, kind=kind, warnings=warnings))
        title = f"{kind.capitalize()} Volcano Plot ({entry.condition1} vs {entry.condition2})"
        request = VolcanoRequest(
            kind=kind,
            dataSource=entry.dataSource,
            condition1=entry.condition1,
            condition2=entry.condition2,
            identifier=entry.identifier,
            pValueThreshold=entry.pValueThreshold,
            log2fcThreshold=entry.log2fcThreshold,
            testType=entry.testType,
            useUncorrected=entry.useUncorrected,
            highlightTerms=entry.highlightTerms,
        )
        # Each entry renders the way it was added. The PCA blocks make the same
        # choice from a page-level setting; a volcano is per comparison, so the
        # mode rides on the entry.
        if entry.renderType == "Normal":
            parts.append(
                _safe_png(
                    renderer=lambda request=request, entry=entry: report_plot(volcano_png,
                        request,
                        advanced=advanced,
                        label_top_up=entry.labelTopUp,
                        label_top_down=entry.labelTopDown,
                    ),
                    fallback_title=title,
                    warnings=warnings,
                )
            )
        else:
            parts.append(
                _safe_plotly(
                    renderer=lambda request=request: report_plot(volcano_html, request, advanced=advanced),
                    fallback_title=title,
                    warnings=warnings,
                    height_px=920,
                )
            )
    return "".join(parts)


def _qc_plot_style(settings: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "header": _to_bool(settings.get("header"), True),
        "legend": _to_bool(settings.get("legend"), True),
        "width_cm": _to_float(settings.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
        "dpi": _to_int(settings.get("dpi"), 300, minimum=72, maximum=1200),
    }


def _abundance_report(kind, settings, advanced, warnings, title):
    options = _qc_plot_style(settings)
    options.update(condition=_to_str(settings.get("condition"), "All Conditions"),
                   height_cm=_to_float(settings.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                   advanced=advanced)
    if settings.get("type") == "Interactive":
        options.pop("dpi")
        return _safe_plotly(renderer=lambda: report_plot(qc_abundance_interactive_html, kind=kind, **options),
                            fallback_title=title, warnings=warnings)
    return _safe_png(renderer=lambda: report_plot(qc_abundance_plot, kind=kind, **options),
                     fallback_title=title, warnings=warnings)


def _missing_plot_options(settings: Mapping[str, Any], *, peptide=False) -> dict[str, Any]:
    names = {"binCount": "bin_count", "header": "header", "text": "text", "textSize": "text_size",
             "color": "color", "widthCm": "width_cm", "heightCm": "height_cm", "dpi": "dpi"}
    if peptide:
        names["quantityColumn"] = "quantity_column"
    options = {target: settings[source] for source, target in names.items() if source in settings}
    for key, low, high in [("bin_count", 0, 1000), ("text_size", 1, 100),
                           ("width_cm", 1, 60), ("height_cm", 1, 60), ("dpi", 72, 1200)]:
        if key in options:
            value = float(options[key])
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"Missing-value report setting {key} must be between {low} and {high}.")
            if key in {"bin_count", "text_size", "dpi"}:
                if not value.is_integer():
                    raise ValueError(f"Missing-value report setting {key} must be an integer.")
                value = int(value)
            options[key] = value
    return options


def _pca_plot_options(settings: Mapping[str, Any]) -> dict[str, Any]:
    """The report's projection is always a PCA.

    The QC page also offers UMAP and t-SNE for exploration; the report does not
    carry them. A saved `method` other than PCA is ignored here, and the
    UMAP/t-SNE parameters are not forwarded, so the figure under the heading
    "PCA Plot" is a PCA whatever the page currently shows.
    """
    return {
        **({"scaling": _to_str(settings["scaling"], "auto")} if "scaling" in settings else {}),
        "header": _to_bool(settings.get("header"), True),
        "legend": _to_bool(settings.get("legend"), True),
        "plot_dim": _to_str(settings.get("plotDim"), "2D"),
        "method": "PCA",
        "add_ellipses": _to_bool(settings.get("addEllipses"), False),
        "dot_size": _to_int(settings.get("dotSize"), 5, minimum=1, maximum=60),
        "cluster_method": _to_str(settings.get("clusterMethod"), "None"),
        "cluster_count": _to_int(settings.get("clusterCount"), 3, minimum=2, maximum=200),
        "color_by": _to_str(settings.get("colorBy"), "Condition"),
        "dbscan_eps_factor": _to_float(settings.get("dbscanEpsFactor"), 0.5, minimum=1e-6, maximum=1000.0),
        "dbscan_min_samples": _to_int(settings.get("dbscanMinSamples"), 2, minimum=1, maximum=500),
        "random_state": _to_int(settings.get("randomState"), 42, minimum=0, maximum=10_000_000),
        "width_cm": _to_float(settings.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
    }


def _pca_parameters_html(kind: str, data_source: str, options: Mapping[str, Any]) -> str:
    """State the settings that determine the PCA figure, as the volcano states its test.

    Scaling, dimension, clustering and its parameters, colouring and ellipses
    are what a reader needs to reproduce the plot; none of them can be read off
    the image. The DBSCAN radius is relative (factor x median sample distance),
    so the resolved radius is written next to the factor when it can be
    computed.
    """
    scaling = resolve_feature_scaling(options.get("scaling", "auto"), method="PCA")
    scaling_text = (
        "centred features (each feature's mean subtracted; features weighted by their variance)"
        if scaling == "centered"
        else "unit-variance features (each feature centred and divided by its standard deviation)"
    )
    plot_dim = str(options.get("plot_dim", "2D")).upper()
    parts = [f"PCA, {plot_dim}, {scaling_text}"]

    cluster_key = str(options.get("cluster_method", "None")).strip().lower()
    if cluster_key in {"none", "", "off"}:
        parts.append("clustering: none")
    elif cluster_key == "kmeans":
        parts.append(f"clustering: k-means with k = {int(options.get('cluster_count', 3))}")
    elif cluster_key in {"agglomerative", "hierarchical"}:
        parts.append(
            f"clustering: agglomerative (Ward linkage) with k = {int(options.get('cluster_count', 3))}"
        )
    elif cluster_key == "dbscan":
        factor = float(options.get("dbscan_eps_factor", 0.5))
        min_samples = int(options.get("dbscan_min_samples", 2))
        radius = f"eps = {factor:g} × the median distance between samples in the projection"
        try:
            summary = qc_pca_feature_summary(
                kind,
                data_source=data_source,
                plot_dim=plot_dim,
                method="PCA",
                scaling=str(options.get("scaling", "auto")),
                cluster_method="DBSCAN",
                dbscan_eps_factor=factor,
                dbscan_min_samples=min_samples,
                random_state=int(options.get("random_state", 42)),
            )
            resolved = summary.get("dbscan") or {}
            if resolved.get("epsEffective"):
                radius += (
                    f" ({float(resolved['medianSampleDistance']):.3g}), "
                    f"i.e. eps = {float(resolved['epsEffective']):.3g}"
                )
        except Exception:
            pass
        parts.append(f"clustering: DBSCAN with {radius}, min_samples = {min_samples}")

    color_by = str(options.get("color_by", "Condition")).strip().lower()
    parts.append("coloured by cluster" if color_by == "cluster" and cluster_key not in {"none", "", "off"} else "coloured by condition")
    if plot_dim != "3D":
        parts.append(
            "minimum enclosing ellipse per group" if options.get("add_ellipses") else "no group ellipses"
        )
    return f"<p><strong>Projection:</strong> {html.escape('; '.join(parts))}.</p>"


def report_function(payload: SummaryReportRequest) -> SummaryReportResponse:
    global GENERAL_COMMENTS
    title = payload.title.strip() or "Untitled Report"
    author = payload.author.strip() or "Unknown Author"
    date_str = datetime.now().strftime("%Y-%m-%d")
    text_entries = _clean_text_entries(payload.textEntries)
    warnings: list[str] = []

    try:
        GENERAL_COMMENTS = _load_general_comments()
    except Exception as exc:
        _report_failure(warnings, "The general comments file", exc)

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

    filter_paragraphs = {}
    for kind, annotation in (("protein", protein_annotation), ("phospho", phospho_annotation)):
        description = _filter_description(annotation)
        if description is None:
            continue
        normalization_description = _normalization_description(annotation)
        # Imputation stands beside the filtering, not only inside the plot
        # blocks that use it: both decide which numbers a reader is looking at,
        # and a report with no volcano and no imputed PCA used to say nothing
        # about imputation at all.
        filter_paragraphs[kind] = (
            f"<p>QC plots use the {'normalized, ' if normalization_description else ''}unfiltered, "
            "non-imputed data unless another data source is stated. Filtering and imputation "
            "apply to clustering and statistical plots according to the selected data source; "
            "PCA also uses its stated data source.</p>"
            + (
                f"<p><strong>Normalization:</strong> {html.escape(normalization_description)}</p>"
                if normalization_description
                else ""
            )
            + f"<p><strong>Filtering:</strong> {html.escape(description)}</p>"
            + _localization_html(kind)
            + _level_imputation_html(kind)
        )

    report_context = payload.reportContext or SummaryReportContext()
    protein_volcano_entries = _volcano_entries(report_context, "protein")
    phospho_volcano_entries = _volcano_entries(report_context, "phospho")
    qc_coverage_advanced = _qc_advanced_settings(report_context, "coverage")
    qc_hist_advanced = _qc_advanced_settings(report_context, "histogram")
    qc_box_advanced = _qc_advanced_settings(report_context, "boxplot")
    qc_cv_advanced = _qc_advanced_settings(report_context, "cv")
    qc_pca_advanced = _qc_advanced_settings(report_context, "pca")
    qc_abundance_advanced = _qc_advanced_settings(report_context, "abundance")
    qc_correlation_advanced = _qc_advanced_settings(report_context, "correlation")
    completeness_missing_advanced = _completeness_advanced_settings(report_context, "missingPlot")
    peptide_rt_advanced = _global_advanced_settings(report_context, "peptide:rtPlot")
    peptide_modification_advanced = _global_advanced_settings(report_context, "peptide:modification")
    peptide_missed_cleavage_advanced = _global_advanced_settings(report_context, "peptide:missedCleavage")
    phosphosite_plot_advanced = _global_advanced_settings(report_context, "phospho:phosphositePlot")
    phospho_coverage_advanced = _global_advanced_settings(report_context, "phospho:coverage")
    stats_volcano_advanced = _global_advanced_settings(report_context, "stats:volcano")

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
        GENERATED_HTML_META,
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
        # The sample mapping is capped in height so a 6-sample run and a
        # 200-sample run take up the same space in the document; the table
        # scrolls inside the box instead of growing the page.
        ".map-scroll{max-height:320px;overflow:auto;border:1px solid #d6d6d6;border-radius:8px;margin-bottom:16px;}",
        ".map-table{font-size:13px;}",
        ".map-table th,.map-table td{border:1px solid #d6d6d6;padding:6px;}",
        # Sticky header: the label column is meaningless once it has scrolled away.
        ".map-table thead th{position:sticky;top:0;background:#f5f5f5;z-index:1;}",
        ".map-table td.map-label{white-space:nowrap;font-weight:600;width:1%;}",
        # Run names are long and must stay complete, so they wrap rather than
        # overflow. anywhere breaks the run of characters only when needed.
        ".map-table td.map-name{overflow-wrap:anywhere;word-break:break-word;font-family:Consolas,'DejaVu Sans Mono',monospace;font-size:12px;}",
        ".map-count{font-weight:400;color:#555;font-size:14px;}",
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
    html_parts.append("<p class='toc-group'>Sample Mapping</p>")
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
                f"<p class='toc-item'>{phospho_block}.2 Coverage Plot (per sample)</p>",
                f"<p class='toc-item'>{phospho_block}.3 Coverage Plot (per condition)</p>",
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

    html_parts.append("<h2>Sample Mapping</h2>")
    html_parts.append(
        _sample_mapping_html(
            levels=[
                ("Peptide Level", _peptide_mapping_metadata() if has_peptide else None),
                (
                    "Protein Level",
                    protein_annotation.metadata.copy() if has_protein else None,
                ),
                (
                    "Phosphosite Level",
                    phospho_annotation.metadata.copy() if has_phospho else None,
                ),
            ],
            warnings=warnings,
        )
    )

    if peptide_block is not None:
        html_parts.append(f"<h1>{peptide_block} Peptide Level</h1>")
        peptide_rt = _module_settings(report_context, "peptide", "rtPlot")
        peptide_modification = _module_settings(report_context, "peptide", "modification")
        peptide_missed_cleavage = _module_settings(report_context, "peptide", "missedCleavage")
        peptide_coverage = _module_settings(report_context, "peptide", "coverage")

        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{peptide_block}.1",
            title="Coverage Plot - Peptide Level",
            description=None,
            general_comment_key="CoveragePep",
            text_entries=text_entries,
            text_key="CoveragePep",
            content_html=_safe_png(
                renderer=lambda: report_plot(qc_peptide_coverage_plot,
                    advanced=qc_coverage_advanced,
                    reference_line=_to_bool(peptide_coverage.get("referenceLine"), True),
                    **({"quantity_column": peptide_coverage["quantityColumn"]}
                       if "quantityColumn" in peptide_coverage else {})),
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
                renderer=lambda: report_plot(completeness_missing_value_plot_peptide, advanced=completeness_missing_advanced,
                    **_missing_plot_options(report_context.completenessSettings, peptide=True)),
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
                renderer=lambda: report_plot(peptide_rt_plot,
                    method=_to_str(peptide_rt.get("method"), "Hexbin Plot"),
                    add_line=_to_bool(peptide_rt.get("addLine"), False),
                    bins=_to_int(peptide_rt.get("bins"), 1000, minimum=10, maximum=2000),
                    header=_to_bool(peptide_rt.get("header"), True),
                    sampling_seed=_to_int(
                        peptide_rt.get("randomSeed"), 69, minimum=0, maximum=2_147_483_647
                    ),
                    width_cm=_to_float(peptide_rt.get("widthCm"), 20.0, minimum=5.0, maximum=60.0),
                    height_cm=_to_float(peptide_rt.get("heightCm"), 15.0, minimum=5.0, maximum=60.0),
                    dpi=_to_int(peptide_rt.get("dpi"), 100, minimum=72, maximum=1200),
                    advanced=peptide_rt_advanced,
                ),
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
                renderer=lambda: report_plot(peptide_modification_plot,
                    include_id=_to_bool(peptide_modification.get("includeId"), False),
                    header=_to_bool(peptide_modification.get("header"), True),
                    legend=_to_bool(peptide_modification.get("legend"), True),
                    width_cm=_to_float(peptide_modification.get("widthCm"), 25.0, minimum=5.0, maximum=60.0),
                    height_cm=_to_float(peptide_modification.get("heightCm"), 15.0, minimum=5.0, maximum=60.0),
                    dpi=_to_int(peptide_modification.get("dpi"), 100, minimum=72, maximum=1200),
                    advanced=peptide_modification_advanced,
                ),
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
                renderer=lambda: report_plot(peptide_missed_cleavage_plot,
                    include_id=_to_bool(peptide_missed_cleavage.get("includeId"), False),
                    text=_to_bool(peptide_missed_cleavage.get("text"), True),
                    text_size=_to_int(peptide_missed_cleavage.get("textSize"), 8, minimum=6, maximum=24),
                    header=_to_bool(peptide_missed_cleavage.get("header"), True),
                    # The page saves the rule it used; without passing it the
                    # report silently re-rendered under trypsin and said so in
                    # the figure title, whatever the page had been set to.
                    protease=normalize_protease(
                        _to_str(peptide_missed_cleavage.get("protease"), "trypsin")
                    ),
                    width_cm=_to_float(peptide_missed_cleavage.get("widthCm"), 25.0, minimum=5.0, maximum=60.0),
                    height_cm=_to_float(peptide_missed_cleavage.get("heightCm"), 15.0, minimum=5.0, maximum=60.0),
                    dpi=_to_int(peptide_missed_cleavage.get("dpi"), 100, minimum=72, maximum=1200),
                    advanced=peptide_missed_cleavage_advanced,
                ),
                fallback_title="Peptide Missed Cleavage Plot",
                warnings=warnings,
            ),
        )

    if protein_block is not None:
        html_parts.append(f"<h1>{protein_block} Protein Level</h1>")
        if "protein" in filter_paragraphs:
            html_parts.append(filter_paragraphs["protein"])
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
                    renderer=lambda: report_plot(qc_coverage_plot,
                        kind="protein",
                        include_id=_to_bool(protein_coverage.get("includeId"), False),
                        header=_to_bool(protein_coverage.get("header"), True),
                        legend=_to_bool(protein_coverage.get("legend"), True),
                        summary=_to_bool(protein_coverage.get("summary"), False),
                        text=_to_bool(protein_coverage.get("text"), False),
                        text_size=_to_int(protein_coverage.get("textSize"), 9, minimum=6, maximum=24),
                        random_seed=_to_int(
                            protein_coverage.get("randomSeed"),
                            187,
                            minimum=0,
                            maximum=2_147_483_647,
                        ),
                        width_cm=_to_float(protein_coverage.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                        height_cm=_to_float(protein_coverage.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                        dpi=_to_int(protein_coverage.get("dpi"), 300, minimum=72, maximum=1200),
                        advanced=qc_coverage_advanced,
                        reference_line=_to_bool(protein_coverage.get("referenceLine"), True),
                    ),
                    fallback_title="Protein Coverage Plot",
                    warnings=warnings,
                )
                + _safe_table_html(
                    renderer=lambda: report_table(qc_coverage_table,
                        kind="protein",
                        summary=_to_bool(protein_coverage.get("summary"), False),
                    ),
                    title="Coverage Table (per sample)",
                    fallback_title="Protein Coverage Table",
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
            content_html=_completeness_exclusion_html("protein") + _safe_png(
                renderer=lambda: report_plot(completeness_missing_value_plot, kind="protein", advanced=completeness_missing_advanced,
                    **_missing_plot_options(report_context.completenessSettings)),
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
                renderer=lambda: report_plot(qc_intensity_histogram_plot,
                    kind="protein",
                    **_qc_plot_style(protein_hist),
                    height_cm=_to_float(protein_hist.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                    advanced=qc_hist_advanced,
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
            comments_override=_boxplot_comment_paragraphs(
                "protein", _to_str(protein_box.get("mode"), "Mean"), "BoxplotIntProt"
            ),
            text_entries=text_entries,
            text_key="BoxplotIntProt",
            content_html=(
                _safe_png(
                    renderer=lambda: report_plot(qc_boxplot_plot,
                        kind="protein",
                        mode=_to_str(protein_box.get("mode"), "Mean"),
                        outliers=_to_bool(protein_box.get("outliers"), False),
                        include_id=_to_bool(protein_box.get("includeId"), False),
                        **_qc_plot_style(protein_box),
                        text=_to_bool(protein_box.get("text"), False),
                        text_size=_to_int(protein_box.get("textSize"), 9, minimum=6, maximum=24),
                        height_cm=_to_float(protein_box.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                        advanced=qc_box_advanced,
                    ),
                    fallback_title="Protein Boxplot",
                    warnings=warnings,
                )
                + _safe_table_html(
                    renderer=lambda: report_table(qc_boxplot_table,
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
                    renderer=lambda: report_plot(qc_cv_plot,
                        kind="protein",
                        outliers=_to_bool(protein_cv.get("outliers"), False),
                        **_qc_plot_style(protein_cv),
                        text=_to_bool(protein_cv.get("text"), False),
                        text_size=_to_int(protein_cv.get("textSize"), 9, minimum=6, maximum=24),
                        height_cm=_to_float(protein_cv.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                        advanced=qc_cv_advanced,
                    ),
                    fallback_title="Protein CV Plot",
                    warnings=warnings,
                )
                + _safe_table_html(
                    renderer=lambda: report_table(qc_cv_table, kind="protein"),
                    title="Coefficient of Variation Summary Table",
                    fallback_title="Protein CV Summary Table",
                    warnings=warnings,
                )
            ),
        )
        protein_pca_height_cm = _to_float(protein_pca.get("heightCm"), 10.0, minimum=4.0, maximum=60.0)
        protein_pca_interactive = _to_str(protein_pca.get("type"), "Normal").lower() == "interactive"
        protein_pca_data_source = _report_data_source(protein_pca.get("dataSource"))
        # A PCA is built from the rows that survived filtering, and from drawn
        # values when its source is imputed, so it carries the same provenance
        # block as a volcano rather than a bare source line.
        protein_pca_source_html = _data_provenance_html(
            kind="protein",
            data_source=protein_pca_data_source,
            subject="this plot",
            completeness=_pca_completeness_description("protein", protein_pca_data_source),
        ) + _pca_parameters_html("protein", protein_pca_data_source, _pca_plot_options(protein_pca))
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.6",
            title="PCA Plot",
            description=None,
            general_comment_key="PCAProt",
            text_entries=text_entries,
            text_key="PCAProt",
            content_html=(
                (
                    protein_pca_source_html
                    + _safe_plotly(
                        renderer=lambda: report_plot(qc_pca_interactive_html,
                            kind="protein",
                            data_source=protein_pca_data_source,
                            **_pca_plot_options(protein_pca),
                            height_cm=protein_pca_height_cm,
                            advanced=qc_pca_advanced,
                        ),
                        fallback_title="Protein PCA Interactive Plot",
                        warnings=warnings,
                        height_px=_interactive_height_px(protein_pca_height_cm),
                    )
                )
                if protein_pca_interactive
                else (
                    protein_pca_source_html
                    + _safe_png(
                        renderer=lambda: report_plot(qc_pca_plot,
                            kind="protein",
                            data_source=protein_pca_data_source,
                            **_pca_plot_options(protein_pca),
                            height_cm=protein_pca_height_cm,
                            dpi=_to_int(protein_pca.get("dpi"), 300, minimum=72, maximum=1200),
                            advanced=qc_pca_advanced,
                        ),
                        fallback_title="Protein PCA Plot",
                        warnings=warnings,
                    )
                )
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{protein_block}.7",
            title="Abundance Plot",
            description=None,
            general_comment_key="AbundanceProt",
            text_entries=text_entries,
            text_key="AbundanceProt",
            content_html=_abundance_report("protein", protein_abundance, qc_abundance_advanced,
                                           warnings, "Protein Abundance Plot"),
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
                renderer=lambda: report_plot(qc_correlation_plot,
                    kind="protein",
                    method=_to_str(protein_correlation.get("method"), "Matrix"),
                    include_id=_to_bool(protein_correlation.get("includeId"), False),
                    full_range=_to_bool(protein_correlation.get("fullRange"), False),
                    width_cm=_to_float(protein_correlation.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                    height_cm=_to_float(protein_correlation.get("heightCm"), 16.0, minimum=4.0, maximum=60.0),
                    dpi=_to_int(protein_correlation.get("dpi"), 400, minimum=72, maximum=1200),
                    advanced=qc_correlation_advanced,
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
                # No section-wide imputation note: every comparison now states
                # its own, which is also the accurate one when some comparisons
                # use imputed data and others do not.
                content_html=(
                    _volcano_block_html(
                        kind="protein",
                        entries=protein_volcano_entries,
                        warnings=warnings,
                        advanced=stats_volcano_advanced,
                    )
                ),
            )

    if phospho_block is not None:
        html_parts.append(f"<h1>{phospho_block} Phosphosite Level</h1>")
        if "phospho" in filter_paragraphs:
            html_parts.append(filter_paragraphs["phospho"])
        phospho_coverage = _module_settings(report_context, "phospho", "coverage")
        # The Phospho-specific page's own coverage settings (include-ID, the
        # conditions shown, colours, point jitter), saved for the report.
        site_coverage = _module_settings(report_context, "phospho", "phosphoCoverage")
        site_coverage_conditions = [
            str(condition) for condition in site_coverage.get("conditions", []) or [] if str(condition).strip()
        ] if isinstance(site_coverage.get("conditions"), list) else []
        site_coverage_options = dict(
            include_id=_to_bool(site_coverage.get("includeId"), False),
            conditions=site_coverage_conditions or None,
            color_class_i=_to_str(site_coverage.get("colorClassI"), "#2563eb"),
            color_not_class_i=_to_str(site_coverage.get("colorNotClassI"), "#f59e0b"),
            random_seed=_to_int(site_coverage.get("randomSeed"), 69, minimum=0, maximum=2_147_483_647),
        )
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
                renderer=lambda: report_plot(phosphosite_plot_png, advanced=phosphosite_plot_advanced),
                fallback_title="Phosphosite Overview Plot",
                warnings=warnings,
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.2",
            title="Coverage Plot (per sample)",
            description=None,
            general_comment_key="Coverage(Number)Phos",
            comments_override=[*GENERAL_COMMENTS.get("Coverage(Number)Phos", []), CLASS_I_SENTENCE],
            text_entries=text_entries,
            text_key="Coverage(Number)Phos",
            content_html=(
                _safe_png(
                    renderer=lambda: report_plot(phospho_coverage_png,
                        mode="Normal",
                        **site_coverage_options,
                        advanced=phospho_coverage_advanced,
                    ),
                    fallback_title="Phospho Coverage Number Plot",
                    warnings=warnings,
                )
                + _safe_table_html(
                    renderer=lambda: report_table(qc_coverage_table,
                        kind="phospho",
                        summary=_to_bool(phospho_coverage.get("summary"), False),
                    ),
                    title="Coverage Table (per sample)",
                    fallback_title="Phospho Coverage Table",
                    warnings=warnings,
                )
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.3",
            title="Coverage Plot (per condition)",
            description=None,
            general_comment_key="Coverage(Quality)Phos",
            comments_override=[*GENERAL_COMMENTS.get("Coverage(Quality)Phos", []), CLASS_I_SENTENCE],
            text_entries=text_entries,
            text_key="Coverage(Quality)Phos",
            content_html=_safe_png(
                renderer=lambda: report_plot(phospho_coverage_png,
                    mode="Summary",
                    **site_coverage_options,
                    advanced=phospho_coverage_advanced,
                ),
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
            content_html=_completeness_exclusion_html("phospho") + _safe_png(
                renderer=lambda: report_plot(completeness_missing_value_plot, kind="phospho", advanced=completeness_missing_advanced,
                    **_missing_plot_options(report_context.completenessSettings)),
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
                renderer=lambda: report_plot(qc_intensity_histogram_plot,
                    kind="phospho",
                    **_qc_plot_style(phospho_hist),
                    height_cm=_to_float(phospho_hist.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                    advanced=qc_hist_advanced,
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
            comments_override=_boxplot_comment_paragraphs(
                "phospho", _to_str(phospho_box.get("mode"), "Mean"), "BoxplotIntPhos"
            ),
            text_entries=text_entries,
            text_key="BoxplotIntPhos",
            content_html=(
                _safe_png(
                    renderer=lambda: report_plot(qc_boxplot_plot,
                        kind="phospho",
                        mode=_to_str(phospho_box.get("mode"), "Mean"),
                        outliers=_to_bool(phospho_box.get("outliers"), False),
                        include_id=_to_bool(phospho_box.get("includeId"), False),
                        **_qc_plot_style(phospho_box),
                        text=_to_bool(phospho_box.get("text"), False),
                        text_size=_to_int(phospho_box.get("textSize"), 9, minimum=6, maximum=24),
                        height_cm=_to_float(phospho_box.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                        advanced=qc_box_advanced,
                    ),
                    fallback_title="Phospho Boxplot",
                    warnings=warnings,
                )
                + _safe_table_html(
                    renderer=lambda: report_table(qc_boxplot_table,
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
                    renderer=lambda: report_plot(qc_cv_plot,
                        kind="phospho",
                        outliers=_to_bool(phospho_cv.get("outliers"), False),
                        **_qc_plot_style(phospho_cv),
                        text=_to_bool(phospho_cv.get("text"), False),
                        text_size=_to_int(phospho_cv.get("textSize"), 9, minimum=6, maximum=24),
                        height_cm=_to_float(phospho_cv.get("heightCm"), 10.0, minimum=4.0, maximum=60.0),
                        advanced=qc_cv_advanced,
                    ),
                    fallback_title="Phospho CV Plot",
                    warnings=warnings,
                )
                + _safe_table_html(
                    renderer=lambda: report_table(qc_cv_table, kind="phospho"),
                    title="Coefficient of Variation Summary Table",
                    fallback_title="Phospho CV Summary Table",
                    warnings=warnings,
                )
            ),
        )
        phospho_pca_height_cm = _to_float(phospho_pca.get("heightCm"), 10.0, minimum=4.0, maximum=60.0)
        phospho_pca_interactive = _to_str(phospho_pca.get("type"), "Normal").lower() == "interactive"
        phospho_pca_data_source = _report_data_source(phospho_pca.get("dataSource"))
        phospho_pca_source_html = _data_provenance_html(
            kind="phospho",
            data_source=phospho_pca_data_source,
            subject="this plot",
            completeness=_pca_completeness_description("phospho", phospho_pca_data_source),
        ) + _pca_parameters_html("phospho", phospho_pca_data_source, _pca_plot_options(phospho_pca))
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.8",
            title="PCA Plot",
            description=None,
            general_comment_key="PCAPhos",
            text_entries=text_entries,
            text_key="PCAPhos",
            content_html=(
                (
                    phospho_pca_source_html
                    + _safe_plotly(
                        renderer=lambda: report_plot(qc_pca_interactive_html,
                            kind="phospho",
                            data_source=phospho_pca_data_source,
                            **_pca_plot_options(phospho_pca),
                            height_cm=phospho_pca_height_cm,
                            advanced=qc_pca_advanced,
                        ),
                        fallback_title="Phospho PCA Interactive Plot",
                        warnings=warnings,
                        height_px=_interactive_height_px(phospho_pca_height_cm),
                    )
                )
                if phospho_pca_interactive
                else (
                    phospho_pca_source_html
                    + _safe_png(
                        renderer=lambda: report_plot(qc_pca_plot,
                            kind="phospho",
                            data_source=phospho_pca_data_source,
                            **_pca_plot_options(phospho_pca),
                            height_cm=phospho_pca_height_cm,
                            dpi=_to_int(phospho_pca.get("dpi"), 300, minimum=72, maximum=1200),
                            advanced=qc_pca_advanced,
                        ),
                        fallback_title="Phospho PCA Plot",
                        warnings=warnings,
                    )
                )
            ),
        )
        _append_plot_section(
            html_parts=html_parts,
            section_id=f"{phospho_block}.9",
            title="Abundance Plot",
            description=None,
            general_comment_key="AbundancePhos",
            text_entries=text_entries,
            text_key="AbundancePhos",
            content_html=_abundance_report("phospho", phospho_abundance, qc_abundance_advanced,
                                           warnings, "Phospho Abundance Plot"),
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
                renderer=lambda: report_plot(qc_correlation_plot,
                    kind="phospho",
                    method=_to_str(phospho_correlation.get("method"), "Matrix"),
                    include_id=_to_bool(phospho_correlation.get("includeId"), False),
                    full_range=_to_bool(phospho_correlation.get("fullRange"), False),
                    width_cm=_to_float(phospho_correlation.get("widthCm"), 20.0, minimum=6.0, maximum=60.0),
                    height_cm=_to_float(phospho_correlation.get("heightCm"), 16.0, minimum=4.0, maximum=60.0),
                    dpi=_to_int(phospho_correlation.get("dpi"), 400, minimum=72, maximum=1200),
                    advanced=qc_correlation_advanced,
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
                # See the protein volcano above: each comparison carries its own
                # imputation note now.
                content_html=(
                    _volcano_block_html(
                        kind="phospho",
                        entries=phospho_volcano_entries,
                        warnings=warnings,
                        advanced=stats_volcano_advanced,
                    )
                ),
            )

    # Warnings go back to the page that asked for the report (the response's
    # `warnings`), not into the report: the report is the record of an analysis
    # done on purpose, read by people who were not there.
    html_parts.append("</body></html>")
    html_doc = "\n".join(html_parts)
    return SummaryReportResponse(
        fileName=_file_name_from_title(title),
        html=html_doc,
        warnings=warnings,
    )
