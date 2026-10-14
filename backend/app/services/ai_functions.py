from __future__ import annotations

from typing import Any, cast, get_args
from app.services.peptide_quantity import resolve_peptide_quantity_column
import json
import re

import numpy as np
import pandas as pd

from app.schemas.assistant import ContextMode
from app.schemas.annotation import AnnotationKind
from app.schemas.stats import AnovaRequest, SimulationRequest, EnrichmentRequest, ListEnrichmentRequest, StatsTestType
from app.services.annotation_store import get_annotation
from app.services.dataset_store import get_active_package, get_all_current_datasets
from app.services.condition_palette_store import build_condition_color_map
from app.services.completeness_tools import completeness_tables as _completeness_tables
from app.services import plot_images as _plot_images
from app.services import stats_tools as _stats_tools
from app.services import single_protein_tools as _single_protein_tools
from app.services import comparison_tools as _comparison_tools
from app.services import phospho_tools as _phospho_tools
from app.services import table_functions as _table_functions
from app.services.functions import (
    condition_sample_labels,
    parse_selection_list,
    comparison_contrast,
    effective_test_type,
    resolve_test_type,
)
from app.services.analysis_matrix import DATA_SOURCES, phosprot_values_are_centred
from app.services.peptide_tools import _sample_rename_map as _peptide_sample_rename_map
from app.services.peptide_tools import PROTEASE_LABELS as _PROTEASE_LABELS
from app.services.peptide_tools import get_peptide_frame
from app.services.peptide_tools import peptide_modification_counts as _peptide_modification_counts
from app.services.peptide_tools import peptide_missed_cleavage_summary as _peptide_missed_cleavage_summary
from app.services.peptide_tools import peptide_overview as _peptide_overview
from app.services.peptide_tools import peptide_sequence_coverage as _peptide_sequence_coverage
from app.services.peptide_tools import normalize_protease as _normalize_protease

# The chat layer accepts exactly what the analysis engine accepts, so a request
# naming an explicit matrix is not silently downgraded to the default one.
# One vocabulary, the same one the UI and the schemas use.
_AI_DATA_SOURCES: frozenset[str] = frozenset(DATA_SOURCES)

_WORKFLOW_ENTITY_LABELS: dict[str, tuple[str, str]] = {
    "protein": ("protein", "proteins"),
    "phosphosite": ("phosphosite", "phosphosites"),
    "phosphoprotein": ("phosphoprotein", "phosphoproteins"),
    "peptide": ("peptide", "peptides"),
}

_HEX_COLOR_NAME_OVERRIDES: dict[str, str] = {
    "#1F77B4": "blue",
    "#FF7F0E": "orange",
    "#2CA02C": "green",
    "#D62728": "red",
    "#9467BD": "purple",
    "#8C564B": "brown",
    "#E377C2": "pink",
    "#7F7F7F": "gray",
    "#BCBD22": "olive",
    "#17BECF": "cyan",
    "#AEC7E8": "light blue",
    "#FFBB78": "light orange",
    "#98DF8A": "light green",
    "#FF9896": "light red",
    "#C5B0D5": "lavender",
    "#C49C94": "tan",
    "#F7B6D2": "light pink",
    "#C7C7C7": "light gray",
    "#DBDB8D": "pale olive",
    "#9EDAE5": "light cyan",
}

_COMPLETENESS_KIND_LABELS: dict[str, tuple[str, str]] = {
    "protein": ("protein", "proteins"),
    "phospho": ("phosphosite", "phosphosites"),
    "phosprot": ("phosphoprotein", "phosphoproteins"),
    "peptide": ("peptide", "peptides"),
    "precursor": ("precursor", "precursors"),
}

_STATS_TEST_TYPES = cast(tuple[StatsTestType, ...], get_args(StatsTestType))
_STATS_TEST_DESCRIPTIONS: dict[StatsTestType, str] = {
    "unpaired": "unpaired_student_t_test_with_pooled_variance",
    "unpaired_welch": "unpaired_welch_t_test_with_unequal_variance",
    "paired": "paired_student_t_test_on_within_pair_differences",
}


def _text_payload(function_name: str, text: str) -> dict[str, Any]:
    return {
        "function": function_name,
        "format": "ai_text",
        "summary": text,
        "data": {"text": text},
    }


def _normalize_coverage_workflow(workflow: str) -> str:
    key = str(workflow or "").strip().lower()
    if key in {"peptide", "phosphosite", "phosphoprotein", "protein"}:
        return key
    if "peptide" in key:
        return "peptide"
    if "phosphosite" in key or key == "phospho":
        return "phosphosite"
    if "phosprot" in key or "phosphoprotein" in key:
        return "phosphoprotein"
    return "protein"


def _workflow_entity_labels(workflow: str) -> tuple[str, str]:
    return _WORKFLOW_ENTITY_LABELS.get(workflow, _WORKFLOW_ENTITY_LABELS["protein"])


def _workflow_kind(workflow: str) -> AnnotationKind:
    if workflow == "phosphosite":
        return "phospho"
    if workflow == "phosphoprotein":
        return "phosprot"
    return "protein"


def _normalize_boxplot_mode(mode: str) -> str:
    key = str(mode or "").strip().lower()
    if key == "single":
        return "Single"
    return "Mean"


def _extract_condition_from_sample(sample_name: str) -> str:
    text = str(sample_name or "").strip()
    if not text:
        return "sample"
    if "_" in text:
        head = text.split("_", 1)[0].strip()
        return head or text
    return text


def _fmt_value(value: float | int) -> str:
    number = float(value)
    if pd.isna(number) or number in {float("inf"), float("-inf")}:
        return "NA"
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.2f}"


def _fmt_probability(value: float | int) -> str:
    number = float(value)
    if pd.isna(number) or number in {float("inf"), float("-inf")}:
        return "NA"
    if number == 0:
        return "0"
    return f"{number:.3e}"


def _color_name(color_value: str) -> str:
    value = str(color_value or "").strip().upper()
    if not value:
        return "unassigned"
    mapped = _HEX_COLOR_NAME_OVERRIDES.get(value)
    if mapped:
        return mapped
    if value.startswith("#"):
        return "custom color"
    return value.lower()


def _coverage_rows_from_wide(kind: AnnotationKind) -> tuple[pd.DataFrame, int | None]:
    table = _table_functions.qc_coverage_table(kind, summary=False).copy()
    if table.empty or "Sample" not in table.columns or "Number" not in table.columns:
        return pd.DataFrame(columns=["Sample", "Condition", "Count"]), None

    frame = table.copy()
    frame["Sample"] = frame["Sample"].astype(str)
    frame["Count"] = pd.to_numeric(frame["Number"], errors="coerce")

    total_features: int | None = None
    all_mask = frame["Sample"].str.lower().str.startswith("all sample")
    if all_mask.any():
        total_values = frame.loc[all_mask, "Count"].dropna()
        if not total_values.empty:
            total_features = int(total_values.iloc[0])

    frame = frame.loc[~all_mask].copy()
    frame = frame.dropna(subset=["Count"])
    if frame.empty:
        return pd.DataFrame(columns=["Sample", "Condition", "Count"]), total_features

    # Coverage labels are generated as <complete condition>_<replicate number>.
    # Splitting at the first underscore merges conditions such as Ctx_DMSO/Ctx_RAPA.
    frame["Condition"] = frame["Sample"].str.rsplit("_", n=1).str[0]
    return frame[["Sample", "Condition", "Count"]].reset_index(drop=True), total_features


def _coverage_rows_from_peptide(*, quantity_column=None, level="peptide") -> tuple[pd.DataFrame, int | None]:
    summary, total, meta = _plot_images._peptide_coverage_summary(
        quantity_column=quantity_column, level=level
    )
    rows = summary.rename(columns={"Value": "Count"}).copy()
    conditions = dict(zip(meta["label"].astype(str), meta["condition"].astype(str)))
    rows["Condition"] = rows["Sample"].astype(str).map(conditions)
    return rows[["Sample", "Condition", "Count"]], total


def _condition_palette_for_workflow(workflow: str, conditions: list[str]) -> dict[str, str]:
    kind = _workflow_kind(workflow)
    if workflow == "peptide":
        kind = "protein"
    try:
        ordered_conditions: list[str] = []
        seen: set[str] = set()
        for condition in conditions:
            name = str(condition or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            ordered_conditions.append(name)
        return build_condition_color_map(kind, ordered_conditions)
    except Exception:
        return {}


def _condition_order(rows: pd.DataFrame) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()
    for value in rows["Condition"].astype(str).tolist():
        if value in seen:
            continue
        seen.add(value)
        order.append(value)
    return order


def _conditions_for_workflow(workflow: str) -> list[str]:
    kind = _workflow_kind(workflow)
    try:
        annotation = get_annotation(kind)
    except Exception:
        annotation = None

    if annotation is not None and not annotation.metadata.empty and "condition" in annotation.metadata.columns:
        values = annotation.metadata["condition"].astype(str).str.strip()
        values = values[values != ""]
        ordered: list[str] = []
        seen: set[str] = set()
        for value in values.tolist():
            if value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        if ordered:
            return ordered

    try:
        summary = _table_functions.qc_boxplot_table(kind, mode="Mean").copy()
    except Exception:
        summary = pd.DataFrame()
    if not summary.empty and "Condition" in summary.columns:
        return _condition_order(summary[["Condition"]].astype(str))
    return []


def _safe_context_text(value: Any) -> str:
    if value is None:
        return "unknown"
    try:
        if bool(pd.isna(value)):
            return "unknown"
    except (TypeError, ValueError):
        pass
    text = str(value).replace("|", "/").replace("\n", " ").replace("\r", " ").strip()
    if not text:
        return "unknown"
    return text


def _lookup_queries(text: str) -> list[str]:
    """Names to look up: separated by commas or semicolons; "MAP4K4 S1045" stays one query
    (a gene and its site), while "ANXA1 ANXA3" is two names (GRK, 2026-10-13)."""
    queries: list[str] = []
    for chunk in re.split(r"[,;]+", text):
        tokens = [token for token in chunk.split() if token]
        while tokens:
            if len(tokens) >= 2 and re.fullmatch(r"[STYsty]\d{1,5}", tokens[1]) and not re.fullmatch(r"[STYsty]\d{1,5}", tokens[0]):
                queries.append(tokens[0] + " " + tokens[1])
                tokens = tokens[2:]
            else:
                queries.append(tokens[0])
                tokens = tokens[1:]
    return queries


def _lookup_pattern(query: str) -> "re.Pattern[str]":
    """A whole-token match of each part of the query, in order, within one identifier cell."""
    parts = [r"(?<![A-Za-z0-9])" + re.escape(part) + r"(?![A-Za-z0-9])" for part in query.split()]
    return re.compile(r".*?".join(parts), re.I)


def _contrast_pair(text: str) -> tuple[str, str] | None:
    """"C5 vs C0", "C5 versus C0" or "C5, C0": two different condition names, else nothing."""
    match = re.fullmatch(r"\s*(.{1,60}?)\s*(?:\s+vs\.?\s+|\s+versus\s+|\s+minus\s+|,|;)\s*(.{1,60}?)\s*", text, re.I)
    if not match or match.group(1) == match.group(2):
        return None
    return match.group(1), match.group(2)


def _reference_direction(a_value: float, b_value: float, relation: str) -> str:
    """Where contrast B puts a row relative to A's reference condition.

    relation "shared_reference": A = X vs ref, B = Y vs ref (both measured from the same
    reference); "chained": A = X vs ref, B = Y vs X (B measured from A's first condition).
    The words are what a reader would otherwise have to work out from two signs
    ("CCN1 R20 vs dQ0 = -1.15 after dQ0 vs C0 = +1.27 is a move back toward C0";
    GRK project, 2026-10-14)."""
    if relation == "chained":
        # Y's position from the reference is a + b.
        position = a_value + b_value
    else:
        position = b_value
    if not np.isfinite(a_value) or not np.isfinite(position):
        return "unavailable"
    if position == a_value:
        return "same_point_estimate"
    if position == 0:
        return "at_reference_point_estimate"
    if a_value * position < 0:
        return "opposite_side_of_reference"
    if abs(position) < abs(a_value):
        return "toward_reference"
    return "further_from_reference"


def _volcano_contrast_difference(frame_a: pd.DataFrame, label_column: str, versus: tuple[str, str], *, kind: str,
                                 identifier: str, p_value_threshold: float, log2fc_threshold: float, test_type: str,
                                 use_uncorrected: bool, data_source: str, a_pair: tuple[str, str],
                                 lookup: list[str] | None = None, enrich: bool = False, organism: str = "") -> list[str]:
    """Contrast A's significant rows seen in contrast B, computed with the same settings
    ("up after stimulation in parental cells but not in the knockout", GRK, 2026-10-14).
    Rows are matched by identifier; the set algebra is done here, not by the model.
    When B shares A's reference condition, or is measured from A's first condition, each row
    also says whether B has moved it back toward that reference. With ``enrich`` the
    A-specific and shared gene sets use genes with usable tests in both contrasts as the GO background."""
    a_label = f"{a_pair[0]}_vs_{a_pair[1]}"
    b_label = f"{versus[0]}_vs_{versus[1]}"
    relation = "shared_reference" if versus[1] == a_pair[1] else "chained" if versus[1] == a_pair[0] else ""
    if test_type == "paired":
        # Complete pairs can differ between contrasts, so their estimates need
        # not share the same reference mean and cannot safely be added.
        relation = ""
    untested_out: list = []
    try:
        _, label_b, frame_b, _ = _stats_tools._volcano_dataframe(
            kind=kind,  # type: ignore[arg-type]
            condition1=versus[0], condition2=versus[1], identifier=identifier,  # type: ignore[arg-type]
            p_value_threshold=p_value_threshold, log2fc_threshold=log2fc_threshold, test_type=test_type,
            use_uncorrected=use_uncorrected, data_source=data_source, untested_out=untested_out)  # type: ignore[arg-type]
    except Exception as exc:
        return [f"volcano_versus|b={_safe_context_text(b_label)}|status=error|detail={_safe_context_text(exc)}"]
    key_a = frame_a[label_column].astype(str) if label_column in frame_a.columns else frame_a.iloc[:, 0].astype(str)
    key_b = frame_b[label_b].astype(str) if label_b in frame_b.columns else frame_b.iloc[:, 0].astype(str)
    # Display labels (especially genes for phosphosites) need not identify a row.
    # Use a common unique workflow identifier; never discard repeated labels.
    for column in _stats_tools._workflow_label_candidates(kind):  # type: ignore[arg-type]
        if column in frame_a and column in frame_b and frame_a[column].notna().all() and frame_b[column].notna().all():
            candidate_a, candidate_b = frame_a[column].astype(str), frame_b[column].astype(str)
            if candidate_a.is_unique and candidate_b.is_unique:
                key_a, key_b = candidate_a, candidate_b
                break
    if not key_a.is_unique or not key_b.is_unique:
        return ["volcano_versus|status=unavailable|reason=no_unique_shared_row_identifier"]
    b = frame_b.assign(_key=key_b.values).set_index("_key")
    untested_b = untested_out[0] if untested_out and isinstance(untested_out[0], pd.DataFrame) else pd.DataFrame()
    key_column = str(key_b.name)
    untested_keys = set(untested_b[key_column].astype(str)) if not untested_b.empty and key_column in untested_b.columns else set()
    header = (f"volcano_versus|a={_safe_context_text(a_label)}|b={_safe_context_text(b_label)}|"
              f"b_tested={int(frame_b.shape[0])}|b_untested={len(untested_keys)}|same_settings=true|rows_matched_by_identifier=true")
    if relation == "shared_reference":
        header += f"|reference={_safe_context_text(a_pair[1])}|direction_words=position_of_{_safe_context_text(versus[0])}_relative_to_{_safe_context_text(a_pair[0])}_both_measured_from_the_reference"
    elif relation == "chained":
        header += (f"|reference={_safe_context_text(a_pair[1])}|direction_words=b_is_measured_from_{_safe_context_text(a_pair[0])}_so_a_plus_b_is_"
                   f"{_safe_context_text(versus[0])}_relative_to_the_reference")
    lines = [header, "volcano_versus_caution|message=Significant in A but not B does not establish a difference between contrasts. "
             "Direction describes point estimates only, not evidence of rescue, equivalence or an interaction."]
    if test_type == "paired":
        lines.append("volcano_versus_caution|message=Paired contrasts can use different complete pairs; no common-reference direction was inferred.")

    def _p(value: object) -> str:
        return _fmt_probability(float(value)) if pd.notna(value) else "unavailable"  # type: ignore[arg-type]

    def _direction(a_value: float, b_value: float) -> str:
        return f"|direction={_reference_direction(a_value, b_value, relation)}" if relation else ""

    gene_sets: dict[str, list[str]] = {}
    gene_column = next((column for column in _stats_tools._gene_label_candidates(kind) if column in frame_a.columns), None)  # type: ignore[arg-type]
    split_groups = kind == "phosprot" or gene_column == "Gene_group"
    for direction, group in (("Upregulated", "up"), ("Downregulated", "down")):
        rows = frame_a[frame_a["significance"].astype(str) == direction].copy()
        rows["_key"] = key_a[rows.index].values
        rows["_b_sig"] = [str(b.loc[k, "significance"]) if k in b.index else ("untested" if k in untested_keys else "absent") for k in rows["_key"]]
        counts = rows["_b_sig"].value_counts()
        lines.append(f"volcano_versus_{group}|a_{group}={int(rows.shape[0])}|also_{group}_in_b={int(counts.get(direction, 0))}|"
                     f"not_significant_in_b={int(counts.get('Not significant', 0))}|opposite_in_b={int(counts.get('Downregulated' if group == 'up' else 'Upregulated', 0))}|"
                     f"untested_in_b={int(counts.get('untested', 0))}|absent_in_b={int(counts.get('absent', 0))}|unavailable_in_b={int(counts.get('Unavailable', 0))}")
        specific = rows[rows["_b_sig"] == "Not significant"].copy()
        specific["_score"] = specific["log2FC"].abs() + (-np.log10(specific["adj_pval"].astype(float).clip(lower=1e-300)))
        for _, row in specific.sort_values("_score", ascending=False).head(10).iterrows():
            b_row = b.loc[row["_key"]]
            lines.append(f"volcano_a_specific_{group}|term={_primary_term_label(row['_key'])}|a_log2FC={_fmt_value(float(row['log2FC']))}|"
                         f"a_adj_p={_p(row['adj_pval'])}|b_log2FC={_fmt_value(float(b_row['log2FC']))}|b_adj_p={_p(b_row['adj_pval'])}|b=not_significant"
                         + _direction(float(row["log2FC"]), float(b_row["log2FC"])))
        if specific.shape[0] > 10:
            lines.append(f"volcano_a_specific_{group}_truncated|rows={int(specific.shape[0])}|shown=10|rank=effect_and_significance_in_a")
        shared = rows[rows["_b_sig"] == direction].copy()
        shared["_score"] = shared["log2FC"].abs() + (-np.log10(shared["adj_pval"].astype(float).clip(lower=1e-300)))
        for _, row in shared.sort_values("_score", ascending=False).head(5).iterrows():
            b_row = b.loc[row["_key"]]
            lines.append(f"volcano_shared_{group}|term={_primary_term_label(row['_key'])}|a_log2FC={_fmt_value(float(row['log2FC']))}|"
                         f"b_log2FC={_fmt_value(float(b_row['log2FC']))}|b_adj_p={_p(b_row['adj_pval'])}"
                         + _direction(float(row["log2FC"]), float(b_row["log2FC"])))
        if enrich and gene_column:
            gene_sets[f"a_specific_{group}"] = _stats_tools._genes_from_values(specific[gene_column].tolist(), split_groups=split_groups)
            gene_sets[f"shared_{group}"] = _stats_tools._genes_from_values(shared[gene_column].tolist(), split_groups=split_groups)
    if lookup:
        # The named rows in B as well, with the direction words (rescue / reversion questions).
        for name in lookup:
            pattern = _lookup_pattern(name)
            mask_a = key_a.str.contains(pattern, na=False) | frame_a[label_column].astype(str).str.contains(pattern, na=False)
            for key, a_row in frame_a[mask_a].assign(_key=key_a[mask_a].values).head(6).set_index("_key").iterrows():
                if key in b.index:
                    b_row = b.loc[key]
                    lines.append(f"volcano_lookup_in_b|query={_safe_context_text(name)}|term={_primary_term_label(key)}|a_log2FC={_fmt_value(float(a_row['log2FC']))}|"
                                 f"a_significance={_safe_context_text(a_row['significance'])}|b_log2FC={_fmt_value(float(b_row['log2FC']))}|"
                                 f"b_adj_p={_p(b_row['adj_pval'])}|b_significance={_safe_context_text(b_row['significance'])}"
                                 + _direction(float(a_row["log2FC"]), float(b_row["log2FC"])))
                else:
                    lines.append(f"volcano_lookup_in_b|query={_safe_context_text(name)}|term={_primary_term_label(key)}|b={'untested' if key in untested_keys else 'absent'}")
    if enrich and gene_column:
        if organism not in {"human", "mouse"}:
            lines.append("volcano_versus_enrichment|status=unavailable|reason=Choose human or mouse before enrichment; no organism was assumed.")
            return lines
        usable = {"Upregulated", "Downregulated", "Not significant"}
        usable_b = set(b.index[b["significance"].isin(usable)])
        jointly_tested = frame_a[frame_a["significance"].isin(usable) & key_a.isin(usable_b)]
        background = _stats_tools._genes_from_values(jointly_tested[gene_column].tolist(), split_groups=split_groups)
        lines.append(f"volcano_versus_enrichment|method=over_representation_hypergeometric_BH|background=genes_with_usable_tests_in_both_contrasts|background_genes={len(background)}|"
                     f"organism={_safe_context_text(organism)}|term_size=20_to_300|adj_p_cutoff=0.05|top=6_per_set|note=gene_level_a_site_set_counts_each_gene_once")
        for set_name, genes in gene_sets.items():
            if len(genes) < 5:
                lines.append(f"volcano_versus_enriched|set={set_name}|genes={len(genes)}|status=too_few_genes")
                continue
            try:
                result = _stats_tools.run_enrichment_from_list(ListEnrichmentRequest(
                    genes=genes, backgroundMode="experiment", backgroundGenes=background, topN=6,
                    minTermSize=20, maxTermSize=300, adjPValueCutoff=0.05, organism=organism))  # type: ignore[arg-type]
            except Exception as exc:
                lines.append(f"volcano_versus_enriched|set={set_name}|genes={len(genes)}|status=error|detail={_safe_context_text(exc)}")
                continue
            if not result.terms:
                lines.append(f"volcano_versus_enriched|set={set_name}|genes={len(genes)}|significant_terms=0")
                continue
            for rank, term in enumerate(result.terms[:6], start=1):
                lines.append(f"volcano_versus_enriched|set={set_name}|genes={len(genes)}|rank={rank}|term={_safe_context_text(term.name)}|"
                             f"source={_safe_context_text(term.source)}|overlap={term.intersectionSize}|term_size={term.termSize}|adj_p={_fmt_probability(float(term.adjPValue))}")
    return lines


def _primary_term_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    first = text.split(";", 1)[0].strip()
    return _safe_context_text(first or text)


def _preview_items(values: list[str], limit: int) -> tuple[list[str], bool]:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return [], False
    max_items = max(1, int(limit))
    trimmed = cleaned[:max_items]
    return trimmed, len(cleaned) > len(trimmed)


def _mode_fields(mode: ContextMode | None) -> dict[str, str]:
    """The view's selections as the text the evidence builders compare.

    Keys are lower-cased. Strings stay as written; booleans, numbers, lists and
    objects are written as JSON, so a switch reads "true"/"false" and a condition
    list reads as the JSON array it is -- the same text the pages used to send.
    An empty selection is no selection.
    """
    fields: dict[str, str] = {}
    for key, value in (mode or {}).items():
        if value is None or value == "":
            continue
        fields[str(key).lower()] = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return fields


def _normalize_stats_test_type(value: object) -> StatsTestType:
    """Keep AI context dispatch aligned with the statistical API contract."""
    mode = str(value or "unpaired").strip().lower()
    try:
        resolve_test_type(mode)
    except ValueError:
        return "unpaired"
    return cast(StatsTestType, mode)


def _stats_test_description(test_type: StatsTestType, *, control: bool = False) -> str:
    if control:
        return (
            "paired_experimental_differences_with_propagated_control_variance"
            if test_type == "paired"
            else "unpaired_propagated_variance_with_satterthwaite_degrees_of_freedom"
        )
    return _STATS_TEST_DESCRIPTIONS[test_type]


def _normalize_completeness_kind(workflow: str, mode: ContextMode | None = None) -> str:
    mode_pairs = _mode_fields(mode)
    requested = str(
        mode_pairs.get("kind")
        or mode_pairs.get("level")
        or mode_pairs.get("dataset")
        or ""
    ).strip().lower()
    if requested in _COMPLETENESS_KIND_LABELS:
        return requested
    if workflow == "phosphosite":
        return "phospho"
    if workflow == "phosphoprotein":
        return "phosprot"
    if workflow == "peptide":
        return "peptide"
    return "protein"


def _bool_from_mode(mode_pairs: dict[str, str], *keys: str, default: bool) -> bool:
    for key in keys:
        if key not in mode_pairs:
            continue
        value = str(mode_pairs.get(key, "")).strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
    return default


def _float_from_mode(
    mode_pairs: dict[str, str],
    *keys: str,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value_num = default
    for key in keys:
        if key not in mode_pairs:
            continue
        try:
            value_num = float(str(mode_pairs.get(key, "")).strip())
            break
        except Exception:
            continue
    if minimum is not None and value_num < minimum:
        value_num = minimum
    if maximum is not None and value_num > maximum:
        value_num = maximum
    return value_num


def _split_mode_list(value: str) -> list[str]:
    return parse_selection_list(value, accept_semicolons=True)


def _completeness_feature_rows(
    kind: str,
) -> tuple[float | None, int, list[tuple[int, int, float | None]], str | None]:
    if kind not in {"protein", "phospho", "phosprot"}:
        return None, 0, [], f"tables_not_available_for_level={kind}"
    try:
        payload = _completeness_tables(kind=kind, outlier_threshold=50.0, include_id=True)
    except Exception as exc:
        return None, 0, [], _safe_context_text(exc)

    overall_missing = float(payload.overallMissingPercent)
    sample_count = int(len(payload.sampleSummary))
    rows: list[tuple[int, int, float | None]] = []
    for item in payload.featureSummary:
        missing_value_raw = item.get("n_MissingProteinValues")
        count_raw = item.get("Counts")
        percent_raw = item.get("%_missing_values")
        try:
            missing_value = int(float(missing_value_raw))
            count_value = int(float(count_raw))
        except Exception:
            continue
        percent_value: float | None
        try:
            percent_value = float(percent_raw)
        except Exception:
            percent_value = None
        rows.append((missing_value, count_value, percent_value))
    rows.sort(key=lambda value: value[0])
    return overall_missing, sample_count, rows, None


def _excluded_all_missing_count(kind: str, *, include_id: bool) -> int | str:
    """Features with no value in any selected sample, or 'unknown'."""
    try:
        from app.services.completeness_tools import completeness_excluded_feature_count

        return int(completeness_excluded_feature_count(kind, include_id=bool(include_id)))
    except Exception:
        return "unknown"


def _completeness_tables_payload(
    kind: str,
    *,
    outlier_threshold: float,
    include_id: bool,
) -> tuple[float | None, int, list[dict[str, Any]], list[dict[str, Any]], list[str], str | None]:
    if kind not in {"protein", "phospho", "phosprot"}:
        return None, 0, [], [], [], f"tables_not_available_for_level={kind}"
    try:
        payload = _completeness_tables(
            kind=kind,
            outlier_threshold=float(outlier_threshold),
            include_id=bool(include_id),
        )
    except Exception as exc:
        return None, 0, [], [], [], _safe_context_text(exc)

    overall_missing = float(payload.overallMissingPercent)
    sample_rows = list(payload.sampleSummary)
    feature_rows = list(payload.featureSummary)
    outliers = [str(value) for value in payload.outliers]
    sample_count = len(sample_rows)
    return overall_missing, sample_count, sample_rows, feature_rows, outliers, None


def _normalize_stats_kind(workflow: str, mode: ContextMode | None = None) -> str:
    mode_pairs = _mode_fields(mode)
    requested = str(
        mode_pairs.get("kind")
        or mode_pairs.get("dataset")
        or mode_pairs.get("level")
        or ""
    ).strip().lower()
    if requested in {"protein", "phospho", "phosprot"}:
        return requested
    if workflow == "phosphosite":
        return "phospho"
    if workflow == "phosphoprotein":
        return "phosprot"
    return "protein"


def _entity_labels_from_stats_kind(kind: str) -> tuple[str, str]:
    if kind == "phospho":
        return _WORKFLOW_ENTITY_LABELS["phosphosite"]
    if kind == "phosprot":
        return _WORKFLOW_ENTITY_LABELS["phosphoprotein"]
    return _WORKFLOW_ENTITY_LABELS["protein"]


def _volcano_ranked_rows(
    frame: pd.DataFrame,
    *,
    label_column: str,
    group: str,
    limit: int,
    strategy: str = "balanced",
) -> tuple[pd.DataFrame, bool]:
    if frame.empty:
        return frame, False
    subset = frame.copy()
    subset[label_column] = subset[label_column].astype(str)
    subset["abs_log2FC"] = pd.to_numeric(subset["log2FC"], errors="coerce").fillna(0.0).astype(float).abs()
    subset["abs_neg_log10_selected_pval"] = (
        pd.to_numeric(subset["neg_log10_selected_pval"], errors="coerce").fillna(0.0).astype(float).abs()
    )
    if strategy == "fold_change_priority":
        subset["rank_score"] = subset["abs_log2FC"]
    else:
        subset["rank_score"] = subset["abs_log2FC"] * subset["abs_neg_log10_selected_pval"]

    if group == "up":
        subset = subset[subset["log2FC"] > 0].copy()
        if strategy == "fold_change_priority":
            subset = subset.sort_values(
                ["abs_log2FC", "log2FC", "abs_neg_log10_selected_pval", "selected_pval"],
                ascending=[False, False, False, True],
            )
        else:
            subset = subset.sort_values(
                ["rank_score", "abs_neg_log10_selected_pval", "log2FC"],
                ascending=[False, False, False],
            )
    else:
        subset = subset[subset["log2FC"] < 0].copy()
        if strategy == "fold_change_priority":
            subset = subset.sort_values(
                ["abs_log2FC", "log2FC", "abs_neg_log10_selected_pval", "selected_pval"],
                ascending=[False, True, False, True],
            )
        else:
            subset = subset.sort_values(
                ["rank_score", "abs_neg_log10_selected_pval", "log2FC"],
                ascending=[False, False, True],
            )
    if subset.empty:
        return subset, False
    total = int(subset.shape[0])
    trimmed = subset.head(max(1, int(limit))).copy()
    return trimmed, total > int(trimmed.shape[0])


def _parse_pca_mode(mode: ContextMode | None) -> tuple[str, str, str]:
    fields = _mode_fields(mode)
    method = fields.get("method", "PCA").strip() or "PCA"
    plot_dim = str(fields.get("plotdim", fields.get("plot_dim", "2D"))).strip().upper()
    if plot_dim not in {"2D", "3D"}:
        plot_dim = "2D"
    data_source = str(fields.get("datasource", fields.get("data_source", "data"))).strip().lower()
    return method, plot_dim, "imputed" if data_source == "imputed" else "data"


def _pca_variance_lines(
    workflow: str,
    *,
    method: str = "PCA",
    plot_dim: str = "2D",
    data_source: str = "data",
    scaling: str = "auto",
) -> list[str]:
    kind = _workflow_kind(workflow)
    lines: list[str] = []
    method_key = str(method or "PCA").strip().lower()
    target_dim = "3D" if str(plot_dim or "").strip().upper() == "3D" else "2D"

    if method_key != "pca":
        lines.append(
            f"pca_data|status=available|projection={target_dim}|method={_safe_context_text(method)}"
        )
        lines.append(
            f"pca_variance|status=not_applicable|reason=explained_pc_variance_is_defined_for_pca_only|method={_safe_context_text(method)}"
        )
        return lines

    pca_scores: pd.DataFrame | None = None
    explained = None
    axis_prefix = ""
    used_dim = target_dim
    projection_error: Exception | None = None

    try:
        pca_scores, explained, axis_prefix = _plot_images._pca_projection(
            kind,
            data_source=data_source,
            plot_dim=target_dim,
            method="PCA",
            scaling=scaling,
        )
    except Exception as exc:
        projection_error = exc

    if projection_error is not None or pca_scores is None:
        lines.append(
            f"pca_variance|status=unavailable|reason={_safe_context_text(projection_error)}"
        )
        return lines

    sample_count = int(pca_scores["sample"].astype(str).nunique()) if "sample" in pca_scores.columns else 0
    condition_count = (
        int(pca_scores["condition"].astype(str).nunique()) if "condition" in pca_scores.columns else 0
    )
    lines.append(
        f"pca_data|status=available|projection={used_dim}|sample_points={sample_count}|conditions={condition_count}"
    )

    if explained is None or axis_prefix != "PC":
        lines.append("pca_variance|status=unavailable|reason=explained_variance_not_computed")
        return lines

    explained_values = [float(value) for value in explained.tolist() if pd.notna(value)]
    if len(explained_values) < 2:
        lines.append("pca_variance|status=unavailable|reason=insufficient_components")
        return lines

    pc1 = explained_values[0]
    pc2 = explained_values[1]
    lines.append(
        f"pca_variance|PC1={pc1:.2f}|PC2={pc2:.2f}|PC1_PC2_total={(pc1 + pc2):.2f}|unit=percent_sample_variance"
    )

    if target_dim == "3D" and len(explained_values) >= 3:
        pc3 = explained_values[2]
        lines.append(
            f"pca_variance|PC3={pc3:.2f}|PC1_PC2_PC3_total={(pc1 + pc2 + pc3):.2f}|unit=percent_sample_variance"
        )

    component_columns = [column for column in ("PC1", "PC2", "PC3") if column in pca_scores.columns]
    if len(component_columns) >= 2 and "condition" in pca_scores.columns:
        scores = pca_scores.copy()
        scores["condition"] = scores["condition"].astype(str)
        scores["display_sample"] = condition_sample_labels(scores)
        for _, row in scores.iterrows():
            coordinates = "|".join(
                f"{column}={_fmt_value(float(row[column]))}" for column in component_columns
            )
            lines.append(
                f"pca_sample_score|sample={_safe_context_text(row['display_sample'])}|condition={_safe_context_text(row['condition'])}|{coordinates}"
            )

        condition_summaries: dict[str, tuple[list[float], float]] = {}
        for condition, subset in scores.groupby("condition", sort=False):
            centroid = [float(subset[column].mean()) for column in component_columns]
            squared_distances = []
            for _, row in subset.iterrows():
                squared_distances.append(
                    sum((float(row[column]) - centroid[index]) ** 2 for index, column in enumerate(component_columns))
                )
            within_rms = (sum(squared_distances) / max(1, len(squared_distances))) ** 0.5
            condition_summaries[str(condition)] = (centroid, within_rms)
            centroid_text = "|".join(
                f"centroid_{column}={_fmt_value(value)}"
                for column, value in zip(component_columns, centroid)
            )
            lines.append(
                f"pca_condition_geometry|condition={_safe_context_text(condition)}|sample_count={int(subset.shape[0])}|{centroid_text}|within_condition_rms_distance={_fmt_value(within_rms)}"
            )

        condition_names = list(condition_summaries)
        for left_index, left in enumerate(condition_names):
            for right in condition_names[left_index + 1 :]:
                left_centroid, left_rms = condition_summaries[left]
                right_centroid, right_rms = condition_summaries[right]
                centroid_distance = sum(
                    (left_value - right_value) ** 2
                    for left_value, right_value in zip(left_centroid, right_centroid)
                ) ** 0.5
                pooled_within = ((left_rms ** 2 + right_rms ** 2) / 2.0) ** 0.5
                ratio = centroid_distance / pooled_within if pooled_within > 0 else float("inf")
                lines.append(
                    "pca_condition_comparison|"
                    f"left={_safe_context_text(left)}|right={_safe_context_text(right)}|"
                    f"centroid_distance={_fmt_value(centroid_distance)}|pooled_within_condition_rms={_fmt_value(pooled_within)}|"
                    f"centroid_to_within_ratio={_fmt_value(ratio)}"
                )
        lines.append(
            "pca_geometry_rule|centroid_to_within_ratio_is_descriptive_only|no_universal_clean_separation_cutoff_is_assumed"
        )

    return lines


def _histogram_data_lines(workflow: str) -> list[str]:
    kind = _workflow_kind(workflow)
    try:
        frame = _plot_images.log2_qc_frame(kind)
        sample_columns = _plot_images._get_sample_columns(kind, frame)
        meta = _plot_images._metadata_for_kind(kind, frame, sample_columns).copy()
    except Exception as exc:
        return [f"histogram_data|status=unavailable|detail={_safe_context_text(exc)}"]
    if not sample_columns:
        return ["histogram_data|status=unavailable|detail=no_sample_columns"]

    numeric = frame[sample_columns].apply(pd.to_numeric, errors="coerce")
    lines = [
        f"histogram_data|status=available|sample_count={len(sample_columns)}|value_scale=log2_intensity"
    ]
    meta["sample"] = meta["sample"].astype(str)
    meta["condition"] = meta["condition"].astype(str)
    summaries: list[dict[str, Any]] = []
    for condition in meta["condition"].drop_duplicates().tolist():
        condition_columns = [
            sample
            for sample in meta.loc[meta["condition"] == condition, "sample"].tolist()
            if sample in numeric.columns
        ]
        if not condition_columns:
            continue
        subset = numeric[condition_columns]
        values = subset.mean(axis=1, skipna=True).dropna().astype(float)
        total_slots = int(subset.shape[0] * subset.shape[1])
        observed_slots = int(subset.notna().sum().sum())
        if values.empty or total_slots <= 0:
            continue
        missing_percent = ((total_slots - observed_slots) / total_slots) * 100.0
        summaries.append(
            {
                "condition": str(condition),
                "mean": float(values.mean()),
                "median": float(values.median()),
                # ddof=1 to match every statistical path; the assistant quotes this
                # to the user alongside numbers the analysis produced.
                "sd": float(values.std(ddof=1)),
                "skewness": float(values.skew()),
            }
        )
        lines.append(
            "histogram_condition_stats|"
            f"condition={_safe_context_text(condition)}|samples={len(condition_columns)}|entity_condition_means={int(values.shape[0])}|"
            f"missing_percent={_fmt_value(missing_percent)}|mean={_fmt_value(values.mean())}|median={_fmt_value(values.median())}|"
            f"sd={_fmt_value(values.std(ddof=1))}|Q1={_fmt_value(values.quantile(0.25))}|Q3={_fmt_value(values.quantile(0.75))}|"
            f"skewness={_fmt_value(values.skew())}"
        )
    if len(summaries) == 2:
        left, right = summaries
        lines.append(
            "histogram_answer_summary|comparison_is_descriptive=true|normality_not_proven=true|"
            f"left={_safe_context_text(left['condition'])}|right={_safe_context_text(right['condition'])}|"
            f"mean_difference_right_minus_left={_fmt_value(round(right['mean'], 2) - round(left['mean'], 2))}|"
            f"median_difference_right_minus_left={_fmt_value(round(right['median'], 2) - round(left['median'], 2))}|"
            f"sd_difference_right_minus_left={_fmt_value(round(right['sd'], 2) - round(left['sd'], 2))}|"
            f"skewness_difference_right_minus_left={_fmt_value(round(right['skewness'], 2) - round(left['skewness'], 2))}"
        )
    lines.append(
        "histogram_inference_rule|summary_statistics_support_location_spread_and_skew_comparisons_but_do_not_by_themselves_prove_normality"
    )
    return lines


def _abundance_data_lines(workflow: str, *, limit: int = 5, condition: str = "All Conditions") -> list[str]:
    kind = _workflow_kind(workflow)
    try:
        mean_intensities, conditions, _, key_column = _plot_images._abundance_mean_intensities(kind)
        if condition != "All Conditions":
            if condition not in conditions:
                raise ValueError(f"Condition '{condition}' not found.")
            conditions = [condition]
    except Exception as exc:
        return [f"abundance_data|status=unavailable|detail={_safe_context_text(exc)}"]

    # `robust_site_median` phosphoproteins are ratios to each site's own median,
    # not abundances; saying "intensity" here would put that in the answer.
    centred = phosprot_values_are_centred(kind)
    value_label = (
        "log10_of_mean_ratio_to_site_median"
        if centred
        else "log10_of_mean_linear_intensity"
    )
    measure_key = "log10_mean_ratio_to_site_median" if centred else "log10_mean_intensity"
    lines = [
        f"abundance_data|status=available|conditions={len(conditions)}|identifier_column={_safe_context_text(key_column)}|value={value_label}"
    ]
    for condition in conditions:
        ranked = mean_intensities[[key_column, condition]].dropna(subset=[condition]).copy()
        ranked = ranked.sort_values(condition, ascending=False).head(max(1, int(limit)))
        for rank, (_, row) in enumerate(ranked.iterrows(), start=1):
            lines.append(
                "abundance_top_entity|"
                f"condition={_safe_context_text(condition)}|rank={rank}|identifier={_safe_context_text(row[key_column])}|"
                f"{measure_key}={float(row[condition]):.4f}"
            )
    return lines


def _correlation_data_lines(workflow: str, *, limit: int = 6) -> list[str]:
    kind = _workflow_kind(workflow)
    try:
        # Must match qc_correlation_plot, which computes Pearson r on log2 values.
        # Reconstructed linear intensities give a different r for the same samples
        # (mean 0.87 vs 0.94 on replicate data), so the chat answer would contradict
        # the figure the user is looking at.
        frame = _plot_images.log2_qc_frame(kind)
        sample_columns = _plot_images._get_sample_columns(kind, frame)
        meta = _plot_images._metadata_for_kind(kind, frame, sample_columns).copy()
    except Exception as exc:
        return [f"correlation_data|status=unavailable|detail={_safe_context_text(exc)}"]
    if len(sample_columns) < 2:
        return ["correlation_data|status=unavailable|detail=fewer_than_two_samples"]

    meta["sample"] = meta["sample"].astype(str)
    meta["condition"] = meta["condition"].astype(str)
    meta["display_sample"] = condition_sample_labels(meta)
    rename_map = dict(zip(meta["sample"], meta["display_sample"]))
    condition_by_display = dict(zip(meta["display_sample"], meta["condition"]))
    numeric = frame[sample_columns].rename(columns=rename_map).apply(pd.to_numeric, errors="coerce")
    correlations = numeric.corr(method="pearson")

    pairs: list[dict[str, Any]] = []
    labels = correlations.columns.astype(str).tolist()
    for left_index, left in enumerate(labels):
        for right in labels[left_index + 1 :]:
            value = correlations.loc[left, right]
            if pd.isna(value):
                continue
            overlap = int(numeric[[left, right]].dropna().shape[0])
            pairs.append(
                {
                    "left": left,
                    "right": right,
                    "r": float(value),
                    "overlap": overlap,
                    "within": condition_by_display.get(left) == condition_by_display.get(right),
                }
            )
    if not pairs:
        return ["correlation_data|status=unavailable|detail=no_finite_pairs"]

    lines = [f"correlation_data|status=available|sample_count={len(labels)}|pair_count={len(pairs)}"]
    for group_name, within in (("within_condition", True), ("between_condition", False)):
        values = pd.Series([pair["r"] for pair in pairs if pair["within"] is within], dtype=float)
        if values.empty:
            continue
        lines.append(
            "correlation_group_summary|"
            f"group={group_name}|pair_count={int(values.shape[0])}|mean_r={float(values.mean()):.4f}|"
            f"median_r={float(values.median()):.4f}|min_r={float(values.min()):.4f}|max_r={float(values.max()):.4f}"
        )

    sorted_pairs = sorted(pairs, key=lambda item: item["r"])
    for rank, pair in enumerate(sorted_pairs[: max(1, int(limit))], start=1):
        lines.append(
            "correlation_low_pair|"
            f"rank={rank}|"
            f"left={_safe_context_text(pair['left'])}|right={_safe_context_text(pair['right'])}|"
            f"pearson_r={float(pair['r']):.4f}|pairwise_complete_proteins={pair['overlap']}|"
            f"relationship={'within_condition' if pair['within'] else 'between_condition'}"
        )
    lowest = sorted_pairs[0]
    within_values = pd.Series([pair["r"] for pair in pairs if pair["within"] is True], dtype=float)
    between_values = pd.Series([pair["r"] for pair in pairs if pair["within"] is False], dtype=float)
    group_comparison = "unavailable"
    if not within_values.empty and not between_values.empty:
        if float(within_values.median()) > float(between_values.median()):
            group_comparison = "within_condition_median_is_higher"
        elif float(within_values.median()) < float(between_values.median()):
            group_comparison = "between_condition_median_is_higher"
        else:
            group_comparison = "medians_are_equal"
    lines.append(
        "correlation_answer_summary|"
        f"lowest_pair={_safe_context_text(lowest['left'])}_vs_{_safe_context_text(lowest['right'])}|"
        f"lowest_pearson_r={float(lowest['r']):.4f}|group_median_comparison={group_comparison}|"
        "comparison_is_descriptive_not_a_quality_classification=true"
    )
    lines.append(
        "correlation_inference_rule|exact_correlations_and_group_summaries_are_descriptive|quality_or_outlier_labels_require_a_defined_cutoff"
    )
    return lines


def _coverage_text_from_rows(
    rows: pd.DataFrame,
    *,
    workflow: str,
    total_features: int | None,
    palette: dict[str, str],
    level: str = "peptide",
) -> str:
    _, entity_plural = _WORKFLOW_ENTITY_LABELS.get(workflow, _WORKFLOW_ENTITY_LABELS["protein"])
    if workflow == "peptide" and level == "precursor":
        entity_plural = "precursors"
    if rows.empty:
        return (
            f"coverage|workflow={workflow}|entity={entity_plural}|status=empty"
        )

    data = rows.copy()
    data["Sample"] = data["Sample"].astype(str)
    data["Condition"] = data["Condition"].astype(str)
    data["Count"] = pd.to_numeric(data["Count"], errors="coerce")
    data = data.dropna(subset=["Count"]).reset_index(drop=True)
    if data.empty:
        return (
            f"coverage|workflow={workflow}|entity={entity_plural}|status=no_numeric_values"
        )

    sample_count = int(data["Sample"].nunique())
    conditions = _condition_order(data)
    condition_count = len(conditions)

    lines: list[str] = []
    lines.append(
        f"coverage_overview|workflow={workflow}|entity={entity_plural}|samples={sample_count}|conditions={condition_count}|total_features={total_features if total_features is not None else 'unknown'}"
    )
    lines.append(
        "coverage_formula|detected_features=total_features-missing_values_per_sample"
    )
    lines.append(
        "coverage_visual|bars=detected_features_per_sample|bar_color=condition"
    )
    lines.append(
        "coverage_reference_line|color=red|value="
        f"{total_features if total_features is not None else 'unknown'}|"
        f"description=total_unique_{entity_plural}_over_all_samples"
    )

    for condition in conditions:
        subset = data[data["Condition"] == condition].copy()
        subset = subset.sort_values("Sample")
        sample_names = subset["Sample"].astype(str).tolist()
        sample_names_text = ",".join(sample_names)
        sample_values = ";".join(
            [f"{row['Sample']}={_fmt_value(float(row['Count']))}" for _, row in subset.iterrows()]
        )
        values = subset["Count"].astype(float)
        color = palette.get(condition, "")
        lines.append(
            f"condition|name={condition}|sample_count={len(sample_names)}|sample_names={sample_names_text}"
        )
        lines.append(
            f"sample_values|condition={condition}|values={sample_values}"
        )
        lines.append(
            f"condition_stats|name={condition}|mean={_fmt_value(values.mean())}|median={_fmt_value(values.median())}|min={_fmt_value(values.min())}|max={_fmt_value(values.max())}|color={color if color else 'unassigned'}"
        )

    highest = data.loc[data["Count"].idxmax()]
    lowest = data.loc[data["Count"].idxmin()]
    lines.append(
        "coverage_answer_summary|sample_values_are_final_computed_counts=true|do_not_recalculate_from_assumed_missingness=true|"
        f"highest_sample={_safe_context_text(highest['Sample'])}|highest_count={_fmt_value(highest['Count'])}|"
        f"lowest_sample={_safe_context_text(lowest['Sample'])}|lowest_count={_fmt_value(lowest['Count'])}"
    )

    return "\n".join(lines)


def general_proteomics_context(workflow: str = "protein") -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    entity_singular, entity_plural = _workflow_entity_labels(workflow_key)
    lines = [
        f"project_scope|domain=mass_spectrometry_proteomics|active_workflow={workflow_key}|entity_singular={entity_singular}|entity_plural={entity_plural}",
        f"project_state|active_dataset_package={_safe_context_text(get_active_package())}",
    ]
    try:
        datasets = get_all_current_datasets()
    except Exception as exc:
        lines.append(f"project_datasets|status=unavailable|detail={_safe_context_text(exc)}")
        return _text_payload("general_proteomics_context", "\n".join(lines))

    for kind in ("protein", "phospho", "phosprot", "peptide"):
        stored = datasets.get(kind)
        if stored is None:
            lines.append(f"project_dataset|kind={kind}|status=not_loaded")
            continue
        filename = _safe_context_text(getattr(stored, "filename", "")) or "unknown"
        frame = getattr(stored, "frame", None)
        if isinstance(frame, pd.DataFrame):
            dataset_details = f"rows={int(frame.shape[0])}|columns={int(frame.shape[1])}"
        else:
            dataset_details = "storage=local_path"

        if kind == "peptide":
            lines.append(
                f"project_dataset|kind={kind}|status=loaded|filename={filename}|{dataset_details}|annotation=not_applicable"
            )
            continue

        annotation = get_annotation(kind)  # type: ignore[arg-type]
        if annotation is None:
            lines.append(
                f"project_dataset|kind={kind}|status=loaded|filename={filename}|{dataset_details}|annotation=not_available"
            )
            continue
        metadata = annotation.metadata.copy()
        sample_count = int(metadata["sample"].nunique()) if "sample" in metadata.columns else 0
        condition_count = int(metadata["condition"].nunique()) if "condition" in metadata.columns else 0
        imputation = annotation.imputation
        imputation_text = "none"
        imputation_mode = str(getattr(imputation, "mode", "none")).strip().lower()
        if imputation is not None and imputation_mode != "none":
            if imputation_mode == "numerical":
                settings = f"downshift={imputation.downShift}:width={imputation.width}"
            else:
                settings = f"q={imputation.qValue}:adjust_std={imputation.adjustStd}"
            imputation_text = (
                f"configured:{_safe_context_text(imputation_mode)}:{settings}:"
                f"seed={imputation.seed}:sample_wise={str(bool(imputation.sampleWise)).lower()}:"
                f"applied={str(bool(imputation.applied)).lower()}:"
                f"missing_before={imputation.missingBefore}:missing_after={imputation.missingAfter}"
            )
            if imputation_mode not in {"numerical", "quantile"}:
                imputation_text = (
                    "restored:unknown:parameters=unknown:"
                    f"applied={str(bool(imputation.applied)).lower()}"
                )
        lines.append(
            f"project_dataset|kind={kind}|status=loaded|filename={filename}|{dataset_details}|annotation=available|"
            f"filtered_rows={int(annotation.filtered_data.shape[0])}|samples={sample_count}|conditions={condition_count}|"
            f"data_are_log2={str(bool(annotation.is_log2_transformed)).lower()}|imputation={imputation_text}|"
            f"normalization={annotation.filter_config.normalization}|normalization_scope=within_this_application_only"
        )
        # What the user chose for filtering, readable (never settable) by the assistant
        # (2026-10-09: "is my phospho data filtered by localization probability?" had no answer).
        config = annotation.filter_config
        rule = (f"at_least_{config.minPresent}_valid_values" if config.method == "at_least_n"
                else f"at_least_{_fmt_value(config.minPercentage)}_percent_valid_values")
        lines.append(
            f"project_filter|kind={kind}|valid_value_filter={'none' if config.method == 'at_least_n' and config.minPresent == 0 else rule}"
            f"|filter_scope={config.mode}|rows_before={int(frame.shape[0]) if isinstance(frame, pd.DataFrame) else 'unknown'}"
            f"|rows_after={int(annotation.filtered_data.shape[0])}|chosen_by_the_user_on=Data_Annotation"
        )
        if kind == "phospho":
            from app.services.phospho_localization import get_localization_cutoff

            lines.append(
                f"project_localization|kind=phospho|ptm_localization_probability_min={_fmt_value(get_localization_cutoff())}"
                "|rule=sites_below_cutoff_are_left_out_of_every_phosphosite_module|zero_keeps_every_site"
                "|default=0|changed_by_the_user_on=QC_Pipeline_Localization_probability_cutoff"
            )
            # How many sites common cutoffs would keep, counted read-only so "what if I set
            # 0.75?" has an answer without changing anything (2026-10-09).
            probabilities = (pd.to_numeric(annotation.filtered_data["PTM_localization"], errors="coerce")
                             if "PTM_localization" in annotation.filtered_data.columns else None)
            if probabilities is not None:
                kept = "|".join(f"sites_at_or_above_{_fmt_value(level)}={int((probabilities >= level).sum())}"
                                for level in (0.5, 0.75, 0.9, 0.99))
                lines.append(f"project_localization_counts|kind=phospho|sites_total={int(probabilities.shape[0])}|{kept}"
                             f"|sites_without_probability={int(probabilities.isna().sum())}"
                             "|scope=rows_after_the_valid_value_filter|read_only_estimate_nothing_changed")
    return _text_payload("general_proteomics_context", "\n".join(lines))


def qc_coverage_plot_context(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    parameters = _mode_fields(mode)
    level = parameters.get("level", "peptide")
    try:
        if workflow_key == "peptide":
            rows, total_features = _coverage_rows_from_peptide(
                quantity_column=parameters.get("quantitycolumn") or None, level=level)
        else:
            rows, total_features = _coverage_rows_from_wide(_workflow_kind(workflow_key))
        conditions = rows["Condition"].astype(str).tolist() if "Condition" in rows.columns else []
        palette = _condition_palette_for_workflow(workflow_key, conditions)
        text = _coverage_text_from_rows(
            rows,
            workflow=workflow_key,
            total_features=total_features,
            palette=palette,
            level=level,
        )
    except Exception as exc:
        _, entity_plural = _WORKFLOW_ENTITY_LABELS.get(workflow_key, _WORKFLOW_ENTITY_LABELS["protein"])
        if workflow_key == "peptide" and level == "precursor":
            entity_plural = "precursors"
        text = (
            f"The bars of the plot show the number of {entity_plural} per sample colored by condition. "
            f"Coverage text generation is currently unavailable: {exc}"
        )
    return _text_payload("qc_coverage_plot", text)


def qc_histogram_intensity(workflow: str = "protein") -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    entity_singular, entity_plural = _workflow_entity_labels(workflow_key)
    text = (
        "The rendered density curves are calculated on a per-condition basis: "
        f"for each {entity_singular}, the mean value across all replicates within each condition is calculated row-wise. "
        "The resulting condition-specific vectors are the values summarized below. "
        f"Use workflow-appropriate terminology ({entity_plural}) in explanations. "
        "The context includes statistics calculated from the same row-wise condition means used by the plot. "
        "Use them for descriptive comparisons of location, spread, and skew only.\n"
        + "\n".join(_histogram_data_lines(workflow_key))
    )
    return _text_payload("qc_histogram_intensity", text)


def qc_boxplot_intensity(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_key = _normalize_boxplot_mode(_mode_fields(mode).get("mode", "Mean"))
    entity_singular, entity_plural = _workflow_entity_labels(workflow_key)

    try:
        table = _table_functions.qc_boxplot_table(_workflow_kind(workflow_key), mode=mode_key).copy()
    except Exception as exc:
        return _text_payload(
            "qc_boxplot_intensity",
            (
                f"boxplot_overview|workflow={workflow_key}|entity={entity_plural}|mode={mode_key}|status=error\n"
                f"boxplot_error|detail={str(exc).replace('|', '/').replace(chr(10), ' ')}"
            ),
        )

    lines: list[str] = []
    lines.append(
        f"boxplot_overview|workflow={workflow_key}|entity={entity_plural}|mode={mode_key}|rows={int(table.shape[0])}"
    )
    lines.append(
        "boxplot_general|per_condition_processing=for_each_entity_extract_condition_values_from_replicates"
    )
    lines.append(
        "boxplot_definition|median=50th_percentile|IQR=Q3-Q1|whiskers=outermost_observed_values_within_the_1.5_IQR_fences|fences=Q1-1.5xIQR_to_Q3+1.5xIQR|outliers=observations_outside_the_fences"
    )

    if mode_key == "Single":
        lines.append(
            "boxplot_visual|mode=Single|boxes=sample_wise|color=condition|description=one_boxplot_per_sample_colored_by_condition"
        )
    else:
        lines.append(
            "boxplot_visual|mode=Mean|boxes=condition_wise|description=one_boxplot_per_condition_using_rowwise_condition_means"
        )

    if table.empty:
        lines.append("boxplot_data|status=empty")
        return _text_payload("qc_boxplot_intensity", "\n".join(lines))

    data = table.copy()
    numeric_columns = ["mean", "median", "Q1", "Q3", "lower_whisker", "upper_whisker"]
    for column in numeric_columns:
        if column in data.columns:
            data[column] = pd.to_numeric(data[column], errors="coerce")

    if mode_key == "Mean":
        if "Condition" not in data.columns:
            lines.append("boxplot_data|status=missing_condition_column")
            return _text_payload("qc_boxplot_intensity", "\n".join(lines))

        data["Condition"] = data["Condition"].astype(str)
        conditions = data["Condition"].tolist()
        palette = _condition_palette_for_workflow(workflow_key, conditions)
        for _, row in data.iterrows():
            condition = str(row.get("Condition", "")).strip() or "unknown"
            color = palette.get(condition, "")
            lines.append(
                "boxplot_condition|"
                f"name={condition}|mean={_fmt_value(row.get('mean', 0.0))}|median={_fmt_value(row.get('median', 0.0))}|"
                f"Q1={_fmt_value(row.get('Q1', 0.0))}|Q3={_fmt_value(row.get('Q3', 0.0))}|"
                f"lower_whisker={_fmt_value(row.get('lower_whisker', 0.0))}|upper_whisker={_fmt_value(row.get('upper_whisker', 0.0))}|"
                f"color={color if color else 'unassigned'}"
            )
        median_rows = data.dropna(subset=["median"])
        if not median_rows.empty:
            highest = median_rows.loc[median_rows["median"].idxmax()]
            lowest = median_rows.loc[median_rows["median"].idxmin()]
            lines.append(
                "boxplot_answer_summary|comparison_is_descriptive=true|"
                f"highest_median_condition={_safe_context_text(highest['Condition'])}|highest_median={_fmt_value(highest['median'])}|"
                f"lowest_median_condition={_safe_context_text(lowest['Condition'])}|lowest_median={_fmt_value(lowest['median'])}"
            )
        if int(data.shape[0]) == 2:
            left = data.iloc[0]
            right = data.iloc[1]
            left_iqr = float(left["Q3"] - left["Q1"])
            right_iqr = float(right["Q3"] - right["Q1"])
            lines.append(
                "boxplot_numeric_comparison|"
                f"left={_safe_context_text(left['Condition'])}|right={_safe_context_text(right['Condition'])}|"
                f"mean_difference_right_minus_left={_fmt_value(right['mean'] - left['mean'])}|"
                f"median_difference_right_minus_left={_fmt_value(right['median'] - left['median'])}|"
                f"left_IQR={_fmt_value(left_iqr)}|right_IQR={_fmt_value(right_iqr)}|"
                f"IQR_difference_right_minus_left={_fmt_value(right_iqr - left_iqr)}"
            )
    else:
        if "Sample" not in data.columns:
            lines.append("boxplot_data|status=missing_sample_column")
            return _text_payload("qc_boxplot_intensity", "\n".join(lines))

        data["Sample"] = data["Sample"].astype(str)
        data["Condition"] = data["Sample"].map(_extract_condition_from_sample)
        conditions = data["Condition"].tolist()
        palette = _condition_palette_for_workflow(workflow_key, conditions)

        condition_order = _condition_order(data[["Condition"]].copy())
        lines.append(
            f"boxplot_samples|sample_count={int(data['Sample'].nunique())}|condition_count={len(condition_order)}"
        )
        for condition in condition_order:
            subset = data[data["Condition"] == condition].copy()
            sample_names = subset["Sample"].astype(str).tolist()
            color = palette.get(condition, "")
            median_values = pd.to_numeric(subset["median"], errors="coerce").dropna()
            lines.append(
                f"boxplot_condition_samples|name={condition}|sample_count={len(sample_names)}|sample_names={','.join(sample_names)}|color={color if color else 'unassigned'}"
            )
            if not median_values.empty:
                lines.append(
                    "boxplot_condition_median_stats|"
                    f"name={condition}|median_mean={_fmt_value(float(median_values.mean()))}|"
                    f"median_min={_fmt_value(float(median_values.min()))}|median_max={_fmt_value(float(median_values.max()))}"
                )

        for _, row in data.iterrows():
            sample = str(row.get("Sample", "")).strip() or "unknown"
            condition = str(row.get("Condition", "")).strip() or "unknown"
            lines.append(
                "boxplot_sample|"
                f"condition={condition}|sample={sample}|mean={_fmt_value(row.get('mean', 0.0))}|"
                f"median={_fmt_value(row.get('median', 0.0))}|Q1={_fmt_value(row.get('Q1', 0.0))}|Q3={_fmt_value(row.get('Q3', 0.0))}|"
                f"lower_whisker={_fmt_value(row.get('lower_whisker', 0.0))}|upper_whisker={_fmt_value(row.get('upper_whisker', 0.0))}"
            )

    lines.append(
        "boxplot_evidence_limit|inferential_test_results=not_available|outlier_count=not_available|full_distribution_shape=not_available|"
        "report_only_numerical_differences_from_available_summary_statistics|do_not_assign_importance_or_claim_outlier_presence_or_shape_similarity"
    )

    return _text_payload("qc_boxplot_intensity", "\n".join(lines))


def _annotation_normalization(kind) -> str:
    """The normalization the session applied at this level ("none" when unset)."""
    from app.services.annotation_store import get_annotation

    annotation = get_annotation(kind)
    config = getattr(annotation, "filter_config", None) if annotation is not None else None
    return str(getattr(config, "normalization", "") or "none").strip().lower() or "none"


def qc_cov_plot(workflow: str = "protein") -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    _, entity_plural = _workflow_entity_labels(workflow_key)

    try:
        table = _table_functions.qc_cv_table(_workflow_kind(workflow_key)).copy()
    except Exception as exc:
        return _text_payload(
            "qc_cov_plot",
            (
                f"cov_overview|workflow={workflow_key}|entity={entity_plural}|status=error\n"
                f"cov_error|detail={str(exc).replace('|', '/').replace(chr(10), ' ')}"
            ),
        )

    lines: list[str] = []
    lines.append(
        f"cov_overview|workflow={workflow_key}|entity={entity_plural}|rows={int(table.shape[0])}"
    )
    lines.append(
        "cov_general|description=condition_wise_coefficient_of_variation_distributions_visualized_as_boxplots"
    )
    lines.append(
        "cov_general|purpose=assess_replicate_consistency_within_each_condition_using_relative_variability"
    )
    lines.append(
        "cov_processing|minimum_replicates_per_condition=2"
    )
    lines.append(
        "cov_processing|steps=extract_condition_samples_compute_featurewise_mean_and_sd_compute_cv_remove_undefined_values_build_condition_distribution"
    )
    normalization = _annotation_normalization(_workflow_kind(workflow_key))
    source = {
        "none": "uploaded_unnormalized_non_imputed_data_back_transformed_to_linear",
        "vsn": "unnormalized_data_of_the_same_rows_because_vsn_output_is_not_linear",
    }.get(normalization, f"{normalization}_normalized_non_imputed_data_back_transformed_to_linear")
    lines.append(
        "cov_formula|CV=(SD/mean)*100|SD=sample_standard_deviation_ddof_1|"
        f"scale=linear_intensity|normalization={normalization}|source={source}|"
        "log2_uploads=back_transformed_to_linear|missing=excluded_not_zero_filled|nonfinite_CV=excluded"
    )
    lines.append(
        "cov_boxplot_definition|median=50th_percentile|IQR=Q3-Q1|whiskers=outermost_observed_values_within_the_1.5_IQR_fences|fences=Q1-1.5xIQR_to_Q3+1.5xIQR|outliers=observations_outside_the_fences"
    )

    if table.empty:
        lines.append("cov_data|status=empty")
        return _text_payload("qc_cov_plot", "\n".join(lines))

    data = table.copy()
    required_columns = ["Condition", "mean", "median", "Q1", "Q3", "lower_whisker", "upper_whisker"]
    for column in required_columns:
        if column not in data.columns:
            lines.append(f"cov_data|status=missing_column|column={column}")
            return _text_payload("qc_cov_plot", "\n".join(lines))

    data["Condition"] = data["Condition"].astype(str)
    numeric_columns = ["mean", "median", "Q1", "Q3", "lower_whisker", "upper_whisker"]
    for column in numeric_columns:
        data[column] = pd.to_numeric(data[column], errors="coerce")

    condition_count = int(data["Condition"].nunique())
    lines.append(f"cov_conditions|count={condition_count}")

    for _, row in data.iterrows():
        condition = str(row.get("Condition", "")).strip() or "unknown"
        lines.append(
            "cov_condition|"
            f"name={condition}|mean_cv={_fmt_value(row.get('mean', 0.0))}|median_cv={_fmt_value(row.get('median', 0.0))}|"
            f"Q1_cv={_fmt_value(row.get('Q1', 0.0))}|Q3_cv={_fmt_value(row.get('Q3', 0.0))}|"
            f"lower_whisker_cv={_fmt_value(row.get('lower_whisker', 0.0))}|upper_whisker_cv={_fmt_value(row.get('upper_whisker', 0.0))}"
        )

    median_rows = data.dropna(subset=["median"])
    if not median_rows.empty:
        lowest = median_rows.loc[median_rows["median"].idxmin()]
        highest = median_rows.loc[median_rows["median"].idxmax()]
        displayed = median_rows["median"].map(_fmt_value)
        low_names = ", ".join(median_rows.loc[displayed == _fmt_value(lowest["median"]), "Condition"])
        high_names = ", ".join(median_rows.loc[displayed == _fmt_value(highest["median"]), "Condition"])
        lines.append(
            "cov_answer_summary|lower_median_cv_means_more_consistent_by_this_descriptive_metric=true|"
            f"lowest_median_cv_condition={_safe_context_text(low_names)}|lowest_median_cv={_fmt_value(lowest['median'])}|"
            f"highest_median_cv_condition={_safe_context_text(high_names)}|highest_median_cv={_fmt_value(highest['median'])}|"
            f"all_medians_equal_at_reported_precision={str(displayed.nunique() == 1).lower()}|"
            "quality_cutoff_applied=false"
        )

    lines.append(
        "cov_quality_guidance|general_check=similar_box_shapes_comparable_IQR_and_medians_support_replicate_consistency"
    )
    lines.append(
        "cov_quality_guidance|general_warning_signals=wide_boxes_high_medians_or_many_outliers_can_indicate_higher_variability_or_reproducibility_issues"
    )

    return _text_payload("qc_cov_plot", "\n".join(lines))


def qc_pca_plot_context(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    _, entity_plural = _workflow_entity_labels(workflow_key)
    method, plot_dim, data_source = _parse_pca_mode(mode)
    mode_pairs = _mode_fields(mode)
    random_state = int(
        _float_from_mode(mode_pairs, "randomstate", "random_state", default=42.0, minimum=0.0)
    )
    method_clean = _safe_context_text(method)

    lines: list[str] = []
    lines.append(
        f"pca_overview|workflow={workflow_key}|entity={entity_plural}|plot_types=static_and_interactive|dimensions=2D_or_3D"
    )
    lines.append(
        f"pca_active_view|method={method_clean}|plot_dim={plot_dim}|data_source={data_source}|random_state={random_state}"
    )
    lines.append(
        "pca_description|goal=reduce_dimensionality_and_visualize_relationships_between_samples_based_on_measured_entities"
    )
    lines.append(
        "pca_points|each_point_represents=one_sample"
    )
    lines.append(
        "pca_components|principal_components=linear_combinations_of_all_measured_entities_using_variance_and_covariance_structure"
    )
    lines.append(
        "pca_component_order|PC1=max_variance|PC2=next_variance_orthogonal_to_PC1|PCn=remaining_orthogonal_variance"
    )
    lines.append(
        "pca_projection|benefit=condense_high_dimensional_information_into_few_axes_to_reveal_sample_patterns_clusters_and_trends"
    )
    lines.append(
        "pca_reproducibility|PCA_is_deterministic|UMAP_tSNE_and_KMeans_use_the_exposed_request_local_random_state"
    )
    lines.append(
        "pca_quality_guidance|type=checklist_only_not_findings|check=inspect_within_condition_replicate_compactness"
    )
    lines.append(
        "pca_quality_guidance|type=checklist_only_not_findings|check=inspect_between_condition_separation_and_overlap_patterns"
    )
    lines.append(
        "pca_quality_guidance|type=checklist_only_not_findings|check=inspect_for_possible_outlier_samples"
    )
    lines.append(
        "pca_quality_guidance|coordinates_and_geometry_may_be_reported_descriptively|outlier_or_clean_separation_labels_require_a_defined_rule"
    )
    lines.append(
        "pca_usage|supports=identify_outliers_assess_condition_separation_evaluate_overall_dataset_structure"
    )
    lines.extend(
        _pca_variance_lines(
            workflow_key,
            method=method,
            plot_dim=plot_dim,
            data_source=data_source,
            scaling=mode_pairs.get("scaling", "auto"),
        )
    )

    conditions = _conditions_for_workflow(workflow_key)
    lines.append(f"pca_conditions|count={len(conditions)}")

    return _text_payload("qc_pca_plot", "\n".join(lines))


def qc_abundance_plot_context(
    workflow: str = "protein",
    mode: ContextMode | None = None,
) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    entity_singular, entity_plural = _workflow_entity_labels(workflow_key)

    lines: list[str] = []
    lines.append(
        f"abundance_overview|workflow={workflow_key}|entity={entity_plural}"
    )
    lines.append(
        "abundance_scope|purpose=inspect_global_intensity_patterns_and_explore_specific_entities_of_interest"
    )
    lines.append(
        "abundance_processing|step=group_samples_by_condition_and_compute_featurewise_mean_across_replicates"
    )
    lines.append(
        "abundance_transform|formula=log10(mean_intensity_across_replicates+1)|reason=avoid_undefined_values_at_zero"
    )
    lines.append(
        "abundance_ranking|x_axis=feature_rank_within_condition_sorted_by_transformed_intensity_descending"
    )
    lines.append(
        "abundance_axes|x=rank_high_to_low_intensity|y=log10_transformed_mean_intensity"
    )
    lines.append(
        "abundance_points|each_point_represents=one_entity_mean_within_one_condition"
    )
    lines.append(
        f"abundance_focus|supports=highlight_or_prioritize_selected_{entity_plural}_during_interpretation"
    )
    lines.append(
        "abundance_interpretation|rank_order_view_supports=assess_dynamic_range_compare_conditions_and_inspect_overall_intensity_distribution_shape"
    )
    lines.append(
        "abundance_special_case|phosphoprotein_context=optional_truncation_of_extended_ptm_text_for_readability"
    )
    lines.append(
        "abundance_quality_guidance|type=checklist_only_not_findings|check=inspect_curve_smoothness_and_gradual_intensity_decay"
    )
    lines.append(
        "abundance_quality_guidance|type=checklist_only_not_findings|check=inspect_pattern_consistency_across_conditions_or_replicates"
    )
    lines.append(
        "abundance_quality_guidance|type=checklist_only_not_findings|check=inspect_for_sharp_deviations_or_possible_outlier_entities"
    )
    lines.append(
        "abundance_quality_guidance|ranked_entities_and_values_may_be_reported_descriptively|curve_shape_or_quality_claims_require_matching_evidence_and_a_defined_rule"
    )
    lines.extend(
        _abundance_data_lines(
            workflow_key,
            condition=_mode_fields(mode).get("condition", "All Conditions"),
            limit=6,
        )
    )

    return _text_payload("qc_abundance_plot", "\n".join(lines))


def qc_correlation_plot_context(
    workflow: str = "protein",
) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    _, entity_plural = _workflow_entity_labels(workflow_key)

    lines: list[str] = []
    lines.append(
        f"correlation_overview|workflow={workflow_key}|entity={entity_plural}|modes=matrix_and_ellipse"
    )
    lines.append(
        "correlation_scope|purpose=visualize_pairwise_sample_similarity_assess_replicate_consistency_and_flag_possible_anomalies"
    )
    lines.append(
        "correlation_input|vectors=original_scale_sample_intensity_vectors_used_by_the_rendered_plot"
    )
    lines.append(
        "correlation_formula|pearson_r=cov(x_i,x_j)/(sigma_x_i*sigma_x_j)"
    )
    lines.append(
        "correlation_distance|d_ij=1-r_ij"
    )
    lines.append(
        "correlation_clustering|step=apply_hierarchical_clustering_on_distance_matrix_then_reorder_by_dendrogram"
    )
    lines.append(
        "correlation_structure|effect=reordered_map_groups_similar_samples_and_reveals_block_patterns"
    )
    lines.append(
        "correlation_matrix_mode|representation=reordered_correlation_matrix_with_diverging_scale"
    )
    lines.append(
        "correlation_matrix_mode|interpretation=one_end_high_positive_other_end_weak_or_negative_center_near_zero"
    )
    lines.append(
        "correlation_ellipse_mode|encoding=ellipse_shape_and_orientation_represent_magnitude_and_sign_of_correlation"
    )
    lines.append(
        "correlation_ellipse_mode|magnitude_rule=abs_r_toward_1_narrower_abs_r_toward_0_more_circular"
    )
    lines.append(
        "correlation_ellipse_mode|sign_rule=orientation_differs_for_positive_vs_negative_correlation"
    )
    lines.append(
        "correlation_usage|supports=global_sample_relationship_review_and_detection_of_possible_batch_or_labeling_issues"
    )
    lines.append(
        "correlation_quality_guidance|type=checklist_only_not_findings|check=inspect_within_group_similarity_patterns"
    )
    lines.append(
        "correlation_quality_guidance|type=checklist_only_not_findings|check=inspect_clustering_smoothness_and_block_consistency"
    )
    lines.append(
        "correlation_quality_guidance|type=checklist_only_not_findings|check=inspect_for_weak_or_asymmetric_sample_relationships"
    )
    lines.append(
        "correlation_quality_guidance|pairwise_coefficients_and_group_summaries_may_be_reported_descriptively|quality_or_outlier_labels_require_a_defined_rule"
    )
    lines.extend(
        _correlation_data_lines(
            workflow_key,
            limit=12,
        )
    )

    return _text_payload("qc_correlation_plot", "\n".join(lines))


def peptide_rt_plot_context(workflow: str = "peptide", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)

    method = str(mode_pairs.get("method", "Hexbin Plot")).strip() or "Hexbin Plot"
    add_line = _bool_from_mode(mode_pairs, "addline", "add_line", default=False)
    header = _bool_from_mode(mode_pairs, "header", default=True)
    bins = int(_float_from_mode(mode_pairs, "bins", default=1000.0, minimum=10.0, maximum=2000.0))
    random_seed = int(
        _float_from_mode(mode_pairs, "randomseed", "random_seed", default=69.0, minimum=0.0)
    )
    width_cm = _float_from_mode(mode_pairs, "widthcm", "width_cm", default=20.0, minimum=5.0, maximum=200.0)
    height_cm = _float_from_mode(mode_pairs, "heightcm", "height_cm", default=15.0, minimum=5.0, maximum=200.0)
    dpi = int(_float_from_mode(mode_pairs, "dpi", default=100.0, minimum=72.0, maximum=2000.0))

    lines: list[str] = []
    lines.append(f"peptide_rt_overview|workflow={workflow_key}|dataset_level=peptide|entity=peptides")
    lines.append(
        f"peptide_rt_parameters|method={_safe_context_text(method)}|add_line={'true' if add_line else 'false'}|header={'true' if header else 'false'}|bins={bins}|random_seed={random_seed}|width_cm={_fmt_value(width_cm)}|height_cm={_fmt_value(height_cm)}|dpi={dpi}"
    )
    lines.append(
        "peptide_rt_general|description=retention_time_agreement_plot_between_predicted_and_observed_retention_times_for_peptide_entries"
    )
    lines.append("peptide_rt_axes|x_axis=predicted_RT|y_axis=actual_RT|point_definition=one_peptide_measurement")
    lines.append(
        "peptide_rt_methods|scatter=points|hexbin=hexagonal_bin_counts|density=2D_histogram_density"
    )
    lines.append(
        "peptide_rt_diagonal_rule|optional_identity_line_if_enabled=predicted_RT_equals_actual_RT_reference"
    )

    try:
        frame = get_peptide_frame()
    except Exception as exc:
        lines.append(f"peptide_rt_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("peptide_rt_plot", "\n".join(lines))

    def _predicted_rt_column(df: pd.DataFrame) -> str | None:
        if "Predicted.RT" in df.columns:
            return "Predicted.RT"
        for column in df.columns:
            normalized = str(column).strip().lower()
            if "predicted" in normalized and "rt" in normalized:
                return str(column)
        return None

    def _actual_rt_column(df: pd.DataFrame) -> str | None:
        if "RT" in df.columns:
            return "RT"
        for column in df.columns:
            normalized = str(column).strip().lower()
            if normalized == "rt":
                return str(column)
        for column in df.columns:
            normalized = str(column).strip().lower()
            if "rt" in normalized and "predicted" not in normalized:
                return str(column)
        return None

    predicted_col = _predicted_rt_column(frame)
    actual_col = _actual_rt_column(frame)
    if predicted_col is None or actual_col is None:
        lines.append(
            "peptide_rt_data|status=error|detail=missing_required_columns_for_rt_plot"
        )
        return _text_payload("peptide_rt_plot", "\n".join(lines))

    data = frame[[predicted_col, actual_col]].apply(pd.to_numeric, errors="coerce").dropna()
    lines.append(
        f"peptide_rt_columns|predicted_column={_safe_context_text(predicted_col)}|actual_column={_safe_context_text(actual_col)}"
    )
    lines.append(
        f"peptide_rt_table|status=available|rows={int(data.shape[0])}|columns={int(data.shape[1])}"
    )
    if data.empty:
        lines.append("peptide_rt_table|status=empty_after_numeric_filter")
        return _text_payload("peptide_rt_plot", "\n".join(lines))

    predicted_vals = data[predicted_col].astype(float)
    actual_vals = data[actual_col].astype(float)
    correlation = float(predicted_vals.corr(actual_vals)) if int(data.shape[0]) >= 2 else float("nan")

    lines.append(
        "peptide_rt_summary|"
        f"points={int(data.shape[0])}|"
        f"predicted_min={_fmt_value(predicted_vals.min())}|predicted_max={_fmt_value(predicted_vals.max())}|predicted_mean={_fmt_value(predicted_vals.mean())}|predicted_median={_fmt_value(predicted_vals.median())}|"
        f"actual_min={_fmt_value(actual_vals.min())}|actual_max={_fmt_value(actual_vals.max())}|actual_mean={_fmt_value(actual_vals.mean())}|actual_median={_fmt_value(actual_vals.median())}|"
        f"pearson_r={_fmt_value(correlation) if pd.notna(correlation) else 'na'}"
    )
    return _text_payload("peptide_rt_plot", "\n".join(lines))


def peptide_modification_plot_context(workflow: str = "peptide", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)

    include_id = _bool_from_mode(mode_pairs, "includeid", "include_id", default=False)
    header = _bool_from_mode(mode_pairs, "header", default=True)
    legend = _bool_from_mode(mode_pairs, "legend", default=True)
    width_cm = _float_from_mode(mode_pairs, "widthcm", "width_cm", default=25.0, minimum=5.0, maximum=200.0)
    height_cm = _float_from_mode(mode_pairs, "heightcm", "height_cm", default=15.0, minimum=5.0, maximum=200.0)
    dpi = int(_float_from_mode(mode_pairs, "dpi", default=100.0, minimum=72.0, maximum=2000.0))

    lines: list[str] = []
    lines.append(f"peptide_modification_overview|workflow={workflow_key}|dataset_level=peptide|entity=peptides")
    lines.append(
        f"peptide_modification_parameters|include_id={'true' if include_id else 'false'}|header={'true' if header else 'false'}|legend={'true' if legend else 'false'}|width_cm={_fmt_value(width_cm)}|height_cm={_fmt_value(height_cm)}|dpi={dpi}"
    )
    lines.append(
        "peptide_modification_general|description=bar_plot_of_modified_peptide_counts_per_sample_for_selected_modification_classes"
    )
    lines.append(
        "peptide_modification_classes|tracked=Carbamidomethylation,Oxidation,Acetylation"
    )
    lines.append(
        "peptide_modification_logic|count_unit=distinct_modified_sequence_per_class_per_sample|"
        "detection_rule=finite_nonzero_quantity|repeated_same_class_within_one_sequence_counts_once"
    )
    lines.append(
        "peptide_modification_identifier_rule|unimod_ids=exact_numeric_identifier_boundary|"
        "text_names=case_insensitive_whole_term|examples=UniMod:4_does_not_match_UniMod:40_or_UniMod:400"
    )
    lines.append(
        "peptide_modification_overlap_rule|a_sequence_with_multiple_tracked_classes_counts_once_in_each_class|"
        "class_assignment_total_can_exceed_unique_tracked_modified_peptides"
    )
    lines.append(
        "peptide_modification_metadata_rule|protein_annotation_metadata_with_sample_and_condition_is_required_for_sample_mapping"
    )

    try:
        frame = get_peptide_frame()
    except Exception as exc:
        lines.append(f"peptide_modification_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("peptide_modification_plot", "\n".join(lines))

    try:
        file_col = _plot_images.peptide_file_column(frame)
    except Exception as exc:
        lines.append(f"peptide_modification_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("peptide_modification_plot", "\n".join(lines))

    sequence_col = "Modified.Sequence" if "Modified.Sequence" in frame.columns else None
    if sequence_col is None:
        for column in frame.columns:
            normalized = str(column).strip().lower()
            if "modified" in normalized and "sequence" in normalized:
                sequence_col = str(column)
                break
    if sequence_col is None:
        lines.append("peptide_modification_data|status=error|detail=missing_modified_sequence_column")
        return _text_payload("peptide_modification_plot", "\n".join(lines))

    quantity_col = (
        "Precursor.Quantity"
        if "Precursor.Quantity" in frame.columns
        else resolve_peptide_quantity_column(frame)
    )

    try:
        meta = _plot_images._peptide_coverage_metadata(frame, include_id=include_id).copy()
    except Exception as exc:
        lines.append(
            f"peptide_modification_data|status=error|detail=metadata_required:{_safe_context_text(exc)}"
        )
        return _text_payload("peptide_modification_plot", "\n".join(lines))

    wide = (
        frame.pivot_table(index=file_col, columns=sequence_col, values=quantity_col, aggfunc="max")
        .T.reset_index()
    )
    try:
        rename_map = _peptide_sample_rename_map(
            wide.columns, meta.rename(columns={"label": "new_sample"}), sequence_col
        )
    except ValueError as exc:
        lines.append("peptide_modification_data|status=error|detail=" + _safe_context_text(exc))
        return _text_payload("peptide_modification_plot", "\n".join(lines))
    wide = wide.rename(columns=rename_map)
    ordered_samples = [str(label) for label in meta["label"].astype(str).tolist()]
    annotated_cols = [column for column in ordered_samples if column in wide.columns]
    if not annotated_cols:
        lines.append(
            "peptide_modification_data|status=error|detail=metadata_sample_mapping_did_not_match_peptide_samples"
        )
        return _text_payload("peptide_modification_plot", "\n".join(lines))

    filtered = wide[[sequence_col, *annotated_cols]].copy()
    summary = _peptide_modification_counts(
        filtered,
        sequence_column=sequence_col,
        sample_columns=annotated_cols,
    ).reset_index()
    summary["ClassAssignmentTotal"] = (
        summary["Carbamidomethylation"].astype(int)
        + summary["Oxidation"].astype(int)
        + summary["Acetylation"].astype(int)
    )

    condition_by_sample = {
        str(label): str(condition)
        for label, condition in zip(meta["label"].astype(str), meta["condition"].astype(str))
    }
    summary["Condition"] = summary["Sample"].map(condition_by_sample).fillna("unknown")

    lines.append(
        f"peptide_modification_columns|file_column={_safe_context_text(file_col)}|sequence_column={_safe_context_text(sequence_col)}|quantity_column={_safe_context_text(quantity_col)}"
    )
    lines.append(
        f"peptide_modification_table|status=available|rows={int(summary.shape[0])}|columns={int(summary.shape[1])}"
    )
    lines.append(
        f"peptide_modification_counts|sample_count={int(summary['Sample'].nunique())}|condition_count={int(summary['Condition'].nunique())}"
    )
    lines.append(
        "peptide_modification_totals|"
        f"carbamidomethylation={int(summary['Carbamidomethylation'].sum())}|"
        f"oxidation={int(summary['Oxidation'].sum())}|acetylation={int(summary['Acetylation'].sum())}|"
        f"class_assignment_total={int(summary['ClassAssignmentTotal'].sum())}|"
        f"unique_tracked_modified_peptides_sample_sum={int(summary['UniqueTrackedModifiedPeptides'].sum())}"
    )

    for _, row in summary.iterrows():
        lines.append(
            "peptide_modification_sample|"
            f"condition={_safe_context_text(row['Condition'])}|sample={_safe_context_text(row['Sample'])}|"
            f"carbamidomethylation={int(row['Carbamidomethylation'])}|oxidation={int(row['Oxidation'])}|"
            f"acetylation={int(row['Acetylation'])}|class_assignment_total={int(row['ClassAssignmentTotal'])}|"
            f"unique_tracked_modified_peptides={int(row['UniqueTrackedModifiedPeptides'])}"
        )

    for condition in _condition_order(summary[["Condition"]].copy()):
        subset = summary[summary["Condition"] == condition].copy()
        if subset.empty:
            continue
        lines.append(
            "peptide_modification_condition|"
            f"name={_safe_context_text(condition)}|sample_count={int(subset.shape[0])}|"
            f"carbamidomethylation_sample_sum={int(subset['Carbamidomethylation'].sum())}|"
            f"oxidation_sample_sum={int(subset['Oxidation'].sum())}|"
            f"acetylation_sample_sum={int(subset['Acetylation'].sum())}|"
            f"class_assignment_sample_sum={int(subset['ClassAssignmentTotal'].sum())}|"
            f"unique_tracked_modified_peptides_sample_sum={int(subset['UniqueTrackedModifiedPeptides'].sum())}"
        )

    return _text_payload("peptide_modification_plot", "\n".join(lines))


def peptide_missed_cleavage_plot_context(workflow: str = "peptide", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)

    include_id = _bool_from_mode(mode_pairs, "includeid", "include_id", default=False)
    show_text = _bool_from_mode(mode_pairs, "text", default=True)
    text_size = int(_float_from_mode(mode_pairs, "textsize", "text_size", default=8.0, minimum=6.0, maximum=100.0))
    header = _bool_from_mode(mode_pairs, "header", default=True)
    width_cm = _float_from_mode(mode_pairs, "widthcm", "width_cm", default=25.0, minimum=5.0, maximum=200.0)
    height_cm = _float_from_mode(mode_pairs, "heightcm", "height_cm", default=15.0, minimum=5.0, maximum=200.0)
    dpi = int(_float_from_mode(mode_pairs, "dpi", default=100.0, minimum=72.0, maximum=2000.0))

    lines: list[str] = []
    lines.append(f"peptide_missed_cleavage_overview|workflow={workflow_key}|dataset_level=peptide|entity=peptides")
    try:
        resolved_protease = _normalize_protease(mode_pairs.get("protease", "trypsin"))
    except ValueError as exc:
        lines.append(
            f"peptide_missed_cleavage_data|status=error|detail={_safe_context_text(exc)}"
        )
        return _text_payload("peptide_missed_cleavage_plot", "\n".join(lines))
    lines.append(
        f"peptide_missed_cleavage_parameters|include_id={'true' if include_id else 'false'}|text={'true' if show_text else 'false'}|text_size={text_size}|header={'true' if header else 'false'}|protease={resolved_protease}|protease_label={_safe_context_text(_PROTEASE_LABELS[resolved_protease])}|width_cm={_fmt_value(width_cm)}|height_cm={_fmt_value(height_cm)}|dpi={dpi}"
    )
    lines.append(
        "peptide_missed_cleavage_general|description=stacked_bar_distribution_of_missed_cleavage_counts_per_sample_reported_as_percentages"
    )
    lines.append(
        "peptide_missed_cleavage_logic|count_definition=internal_cleavable_K_or_R_sites_excluding_the_expected_C_terminal_cut|"
        "trypsin_blocks_KP_and_RP|trypsin_lysc_cleaves_KP_but_still_blocks_RP"
    )
    lines.append(
        "peptide_missed_cleavage_logic|count_unit=distinct_stripped_sequence_per_sample|"
        "sample_assignment=finite_nonzero_raw_quantity"
    )
    lines.append(
        "peptide_missed_cleavage_metadata_rule|protein_annotation_metadata_with_sample_and_condition_is_required_for_sample_mapping"
    )

    try:
        frame = get_peptide_frame()
    except Exception as exc:
        lines.append(f"peptide_missed_cleavage_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("peptide_missed_cleavage_plot", "\n".join(lines))

    try:
        file_col = _plot_images.peptide_file_column(frame)
        seq_col = _plot_images.peptide_sequence_column(frame)
    except Exception as exc:
        lines.append(f"peptide_missed_cleavage_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("peptide_missed_cleavage_plot", "\n".join(lines))

    quantity_col = (
        "Precursor.Quantity"
        if "Precursor.Quantity" in frame.columns
        else resolve_peptide_quantity_column(frame)
    )

    try:
        meta = _plot_images._peptide_coverage_metadata(frame, include_id=include_id).copy()
    except Exception as exc:
        lines.append(
            f"peptide_missed_cleavage_data|status=error|detail=metadata_required:{_safe_context_text(exc)}"
        )
        return _text_payload("peptide_missed_cleavage_plot", "\n".join(lines))

    wide = (
        frame.pivot_table(index=file_col, columns=seq_col, values=quantity_col, aggfunc="max")
        .T.reset_index()
    )
    wide = wide.rename(columns={"index": seq_col})
    try:
        rename_map = _peptide_sample_rename_map(
            wide.columns, meta.rename(columns={"label": "new_sample"}), seq_col
        )
    except ValueError as exc:
        lines.append("peptide_missed_cleavage_data|status=error|detail=" + _safe_context_text(exc))
        return _text_payload("peptide_missed_cleavage_plot", "\n".join(lines))
    wide = wide.rename(columns=rename_map)
    sample_order = [str(label) for label in meta["label"].astype(str).tolist()]
    annotated_cols = [column for column in sample_order if column in wide.columns]
    if not annotated_cols:
        lines.append(
            "peptide_missed_cleavage_data|status=error|detail=metadata_sample_mapping_did_not_match_peptide_samples"
        )
        return _text_payload("peptide_missed_cleavage_plot", "\n".join(lines))

    summary = _peptide_missed_cleavage_summary(
        wide[[seq_col, *annotated_cols]],
        sequence_column=seq_col,
        sample_columns=annotated_cols,
        protease=resolved_protease,
    )
    if summary.empty:
        lines.append("peptide_missed_cleavage_table|status=empty_after_filtering")
        return _text_payload("peptide_missed_cleavage_plot", "\n".join(lines))
    summary["Sample"] = pd.Categorical(summary["Sample"], categories=sample_order, ordered=True)

    condition_by_sample = {
        str(label): str(condition)
        for label, condition in zip(meta["label"].astype(str), meta["condition"].astype(str))
    }

    sample_totals = summary.groupby("Sample", observed=False)["Total"].max()
    counts_sorted = sorted(summary["Count"].astype(int).unique().tolist())
    pivot = (
        summary.pivot_table(
            index="Sample",
            columns="Count",
            values="Percentage",
            aggfunc="first",
        )
        .reindex(sample_order)
        .fillna(0.0)
    )

    lines.append(
        f"peptide_missed_cleavage_columns|file_column={_safe_context_text(file_col)}|sequence_column={_safe_context_text(seq_col)}|quantity_column={_safe_context_text(quantity_col)}"
    )
    lines.append(
        f"peptide_missed_cleavage_table|status=available|rows={int(summary.shape[0])}|columns={int(summary.shape[1])}"
    )
    lines.append(
        f"peptide_missed_cleavage_counts|sample_count={len(sample_order)}|cleavage_count_levels={len(counts_sorted)}"
    )
    lines.append(
        f"peptide_missed_cleavage_levels|values={_safe_context_text(';'.join([str(value) for value in counts_sorted]))}"
    )

    single_percent = (
        summary[summary["Count"] == 1]
        .set_index("Sample")["Percentage"]
        .reindex(sample_order)
        .fillna(0.0)
    )
    for sample in sample_order:
        if sample not in pivot.index:
            continue
        distribution_parts = [
            f"{count}:{_fmt_value(float(pivot.loc[sample, count]))}"
            for count in counts_sorted
        ]
        n_total = int(sample_totals.get(sample, 0))
        lines.append(
            "peptide_missed_cleavage_sample|"
            f"condition={_safe_context_text(condition_by_sample.get(sample, 'unknown'))}|sample={_safe_context_text(sample)}|"
            f"n_detected_peptides={n_total}|single_missed_cleavage_percent={_fmt_value(float(single_percent.get(sample, 0.0)))}|"
            f"distribution_percent={_safe_context_text(';'.join(distribution_parts))}"
        )

    global_occurrences = summary.groupby("Count", observed=False)["Occurrences"].sum()
    global_total = int(global_occurrences.sum())
    global_dist = (global_occurrences / global_total * 100.0).sort_index()
    lines.append(
        f"peptide_missed_cleavage_global|total_detected_entries={global_total}"
    )
    for count, percent in global_dist.items():
        lines.append(
            f"peptide_missed_cleavage_global_bin|count={int(count)}|percentage={_fmt_value(float(percent))}"
        )

    return _text_payload("peptide_missed_cleavage_plot", "\n".join(lines))


def peptide_sequence_coverage_context(workflow: str = "peptide", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)

    species = str(mode_pairs.get("species", "human")).strip().lower()
    if species not in {"human", "mouse"}:
        species = "human"
    protein = str(mode_pairs.get("protein", "")).strip()
    chunk_size = int(_float_from_mode(mode_pairs, "chunksize", "chunk_size", default=100.0, minimum=10.0, maximum=5000.0))
    max_protein_preview = int(
        _float_from_mode(
            mode_pairs,
            "maxproteinpreview",
            "max_protein_preview",
            default=150.0,
            minimum=10.0,
            maximum=2000.0,
        )
    )

    lines: list[str] = []
    lines.append(f"peptide_sequence_coverage_overview|workflow={workflow_key}|dataset_level=peptide|entity=peptides")
    lines.append(
        f"peptide_sequence_coverage_parameters|species={species}|protein={_safe_context_text(protein or 'not_selected')}|chunk_size={chunk_size}"
    )
    lines.append(
        "peptide_sequence_coverage_general|description=textual_sequence_map_of_selected_protein_with_matched_peptides_overlay_and_coverage_percent"
    )
    lines.append(
        "peptide_sequence_coverage_logic|coverage_percent=covered_amino_acid_positions_divided_by_total_protein_length_times_100"
    )
    lines.append(
        "peptide_sequence_coverage_database|supported_species=human_or_mouse_fasta_database_selected_by_ui_parameter"
    )

    try:
        overview = _peptide_overview()
    except Exception as exc:
        lines.append(f"peptide_sequence_coverage_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("peptide_sequence_coverage", "\n".join(lines))

    available_proteins = [str(value) for value in list(overview.get("availableProteins") or []) if str(value).strip()]
    protein_preview, protein_preview_truncated = _preview_items(available_proteins, max_protein_preview)
    lines.append(
        f"peptide_sequence_coverage_dataset|filename={_safe_context_text(overview.get('filename'))}|rows={int(overview.get('rows') or 0)}|available_proteins={len(available_proteins)}|metadata_loaded={'true' if bool(overview.get('metadataLoaded')) else 'false'}"
    )
    lines.append(
        f"peptide_sequence_coverage_available_proteins|count={len(available_proteins)}|preview_count={len(protein_preview)}|preview_truncated={'true' if protein_preview_truncated else 'false'}|values={_safe_context_text(';'.join(protein_preview))}"
    )

    if not protein:
        suggested = available_proteins[0] if available_proteins else ""
        lines.append(
            f"peptide_sequence_coverage_data|status=incomplete_parameters|detail=protein_not_selected|suggested_protein={_safe_context_text(suggested or 'none_available')}"
        )
        return _text_payload("peptide_sequence_coverage", "\n".join(lines))

    try:
        payload = _peptide_sequence_coverage(
            species=species,  # type: ignore[arg-type]
            protein=protein,
            chunk_size=chunk_size,
        )
    except Exception as exc:
        lines.append(f"peptide_sequence_coverage_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("peptide_sequence_coverage", "\n".join(lines))

    coverage_percent = float(payload.get("coveragePercent", 0.0))
    matching_peptide_count = int(payload.get("matchingPeptideCount", 0) or 0)
    assigned_peptide_count = int(payload.get("assignedPeptideCount", matching_peptide_count) or 0)
    unmapped_peptides = [str(value) for value in list(payload.get("unmappedPeptides") or [])]
    sequence_text = str(payload.get("sequenceText", "") or "")
    sequence_lines = [line for line in sequence_text.splitlines() if line.strip()]
    sequence_preview, sequence_preview_truncated = _preview_items(sequence_lines, 12)

    lines.append(
        "peptide_sequence_coverage_result|"
        f"protein={_safe_context_text(str(payload.get('protein') or protein))}|species={_safe_context_text(str(payload.get('species') or species))}|"
        f"coverage_percent={_fmt_value(coverage_percent)}|matching_peptide_count={matching_peptide_count}|"
        f"assigned_peptide_count={assigned_peptide_count}|unmapped_peptide_count={len(unmapped_peptides)}|sequence_text_lines={len(sequence_lines)}"
    )
    if unmapped_peptides:
        lines.append(
            "peptide_sequence_coverage_warning|"
            f"unmapped_peptides={_safe_context_text(';'.join(unmapped_peptides[:10]))}|"
            "note=assigned_to_the_protein_group_but_absent_from_the_selected_sequence_not_counted_in_coverage_check_isoform_or_database_variant"
        )
    lines.append(
        f"peptide_sequence_coverage_sequence_preview|line_count={len(sequence_preview)}|preview_truncated={'true' if sequence_preview_truncated else 'false'}|lines={_safe_context_text(' || '.join(sequence_preview))}"
    )
    return _text_payload("peptide_sequence_coverage", "\n".join(lines))


def completeness_missing_value_plot_context(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    kind = _normalize_completeness_kind(workflow_key, mode)
    entity_singular, entity_plural = _COMPLETENESS_KIND_LABELS.get(kind, _COMPLETENESS_KIND_LABELS["protein"])

    lines: list[str] = []
    lines.append(
        f"missing_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}"
    )
    lines.append(
        "missing_functions|wide_format=missing_value_plot|long_format=missing_value_plot_prec_and_missing_value_plot_pep"
    )
    lines.append(
        "missing_format_logic|protein_and_phosphosite_levels=wide_format|full_report_precursor_and_peptide_levels=long_format"
    )
    lines.append(
        "missing_calculation|step1=count_missing_values_per_feature_row"
    )
    lines.append(
        "missing_calculation|step2=aggregate_feature_counts_by_missing_value_count"
    )
    lines.append(
        "missing_plot_encoding|x_axis=number_of_missing_values_per_feature|y_axis=number_of_features_with_that_missing_value_count"
    )
    lines.append(
        "missing_interpretation_example|zero_missing_values_means_feature_detected_in_all_samples"
    )
    lines.append(
        "missing_interpretation_example|one_missing_value_means_feature_detected_in_total_samples_minus_one"
    )
    lines.append(
        "missing_interpretation_example|high_missing_value_counts_mean_feature_detected_in_few_samples"
    )
    lines.append(
        "missing_usage|supports=quick_overview_of_data_completeness_and_missingness_pattern_detection"
    )

    overall_missing, sample_count, feature_rows, error = _completeness_feature_rows(kind)
    if error is not None:
        lines.append(f"missing_tables|status=unavailable|detail={error}")
    else:
        lines.append(
            f"missing_tables_overall|overall_missing_values_percent={_fmt_value(overall_missing if overall_missing is not None else 0.0)}"
        )
        lines.append(
            "missing_excluded_features|"
            f"no_value_in_any_selected_sample={_excluded_all_missing_count(kind, include_id=True)}|"
            "excluded_from=plot,heatmap,tables"
        )
        lines.append(f"missing_tables_samples|count={sample_count}")
        lines.append(f"missing_tables_feature_distribution|rows={len(feature_rows)}")
        for missing_count, feature_count, percent_value in feature_rows:
            detected_count = max(0, sample_count - int(missing_count))
            percent_text = "unknown" if percent_value is None else _fmt_value(percent_value)
            lines.append(
                "missing_feature_bin|"
                f"missing_values={missing_count}|feature_count={feature_count}|feature_percent={percent_text}|"
                f"detected_samples_per_feature={detected_count}"
            )

    lines.append(
        "missing_quality_guidance|type=checklist_only_not_findings|check=inspect_where_mass_of_distribution_sits_across_missing_value_bins"
    )
    lines.append(
        "missing_quality_guidance|type=checklist_only_not_findings|check=inspect_for_large_tails_at_high_missing_value_counts"
    )
    lines.append(
        "missing_quality_guidance|hard_claim_gate=do_not_state_any_of_the_above_as_observed_dataset_findings_without_explicit_numeric_evidence_and_defined_cutoff_rules"
    )

    return _text_payload("completeness_missing_value_plot", "\n".join(lines))


def completeness_missing_value_heatmap_context(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    kind = _normalize_completeness_kind(workflow_key, mode)
    _, entity_plural = _COMPLETENESS_KIND_LABELS.get(kind, _COMPLETENESS_KIND_LABELS["protein"])

    lines: list[str] = []
    lines.append(
        f"missing_heatmap_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}"
    )
    lines.append(
        "missing_heatmap_relation|similar_to_missing_value_plot=true|difference=preserves_structural_pattern_of_missingness"
    )
    lines.append(
        "missing_heatmap_encoding|missing_and_present_values_are_shown_with_distinct_visual_classes"
    )
    lines.append(
        "missing_heatmap_structure|rows=features|columns=samples|pattern_preservation=enabled"
    )
    lines.append(
        "missing_heatmap_pattern_example|vertical_missing_band=sample_with_many_missing_values"
    )
    lines.append(
        "missing_heatmap_pattern_example|horizontal_missing_band=feature_missing_across_multiple_samples"
    )
    lines.append(
        "missing_heatmap_usage|supports=quick_detection_of_systematic_missingness_and_missing-data_trends"
    )
    overall_missing, sample_count, sample_rows, feature_rows, _, error = _completeness_tables_payload(
        kind,
        outlier_threshold=100.0,
        include_id=True,
    )
    if error is not None:
        lines.append(f"missing_heatmap_data|status=unavailable|detail={_safe_context_text(error)}")
    else:
        lines.append(
            "missing_heatmap_data|"
            f"status=available|overall_missing_values_percent={_fmt_value(overall_missing if overall_missing is not None else 0.0)}|"
            f"sample_count={sample_count}|feature_missingness_bins={len(feature_rows)}"
        )
        ranked_samples = sorted(
            sample_rows,
            key=lambda row: float(pd.to_numeric(row.get("%_missing_values"), errors="coerce"))
            if pd.notna(pd.to_numeric(row.get("%_missing_values"), errors="coerce"))
            else float("-inf"),
            reverse=True,
        )
        for row in ranked_samples[:5]:
            sample = str(row.get("Sample", "")).strip() or "unknown"
            lines.append(
                "missing_heatmap_high_missing_sample|"
                f"sample={_safe_context_text(sample)}|condition={_safe_context_text(_extract_condition_from_sample(sample))}|"
                f"missing_count={_safe_context_text(row.get('Counts'))}|missing_percent={_safe_context_text(row.get('%_missing_values'))}"
            )
        lines.append(
            "missing_heatmap_evidence_rule|sample_summaries_support_column_level_comparisons|specific_row_or_block_patterns_require_the_rendered_heatmap_or_row_level_matrix"
        )
    lines.append(
        "missing_heatmap_scope|aggregated_sample_findings_are_data_specific|visual_row_and_block_patterns_are_not_available_in_context"
    )
    lines.append(
        "missing_heatmap_quality_guidance|type=checklist_only_not_findings|check=inspect_for_column_wise_missingness_patterns"
    )
    lines.append(
        "missing_heatmap_quality_guidance|type=checklist_only_not_findings|check=inspect_for_row_wise_missingness_patterns"
    )
    lines.append(
        "missing_heatmap_quality_guidance|sample_missingness_values_may_be_reported_descriptively|quality_or_outlier_labels_require_a_defined_rule"
    )

    return _text_payload("completeness_missing_value_heatmap", "\n".join(lines))


def completeness_missing_value_tables(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)
    kind = _normalize_completeness_kind(workflow_key, mode)
    _, entity_plural = _COMPLETENESS_KIND_LABELS.get(kind, _COMPLETENESS_KIND_LABELS["protein"])
    outlier_threshold = _float_from_mode(
        mode_pairs,
        "outlierthreshold",
        "outlier_threshold",
        "threshold",
        default=50.0,
        minimum=0.0,
        maximum=100.0,
    )
    include_id = _bool_from_mode(mode_pairs, "includeid", "include_id", default=True)

    lines: list[str] = []
    lines.append(
        f"missing_tables_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}"
    )
    lines.append(
        f"missing_tables_outlier_criterion|samples_exceed_when_missing_percent_is_strictly_greater_than={_fmt_value(outlier_threshold)}|threshold_percent={_fmt_value(outlier_threshold)}"
    )
    lines.append(
        f"missing_tables_parameters|include_id={str(include_id).lower()}"
    )

    overall_missing, sample_count, sample_rows, feature_rows, outliers, error = _completeness_tables_payload(
        kind,
        outlier_threshold=outlier_threshold,
        include_id=include_id,
    )

    if error is not None:
        lines.append(f"missing_tables|status=unavailable|detail={error}")
    else:
        lines.append(
            f"missing_tables_overall|overall_missing_values_percent={_fmt_value(overall_missing if overall_missing is not None else 0.0)}"
        )
        lines.append(
            "missing_tables_excluded_features|"
            f"no_value_in_any_selected_sample={_excluded_all_missing_count(kind, include_id=include_id)}|"
            "excluded_from=plot,heatmap,tables"
        )
        lines.append(f"missing_tables_samples|count={sample_count}|rows={len(sample_rows)}")
        for row in sample_rows:
            sample_name = str(row.get("Sample", "")).strip() or "unknown"
            condition = _extract_condition_from_sample(sample_name)
            missing_count = row.get("Counts")
            missing_percent = row.get("%_missing_values")
            lines.append(
                "missing_sample_row|"
                f"sample={sample_name}|condition={condition}|missing_count={_safe_context_text(missing_count)}|"
                f"missing_percent={_safe_context_text(missing_percent)}"
            )

        lines.append(f"missing_tables_feature_distribution|rows={len(feature_rows)}")
        for row in feature_rows:
            missing_values = row.get("n_MissingProteinValues")
            feature_count = row.get("Counts")
            feature_percent = row.get("%_missing_values")
            lines.append(
                "missing_feature_row|"
                f"missing_values_per_feature={_safe_context_text(missing_values)}|feature_count={_safe_context_text(feature_count)}|"
                f"feature_percent={_safe_context_text(feature_percent)}"
            )

        lines.append(f"missing_outliers|count={len(outliers)}")
        if outliers:
            sample_percent_map: dict[str, Any] = {}
            for row in sample_rows:
                sample_name = str(row.get("Sample", "")).strip()
                if not sample_name:
                    continue
                sample_percent_map[sample_name] = row.get("%_missing_values")
            for sample_name in outliers:
                condition = _extract_condition_from_sample(sample_name)
                missing_percent = sample_percent_map.get(sample_name)
                lines.append(
                    "missing_outlier|"
                    f"sample={sample_name}|condition={condition}|missing_percent={_safe_context_text(missing_percent)}|"
                    f"defined_by_threshold_percent_gt={_fmt_value(outlier_threshold)}"
                )
            lines.append(
                f"missing_outlier_answer_summary|threshold_percent={_fmt_value(outlier_threshold)}|count={len(outliers)}|result=only_the_listed_samples_exceed_the_threshold"
            )
        else:
            lines.append(
                f"missing_outlier_answer_summary|threshold_percent={_fmt_value(outlier_threshold)}|count=0|result=no_samples_exceed_the_threshold"
            )

    lines.append(
        "missing_tables_quality_guidance|hard_claim_gate=do_not_state_unqualified_quality_findings_without_explicit_numeric_evidence_and_defined_cutoff_rules"
    )

    return _text_payload("completeness_missing_value_tables", "\n".join(lines))


def data_distribution_summary(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    from app.services.data_tools import distribution_summary
    if workflow == "peptide":
        raise ValueError("Distribution summary requires protein or phosphorylation data.")
    result = distribution_summary(_workflow_kind(workflow))
    lines = [f"distribution_overview|workflow={workflow}|source_used={result.sourceUsed}|aggregation=all_sample_values_pooled",
             "distribution_answer_summary|" + "|".join(f"{key}={_safe_context_text(value) if value is not None else 'NA'}" for key, value in result.stats.model_dump().items()),
             f"distribution_missingness|rows_with_missing={result.rowsWithMissing}|rows_without_missing={result.rowsWithoutMissing}",
             "distribution_inference_rule|std=population_standard_deviation|summary_is_not_a_normality_test|QQ_shape_not_supplied|raw_or_filtered_source_does_not_establish_scale"]
    lines.extend(f"distribution_warning|message={_safe_context_text(w)}" for w in result.warnings)
    return _text_payload("data_distribution_summary", "\n".join(lines))


def stats_simulation_plot(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    if workflow == "peptide":
        raise ValueError("Simulation does not support peptide-level data.")
    pairs = _mode_fields(mode)
    settings = {name: pairs[name.lower()] for name in SimulationRequest.model_fields
                if name != "kind" and name.lower() in pairs}
    payload = SimulationRequest(kind=_workflow_kind(workflow), **settings)
    result = _stats_tools.run_simulation(payload)
    metric = "raw_p_value" if payload.useUncorrected else "BH_adjusted_p_value"
    lines = [f"simulation_overview|workflow={workflow}|source_used={result.sourceUsed}|test_type={result.testType}|selected_p_metric={metric}|scope=hypothetical_sensitivity_analysis",
             "simulation_parameters|" + "|".join(f"{k}={_safe_context_text(v)}" for k, v in payload.model_dump().items()),
             f"simulation_selected_metric|metric={metric}|hypothetical=true",
             "simulation_answer_summary|" + "|".join(f"{k}={_safe_context_text(v)}" for k, v in result.model_dump(exclude={"rows", "warnings"}).items()),
             "simulation_inference_rule|observed_mean_fold_changes_held_fixed|variance_and_sample_size_assumptions_change_pvalues|not_new_observations_or_validated_power_predictions"]
    for row in result.rows[:5]:
        fields = {"term": row.get(result.labelColumn), **{k: row.get(k) for k in ("log2FC", "pval", "adj_pval", "selected_pval", "significance", "effective_n_condition1", "effective_n_condition2")}}
        fields["selected_pval_meaning"] = metric
        lines.append("simulation_term|" + "|".join(f"{k}={_safe_context_text(v) if v is not None else 'NA'}" for k, v in fields.items()))
    if len(result.rows) > 5:
        lines.append("simulation_data|status=partial|reason=first_five_rows_only")
    lines.extend(f"simulation_warning|message={_safe_context_text(w)}" for w in result.warnings)
    return _text_payload("stats_simulation_plot", "\n".join(lines))


def phospho_ksea_export(workflow: str = "phosphosite", mode: ContextMode | None = None) -> dict[str, Any]:
    if workflow != "phosphosite":
        raise ValueError("Kinase Library export requires phosphosite data.")
    pairs = _mode_fields(mode)
    names = {"condition1": "condition1", "condition2": "condition2", "source": "source",
             "dataSource": "data_source", "condition1Control": "condition1_control", "condition2Control": "condition2_control",
             "pValueThreshold": "p_value_threshold", "log2fcThreshold": "log2fc_threshold", "testType": "test_type", "useUncorrected": "use_uncorrected",
             "organism": "organism"}
    # Reuse the validated differential-analysis contract for shared settings.
    from app.schemas.stats import VolcanoRequest, VolcanoControlRequest
    source = pairs.get("source", "volcano")
    if source not in {"volcano", "volcano_control"}:
        raise ValueError("Unsupported Kinase Library source.")
    request_class = VolcanoControlRequest if source == "volcano_control" else VolcanoRequest
    request = request_class(kind="phospho", **{k: pairs[k.lower()] for k in request_class.model_fields if k != "kind" and k.lower() in pairs})
    settings = {key: getattr(request, key, None) for key in names}
    settings["source"] = source
    settings["organism"] = pairs.get("organism", "human")
    table = _phospho_tools.ksea_table(**{target: settings[key] for key, target in names.items()})
    metric = "raw_p_value" if request.useUncorrected else "BH_adjusted_p_value"
    lines = [f"ksea_overview|workflow=phosphosite|selected_p_metric={metric}|scope=external_tool_input_not_kinase_activity_results",
             "ksea_parameters|" + "|".join(f"{k}={_safe_context_text(settings[k])}" for k in names),
             f"ksea_answer_summary|export_rows={len(table)}|selected_p_metric={metric}|all_testable_sites_not_only_significant=true",
             "ksea_inference_rule|export_contains_site_fold_changes_not_kinase_activity|kinase_scores_substrate_counts_and_external_significance_not_available|uploaded_external_plot_not_parsed_by_this_adapter"]
    lines.append(f"ksea_external_view|browser_reports_plot_present={_safe_context_text(pairs.get('externalplotpresent', 'unknown'))}|external_result_values_not_supplied=true")
    for row in table.head(5).to_dict(orient="records"):
        lines.append("ksea_export_row|" + "|".join(f"{k}={_safe_context_text(row[k])}" for k in ("UPD_seq", "Site", "window_source", "log2FC", "pval", "adj_pval", "significance") if k in row))
    if len(table) > 5:
        lines.append("ksea_data|status=partial|reason=first_five_export_rows_only")
    return _text_payload("phospho_ksea_export", "\n".join(lines))


def analysis_canvas_context(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    pairs = _mode_fields(mode)
    if "tiles" not in pairs:
        raise ValueError("Open the canvas to inspect its current composition.")
    tiles = json.loads(pairs.get("tiles", "[]"))
    if not isinstance(tiles, list) or any(not isinstance(tile, str) for tile in tiles):
        raise ValueError("Canvas tile context is invalid.")
    return _text_payload("analysis_canvas_context", "\n".join([
        f"canvas_overview|workflow={workflow}|source=browser_reported_composition_not_calculated_results",
        f"canvas_answer_summary|tile_count={len(tiles)}|tile_types={_safe_context_text(', '.join(tiles[:20]))}",
        "canvas_inference_rule|overview_is_composition_only|no_combined_statistical_test|consult_separate_tile_evidence_for_values",
    ]))


def stats_anova_plot(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    if workflow_key == "peptide":
        raise ValueError("ANOVA evidence does not support peptide-level data.")
    pairs = _mode_fields(mode)
    settings = {name: pairs[name.lower()] for name in AnovaRequest.model_fields
                if name != "kind" and name.lower() in pairs}
    payload = AnovaRequest(kind=_workflow_kind(workflow_key), **settings)
    result = _stats_tools.run_anova(payload)
    selected_cluster = pairs.get("selectedcluster", "none")
    selected_rows = result.rows
    if selected_cluster != "none":
        if payload.source != "anova_cluster":
            raise ValueError("A selected cluster requires ANOVA cluster mode.")
        selected_rows = [row for row in result.clusterRows if str(row.get("cluster")) == selected_cluster]
        if not selected_rows:
            raise ValueError("The selected ANOVA cluster is unavailable.")
    elif payload.source == "anova_cluster":
        selected_rows = result.clusterRows
    p_metric = "raw_p_value" if payload.useUncorrected else "BH_adjusted_p_value"
    lines = [
        f"anova_overview|workflow={workflow_key}|dataset_level={payload.kind}|source={payload.source}|data_source={payload.dataSource}",
        f"anova_tested|source_used={result.sourceUsed}|label_column={_safe_context_text(result.labelColumn)}",
        "anova_testing|test=one_way_independent_groups_ANOVA|assumption=equal_population_variances|"
        "minimum_observations=two_per_condition|undefined_tests=excluded",
        f"anova_multiple_testing|method={'none' if payload.useUncorrected else 'benjamini_hochberg'}|family=all_finite_ANOVA_tests",
        f"anova_parameters|p_value_threshold={_fmt_value(payload.pValueThreshold)}|use_uncorrected={str(payload.useUncorrected).lower()}|"
        f"selected_p_metric={p_metric}|selected_cluster={_safe_context_text(selected_cluster)}|requested_clusters={payload.nClusters}|post_hoc={payload.postHoc}",
        f"anova_answer_summary|full_analysis_tested={result.totalRows}|full_analysis_significant={result.significantCount}|"
        f"selected_view_rows={len(selected_rows)}|actual_clusters={result.clusterCount if result.clusterCount is not None else 'not_requested'}|"
        f"selected_p_metric={p_metric}",
        "anova_inference_rule|omnibus_significance=at_least_one_condition_mean_differs|"
        "does_not_identify_which_pair_or_direction|cluster_membership_is_descriptive_not_a_separate_significance_test",
        f"anova_posthoc_summary|method={result.postHocMethod or 'none'}|comparisons={len(result.postHocRows)}|"
        f"significant_comparisons={result.postHocSignificantCount}|scope=full_analysis_not_selected_cluster|pairwise_rows_not_included=true",
    ]
    for row in selected_rows[:5]:
        f_statistic = "infinity" if row["f_statistic"] == float("inf") else _fmt_value(row["f_statistic"])
        lines.append("anova_term|"
                     f"term={_safe_context_text(row.get(result.labelColumn, ''))}|"
                     f"f_statistic={f_statistic}|raw_p_value={_fmt_probability(row['pval'])}|"
                     f"selected_p_value={_fmt_probability(row['selected_pval'])}|selected_p_metric={p_metric}|"
                     f"significance={_safe_context_text(row['significance'])}")
    lines.append(f"anova_evidence_limit|reported_rows={min(5, len(selected_rows))}|selected_view_rows={len(selected_rows)}|"
                 "row_order=application_table_order|no_heatmap_pattern_or_pairwise_claims_without_supporting_evidence")
    if len(selected_rows) > 5:
        lines.append("anova_data|status=partial|reason=only_first_five_selected_rows_included")
    for warning in result.warnings:
        lines.append(f"anova_warning|message={_safe_context_text(warning)}")
    return _text_payload("stats_anova_plot", "\n".join(lines))


def stats_volcano_plot(
    workflow: str = "protein",
    mode: ContextMode | None = None,
) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)
    kind = _normalize_stats_kind(workflow_key, mode)
    entity_singular, entity_plural = _entity_labels_from_stats_kind(kind)

    source = str(mode_pairs.get("source", "volcano")).strip().lower()
    if source not in {"volcano", "volcano_control"}:
        source = "volcano"
    data_source = str(mode_pairs.get("datasource", "data")).strip().lower()
    if data_source not in _AI_DATA_SOURCES:
        data_source = "data"
    condition1 = str(mode_pairs.get("condition1", "")).strip()
    condition2 = str(mode_pairs.get("condition2", "")).strip()
    condition1_control = str(mode_pairs.get("condition1control", "")).strip()
    condition2_control = str(mode_pairs.get("condition2control", "")).strip()
    override = _contrast_pair(str(mode_pairs.get("conditions", "")))
    for field in ("conditions", "versus"):
        if str(mode_pairs.get(field, "")).strip() and not _contrast_pair(str(mode_pairs[field])):
            return _text_payload("stats_volcano_plot", f"volcano_data|status=error|detail=Invalid {field}: supply two distinct condition names separated by ' vs '.")
    if override:
        if source == "volcano_control":
            return _text_payload("stats_volcano_plot", "volcano_data|status=error|detail=Reading another control-corrected contrast requires both control conditions; no ordinary contrast was substituted.")
        # A read of another contrast with the open plot's settings (GRK, 2026-10-14): the page
        # itself is not changed; every line below describes the requested pair.
        condition1, condition2 = override
    versus = _contrast_pair(str(mode_pairs.get("versus", "")))
    identifier = str(mode_pairs.get("identifier", "workflow")).strip().lower()
    if identifier not in {"workflow", "genes"}:
        identifier = "workflow"
    test_type = _normalize_stats_test_type(mode_pairs.get("testtype", "unpaired"))
    is_paired_test, _ = resolve_test_type(test_type)
    use_uncorrected = _bool_from_mode(mode_pairs, "useuncorrected", "use_uncorrected", default=False)
    p_value_threshold = _float_from_mode(
        mode_pairs,
        "pvaluethreshold",
        "p_value_threshold",
        "alpha",
        default=0.05,
        minimum=1e-12,
        maximum=1.0,
    )
    log2fc_threshold = _float_from_mode(
        mode_pairs,
        "log2fcthreshold",
        "log2fc_threshold",
        "fc",
        default=1.0,
        minimum=0.0,
    )
    max_ranked_per_group = int(
        _float_from_mode(
            mode_pairs,
            "maxranked",
            "max_ranked",
            "ranklimit",
            default=10.0,
            minimum=2.0,
            maximum=500.0,
        )
    )

    lines: list[str] = []
    lines.append(
        f"volcano_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}|source={source}"
    )
    lines.append(
        "volcano_functions|data_function=volcano_data_f|plot_functions=volcano_plot_and_volcano_plot_h"
    )
    lines.append(
        "volcano_functions|control_variant=volcano_control_uses_same_output_table_structure"
    )
    lines.append(
        "volcano_formula|log2FC="
        + (
            "mean_of_complete_pair_differences_condition1_minus_condition2"
            if is_paired_test
            else "mean_condition1_minus_mean_condition2"
        )
        + ("_minus_(mean_condition1_control_minus_mean_condition2_control)" if source == "volcano_control" else "")
    )
    lines.append(
        "volcano_contrast|" + comparison_contrast(
            condition1 or "condition1", condition2 or "condition2",
            (condition1_control or "condition1_control") if source == "volcano_control" else None,
            (condition2_control or "condition2_control") if source == "volcano_control" else None,
        )
    )
    test_type = cast(StatsTestType, effective_test_type(test_type, with_controls=source == "volcano_control"))
    lines.append(
        f"volcano_testing|selected_test={test_type}|"
        f"selected_test_description={_stats_test_description(test_type, control=source == 'volcano_control')}|"
        f"supported_tests={','.join(_STATS_TEST_TYPES)}"
    )
    if is_paired_test:
        lines.append(
            "volcano_pairing|identity=explicit_pair_id_metadata_column|"
            "requirements=identical_unique_pair_ids_in_both_conditions"
        )
    lines.append(
        "volcano_multiple_testing|method=benjamini_hochberg_fdr_control"
    )
    lines.append(
        "volcano_classification_rule|upregulated=(adj_p_or_selected_p<alpha_and_log2FC>tau)|downregulated=(adj_p_or_selected_p<alpha_and_log2FC<-tau)|not_significant=otherwise"
    )
    lines.append(
        "volcano_axes|x=log2FC|y=negative_log10_of_selected_p_metric"
    )

    lines.append(
        f"volcano_parameters|source={source}|identifier={identifier}|test_type={test_type}|data_source={data_source}|p_value_threshold={_fmt_value(p_value_threshold)}|log2fc_threshold={_fmt_value(log2fc_threshold)}|use_uncorrected={'true' if use_uncorrected else 'false'}"
    )
    lines.append(
        f"volcano_selected_p_metric|for_significance={'pval' if use_uncorrected else 'adj_pval'}|for_y_axis=neg_log10_selected_pval"
    )
    lines.append(
        f"volcano_comparison|condition1={_safe_context_text(condition1)}|condition2={_safe_context_text(condition2)}"
    )
    if override:
        lines.append("volcano_read_override|note=this_read_uses_the_requested_conditions_with_the_open_plot_settings;_the_open_plot_itself_is_unchanged")
    if source == "volcano_control":
        lines.append(
            f"volcano_control_comparison|condition1_control={_safe_context_text(condition1_control)}|condition2_control={_safe_context_text(condition2_control)}"
        )

    missing_required = not condition1 or not condition2 or (source == "volcano_control" and (not condition1_control or not condition2_control))
    if missing_required:
        lines.append("volcano_data|status=incomplete_parameters")
        return _text_payload("stats_volcano_plot", "\n".join(lines))

    lookup = _lookup_queries(str(mode_pairs.get("lookup", "")))
    untested_out: list = []
    try:
        source_used, label_column, df, warnings = _stats_tools._volcano_dataframe(
            kind=kind,  # type: ignore[arg-type]
            condition1=condition1,
            condition2=condition2,
            identifier=identifier,  # type: ignore[arg-type]
            p_value_threshold=float(p_value_threshold),
            log2fc_threshold=float(log2fc_threshold),
            test_type=test_type,
            use_uncorrected=bool(use_uncorrected),
            data_source=data_source,  # type: ignore[arg-type]
            condition1_control=condition1_control if source == "volcano_control" else None,
            condition2_control=condition2_control if source == "volcano_control" else None,
            untested_out=untested_out if lookup else None,
        )
    except Exception as exc:
        lines.append(f"volcano_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("stats_volcano_plot", "\n".join(lines))

    frame = df.copy()
    frame["significance"] = frame["significance"].astype(str)
    frame["log2FC"] = pd.to_numeric(frame["log2FC"], errors="coerce")
    frame["pval"] = pd.to_numeric(frame["pval"], errors="coerce")
    frame["adj_pval"] = pd.to_numeric(frame["adj_pval"], errors="coerce")
    frame["selected_pval"] = pd.to_numeric(frame["selected_pval"], errors="coerce")
    frame["neg_log10_selected_pval"] = pd.to_numeric(frame["neg_log10_selected_pval"], errors="coerce")

    total = int(frame.shape[0])
    up_count = int((frame["significance"] == "Upregulated").sum())
    down_count = int((frame["significance"] == "Downregulated").sum())
    not_significant_count = int((frame["significance"] == "Not significant").sum())
    unavailable_count = int((frame["significance"] == "Unavailable").sum())
    denom = float(max(total, 1))
    lines.append(
        f"volcano_tested|total_{entity_plural}_tested={total}|label_column={label_column}|source_used={source_used}"
    )
    lines.append(
        f"volcano_counts|upregulated={up_count}|downregulated={down_count}|not_significant={not_significant_count}"
        f"|unavailable={unavailable_count}"
    )
    lines.append(
        "volcano_answer_summary|"
        f"comparison={_safe_context_text(condition1)}_minus_{_safe_context_text(condition2)}|"
        f"significance_metric={'raw_p_value' if use_uncorrected else 'adjusted_p_value'}|"
        f"p_value_threshold={_fmt_value(p_value_threshold)}|absolute_log2fc_threshold={_fmt_value(log2fc_threshold)}|"
        f"upregulated={up_count}|downregulated={down_count}|not_significant={not_significant_count}"
    )
    lines.append(
        f"volcano_fractions|upregulated_fraction={up_count/denom:.4f}|downregulated_fraction={down_count/denom:.4f}|not_significant_fraction={not_significant_count/denom:.4f}"
    )
    if warnings:
        lines.append(f"volcano_warnings|count={len(warnings)}|messages={_safe_context_text(' || '.join(warnings))}")

    significant_frame = frame[frame["significance"].isin(["Upregulated", "Downregulated"])].copy()
    has_significant = not significant_frame.empty
    lines.append(f"volcano_significant|count={int(significant_frame.shape[0])}|present={'true' if has_significant else 'false'}")

    if lookup:
        # Named features wherever they rank ("are there sites on RPS6 that go down?", 2026-10-13):
        # the ranked lists show ten per direction, which answers nothing about a named protein.
        # A name is looked for in every identifier column the row carries, not only the label.
        def _matches(table: pd.DataFrame, pattern: "re.Pattern[str]") -> pd.Series:
            columns = [column for column in table.columns
                       if (pd.api.types.is_string_dtype(table[column]) or table[column].dtype == object)
                       and not str(column).startswith(("n_", "mean_")) and column != "reason"]
            mask = pd.Series(False, index=table.index)
            for column in columns:
                mask |= table[column].astype(str).str.contains(pattern, na=False)
            return mask
        untested = untested_out[0] if untested_out and isinstance(untested_out[0], pd.DataFrame) else pd.DataFrame()
        found: set[str] = set()
        shown = 0
        for name in lookup:
            pattern = _lookup_pattern(name)
            hits = frame[_matches(frame, pattern)]
            if not untested.empty:
                # Rows the test could not use (a knocked-out protein is missing in every replicate
                # of one condition): their value counts per condition are the answer (GRK, 2026-10-13).
                untested_hits = untested[_matches(untested, pattern)]
                for _, row in untested_hits.head(6).iterrows():
                    found.add(name)
                    counts = "|".join(f"{column}={int(row[column])}" for column in untested.columns if str(column).startswith("n_") and column != "n_pairs")
                    means = "|".join(f"{column}={_fmt_value(float(row[column]))}" for column in untested.columns
                                     if str(column).startswith("mean_") and pd.notna(row[column]))
                    label = _primary_term_label(row.get(label_column, "")) if label_column in untested.columns else _safe_context_text(str(row.iloc[0]))
                    lines.append(f"volcano_lookup_untested|query={_safe_context_text(name)}|term={label}|{counts}|{means}|"
                                 f"reason={_safe_context_text(row.get('reason', ''))}|note=values_count_per_condition_0_means_not_detected_in_any_replicate")
                if len(untested_hits) > 6:
                    lines.append(f"volcano_lookup_untested_truncated|query={_safe_context_text(name)}|matching_rows={len(untested_hits)}|shown=6")
            if hits.empty:
                continue
            found.add(name)
            limit = min(12, max(0, 40 - shown))
            for _, row in hits.head(limit).iterrows():
                shown += 1
                lines.append(
                    f"volcano_lookup|query={_safe_context_text(name)}|term={_primary_term_label(row.get(label_column, ''))}|"
                    f"significance={_safe_context_text(row.get('significance', ''))}|log2FC={_fmt_value(float(row.get('log2FC', 0.0)))}|"
                    f"adj_p_value={_fmt_probability(float(row['adj_pval'])) if pd.notna(row.get('adj_pval')) else 'unavailable'}|"
                    f"p_value={_fmt_probability(float(row['pval'])) if pd.notna(row.get('pval')) else 'unavailable'}"
                )
            if hits.shape[0] > limit:
                lines.append(f"volcano_lookup_truncated|query={_safe_context_text(name)}|matching_rows={int(hits.shape[0])}|shown={limit}")
        missing = [name for name in lookup if name not in found]
        if missing:
            where = "not_in_the_tested_or_untested_rows_of_this_comparison_(absent_from_the_data_used)" if not untested.empty else "not_in_the_tested_rows_of_this_comparison"
            lines.append(f"volcano_lookup_not_found|queries={_safe_context_text(';'.join(missing))}|note={where}")
    if versus and source == "volcano_control":
        lines.append("volcano_versus|status=unavailable|reason=Control-corrected contrasts require their own control pairs; no ordinary contrast was substituted.")
    elif versus:
        lines.extend(_volcano_contrast_difference(
            frame, label_column, versus, kind=kind, identifier=identifier, p_value_threshold=float(p_value_threshold),
            log2fc_threshold=float(log2fc_threshold), test_type=test_type, use_uncorrected=bool(use_uncorrected),
            data_source=data_source, a_pair=(condition1, condition2), lookup=lookup or None,
            enrich=_bool_from_mode(mode_pairs, "enrich", default=False),
            organism=str(mode_pairs.get("organism", "")).strip().lower()))
    if has_significant:
        up_ranked, up_truncated = _volcano_ranked_rows(
            significant_frame[significant_frame["significance"] == "Upregulated"].copy(),
            label_column=label_column,
            group="up",
            limit=max_ranked_per_group,
            strategy="balanced",
        )
        down_ranked, down_truncated = _volcano_ranked_rows(
            significant_frame[significant_frame["significance"] == "Downregulated"].copy(),
            label_column=label_column,
            group="down",
            limit=max_ranked_per_group,
            strategy="balanced",
        )
        lines.append(
            f"volcano_ranked_terms|type=significant|max_per_group={max_ranked_per_group}|rank_method=balanced_effect_and_significance|up_rows={int(up_ranked.shape[0])}|down_rows={int(down_ranked.shape[0])}|up_truncated={'true' if up_truncated else 'false'}|down_truncated={'true' if down_truncated else 'false'}"
        )
        lines.extend(_volcano_term_lines(up_ranked, label_column, "upregulated"))
        lines.extend(_volcano_term_lines(down_ranked, label_column, "downregulated"))
    else:
        lines.append(
            "volcano_disclaimer|message=no_features_passed_the_significance_and_fold_change_thresholds_the_following_terms_are_ranked_as_most_interesting_but_not_significant"
        )
        up_top, _ = _volcano_ranked_rows(
            frame.copy(),
            label_column=label_column,
            group="up",
            limit=2,
            strategy="fold_change_priority",
        )
        down_top, _ = _volcano_ranked_rows(
            frame.copy(),
            label_column=label_column,
            group="down",
            limit=2,
            strategy="fold_change_priority",
        )
        lines.append(
            f"volcano_ranked_terms|type=not_significant_fallback|rank_method=fold_change_priority_pvalue_tiebreak|up_rows={int(up_top.shape[0])}|down_rows={int(down_top.shape[0])}"
        )
        lines.extend(_volcano_term_lines(up_top, label_column, "upregulated_candidate_not_significant"))
        lines.extend(_volcano_term_lines(down_top, label_column, "downregulated_candidate_not_significant"))

    return _text_payload("stats_volcano_plot", "\n".join(lines))


def _volcano_term_lines(ranked: pd.DataFrame, label_column: str, group: str) -> list[str]:
    """One evidence line per ranked volcano feature, the same for every group."""
    return [
        "volcano_term|"
        f"group={group}|rank={rank}|term={_primary_term_label(row.get(label_column, ''))}|"
        f"log2FC={_fmt_value(float(row.get('log2FC', 0.0)))}|"
        f"selected_p_value={_fmt_probability(float(row['selected_pval']))}|"
        f"minus_log10_selected_p={_fmt_value(float(row['neg_log10_selected_pval']))}|"
        f"rank_score={_fmt_value(float(row.get('rank_score', 0.0)))}"
        for rank, (_, row) in enumerate(ranked.iterrows(), start=1)
    ]


def stats_ora_plot(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)
    kind = _normalize_stats_kind(workflow_key, mode)
    _, entity_plural = _entity_labels_from_stats_kind(kind)

    source = str(mode_pairs.get("source", "volcano")).strip().lower()
    if source not in {"volcano", "volcano_control", "anova"}:
        source = "volcano"
    data_source = str(mode_pairs.get("datasource", "data")).strip().lower()
    if data_source not in _AI_DATA_SOURCES:
        data_source = "data"
    condition1 = str(mode_pairs.get("condition1", "")).strip()
    condition2 = str(mode_pairs.get("condition2", "")).strip()
    condition1_control = str(mode_pairs.get("condition1control", "")).strip()
    condition2_control = str(mode_pairs.get("condition2control", "")).strip()
    test_type = _normalize_stats_test_type(mode_pairs.get("testtype", "unpaired"))
    use_uncorrected = _bool_from_mode(mode_pairs, "useuncorrected", "use_uncorrected", default=False)
    p_value_threshold = _float_from_mode(
        mode_pairs,
        "pvaluethreshold",
        "p_value_threshold",
        "alpha",
        default=0.05,
        minimum=1e-12,
        maximum=1.0,
    )
    log2fc_threshold = _float_from_mode(
        mode_pairs,
        "log2fcthreshold",
        "log2fc_threshold",
        "fc",
        default=1.0,
        minimum=0.0,
    )
    selected_cluster_value = int(
        _float_from_mode(
            mode_pairs,
            "selectedcluster",
            "selected_cluster",
            default=0.0,
            minimum=0.0,
            maximum=100.0,
        )
    )
    selected_cluster = selected_cluster_value if selected_cluster_value > 0 else None
    n_clusters = int(
        _float_from_mode(
            mode_pairs,
            "nclusters",
            "n_clusters",
            default=4.0,
            minimum=1.0,
            maximum=100.0,
        )
    )
    top_n = int(
        _float_from_mode(
            mode_pairs,
            "topn",
            "top_terms",
            "topterms",
            default=10.0,
            minimum=1.0,
            maximum=100.0,
        )
    )
    min_term_size = int(
        _float_from_mode(
            mode_pairs,
            "mintermsize",
            "min_term_size",
            default=20.0,
            minimum=1.0,
        )
    )
    max_term_size = int(
        _float_from_mode(
            mode_pairs,
            "maxtermsize",
            "max_term_size",
            default=300.0,
            minimum=1.0,
        )
    )
    if min_term_size > max_term_size:
        min_term_size, max_term_size = max_term_size, min_term_size
    adj_p_value_cutoff = _float_from_mode(
        mode_pairs,
        "adjpvaluecutoff",
        "adj_p_value_cutoff",
        default=0.05,
        minimum=1e-12,
        maximum=1.0,
    )
    background_mode = str(mode_pairs.get("backgroundmode", "experiment")).strip().lower()
    if background_mode not in {"experiment", "global"}:
        background_mode = "experiment"
    # The organism selects the GO table; an unknown one is refused by the
    # request schema below, never replaced by human.
    organism = str(mode_pairs.get("organism", "human")).strip().lower() or "human"

    max_gene_preview = int(
        _float_from_mode(
            mode_pairs,
            "maxgenepreview",
            "max_gene_preview",
            default=200.0,
            minimum=20.0,
            maximum=1000.0,
        )
    )
    max_intersection_preview = int(
        _float_from_mode(
            mode_pairs,
            "maxintersectionpreview",
            "max_intersection_preview",
            default=40.0,
            minimum=5.0,
            maximum=200.0,
        )
    )

    lines: list[str] = []
    lines.append(
        f"ora_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}|source={source}"
    )
    if source == "anova":
        lines.append(
            "ora_method|test=hypergeometric_over_representation|basis=anova_significance_filter_followed_by_hierarchical_protein_clustering"
        )
        lines.append(
            f"ora_flow|selected_anova_cluster={selected_cluster or 'none'}|cluster_genes_to_enriched_pathways"
        )
    else:
        lines.append(
            "ora_method|test=hypergeometric_over_representation|basis=volcano_differential_analysis_with_user_defined_thresholds"
        )
        lines.append(
            "ora_method|volcano_dependency=upregulated_and_downregulated_gene_clusters_are_derived_from_the_selected_differential_test_and_multiple_testing_settings|"
            f"selected_test={effective_test_type(test_type, with_controls=source == 'volcano_control')}|"
            f"selected_test_description={_stats_test_description(test_type, control=source == 'volcano_control')}"
        )
        lines.append(
            "ora_flow|upregulated_cluster=upregulated_genes_to_enriched_pathways"
        )
        lines.append(
            "ora_flow|downregulated_cluster=downregulated_genes_to_enriched_pathways"
        )
    lines.append(
        f"ora_parameters|source={source}|data_source={data_source}|test_type={test_type}|p_value_threshold={_fmt_value(p_value_threshold)}|log2fc_threshold={_fmt_value(log2fc_threshold)}|use_uncorrected={'true' if use_uncorrected else 'false'}|background_mode={background_mode}|organism={_safe_context_text(organism)}"
    )
    lines.append(
        f"ora_comparison|condition1={_safe_context_text(condition1)}|condition2={_safe_context_text(condition2)}"
    )
    if source == "anova":
        lines.append(
            f"ora_anova_parameters|source_locked=anova_cluster|selected_cluster={selected_cluster or 'none'}|n_clusters={n_clusters}|small_clusters=preserved"
        )
    if source == "volcano_control":
        lines.append(
            f"ora_control_comparison|condition1_control={_safe_context_text(condition1_control)}|condition2_control={_safe_context_text(condition2_control)}"
        )
    lines.append(
        f"ora_term_filters|top_terms={top_n}|min_term_size={min_term_size}|max_term_size={max_term_size}|adj_p_value_cutoff={_fmt_value(adj_p_value_cutoff)}"
    )

    missing_required = (
        selected_cluster is None
        if source == "anova"
        else not condition1
        or not condition2
        or (source == "volcano_control" and (not condition1_control or not condition2_control))
    )
    if missing_required:
        lines.append("ora_data|status=incomplete_parameters")
        return _text_payload("stats_ora_plot", "\n".join(lines))

    try:
        payload = EnrichmentRequest(
            kind=kind,  # type: ignore[arg-type]
            source=source,  # type: ignore[arg-type]
            dataSource=data_source,  # type: ignore[arg-type]
            condition1=condition1,
            condition2=condition2,
            condition1Control=condition1_control if source == "volcano_control" else None,
            condition2Control=condition2_control if source == "volcano_control" else None,
            pValueThreshold=float(p_value_threshold),
            log2fcThreshold=float(log2fc_threshold),
            testType=test_type,  # type: ignore[arg-type]
            useUncorrected=bool(use_uncorrected),
            selectedCluster=selected_cluster,
            nClusters=n_clusters,
            adjPValueCutoff=float(adj_p_value_cutoff),
            topN=int(top_n),
            minTermSize=int(min_term_size),
            maxTermSize=int(max_term_size),
            backgroundMode=background_mode,  # type: ignore[arg-type]
            organism=organism,  # type: ignore[arg-type]
        )
        result = _stats_tools.run_enrichment(payload)
    except Exception as exc:
        lines.append(f"ora_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("stats_ora_plot", "\n".join(lines))

    if source == "anova":
        cluster_genes = [str(value) for value in result.clusterGenes]
        gene_preview, gene_preview_truncated = _preview_items(cluster_genes, max_gene_preview)
        cluster_terms = list(result.clusterTerms)
        lines.append(
            f"ora_data|status=available|source_used={result.sourceUsed}"
        )
        lines.append(
            f"ora_background|mode={result.backgroundMode}|organism={_safe_context_text(result.organism)}|submitted_size={result.backgroundSize}|annotated_size={result.annotatedBackgroundSize}|search_space_terms={result.testedTermCount}|per_query_counts={result.termCounts}|correction_scope=BH per query across overlapping size-eligible terms before cutoff and topN|upstream_correction={_safe_context_text(result.upstreamCorrectionMethod)}|term_correction={_safe_context_text(result.correctionMethod)}|database_sha256={result.databaseSha256}"
        )
        lines.append(
            f"ora_gene_clusters|selected_anova_cluster={result.selectedCluster}|genes={len(cluster_genes)}"
        )
        lines.append(
            f"ora_cluster_genes|cluster={result.selectedCluster}|count={len(cluster_genes)}|preview_count={len(gene_preview)}|preview_truncated={'true' if gene_preview_truncated else 'false'}|genes={_safe_context_text(';'.join(gene_preview))}"
        )
        lines.append(
            f"ora_terms|cluster={result.selectedCluster}|count={len(cluster_terms)}"
        )
        if not cluster_terms:
            lines.append(
                f"ora_terms_status|cluster={result.selectedCluster}|status=no_terms_for_current_filters"
            )
        for index, term in enumerate(cluster_terms, start=1):
            genes_preview, preview_truncated = _preview_items(
                [str(value) for value in term.intersectingGenes],
                max_intersection_preview,
            )
            lines.append(
                "ora_term|"
                f"cluster={result.selectedCluster}|rank={index}|source={_safe_context_text(term.source)}|term_id={_safe_context_text(term.termId)}|"
                f"name={_safe_context_text(term.name)}|term_size={term.termSize}|intersection_size={term.intersectionSize}|"
                f"gene_ratio={_fmt_value(term.geneRatio)}|hit_percent={_fmt_value(term.hitPercent)}|p_value={_fmt_value(term.pValue)}|adj_p_value={_fmt_value(term.adjPValue)}|"
                f"intersection_genes_count={len(term.intersectingGenes)}|intersection_genes_preview={_safe_context_text(';'.join(genes_preview))}|"
                f"intersection_preview_truncated={'true' if preview_truncated else 'false'}"
            )
        if result.warnings:
            lines.append(
                f"ora_warnings|count={len(result.warnings)}|messages={_safe_context_text(' || '.join(result.warnings))}"
            )
        return _text_payload("stats_ora_plot", "\n".join(lines))

    up_genes = [str(value) for value in result.upGenes]
    down_genes = [str(value) for value in result.downGenes]
    up_gene_preview, up_gene_truncated = _preview_items(up_genes, max_gene_preview)
    down_gene_preview, down_gene_truncated = _preview_items(down_genes, max_gene_preview)

    lines.append(
        f"ora_data|status=available|source_used={result.sourceUsed}"
    )
    lines.append(
        f"ora_background|mode={result.backgroundMode}|organism={_safe_context_text(result.organism)}|submitted_size={result.backgroundSize}|annotated_size={result.annotatedBackgroundSize}|search_space_terms={result.testedTermCount}|per_query_counts={result.termCounts}|correction_scope=BH per query across overlapping size-eligible terms before cutoff and topN|upstream_correction={_safe_context_text(result.upstreamCorrectionMethod)}|term_correction={_safe_context_text(result.correctionMethod)}|database_sha256={result.databaseSha256}"
    )
    lines.append(
        f"ora_gene_clusters|upregulated_genes={len(up_genes)}|downregulated_genes={len(down_genes)}"
    )
    lines.append(
        f"ora_cluster_genes|cluster=upregulated|count={len(up_genes)}|preview_count={len(up_gene_preview)}|preview_truncated={'true' if up_gene_truncated else 'false'}|genes={_safe_context_text(';'.join(up_gene_preview))}"
    )
    lines.append(
        f"ora_cluster_genes|cluster=downregulated|count={len(down_genes)}|preview_count={len(down_gene_preview)}|preview_truncated={'true' if down_gene_truncated else 'false'}|genes={_safe_context_text(';'.join(down_gene_preview))}"
    )

    up_terms = list(result.upTerms)
    down_terms = list(result.downTerms)
    lines.append(f"ora_terms|cluster=upregulated|count={len(up_terms)}")
    lines.append(f"ora_terms|cluster=downregulated|count={len(down_terms)}")

    if not up_terms:
        lines.append("ora_terms_status|cluster=upregulated|status=no_terms_for_current_filters")
    if not down_terms:
        lines.append("ora_terms_status|cluster=downregulated|status=no_terms_for_current_filters")

    for index, term in enumerate(up_terms, start=1):
        genes_preview, preview_truncated = _preview_items([str(value) for value in term.intersectingGenes], max_intersection_preview)
        lines.append(
            "ora_term|"
            f"cluster=upregulated|rank={index}|source={_safe_context_text(term.source)}|term_id={_safe_context_text(term.termId)}|"
            f"name={_safe_context_text(term.name)}|term_size={term.termSize}|intersection_size={term.intersectionSize}|"
            f"gene_ratio={_fmt_value(term.geneRatio)}|hit_percent={_fmt_value(term.hitPercent)}|p_value={_fmt_value(term.pValue)}|adj_p_value={_fmt_value(term.adjPValue)}|"
            f"intersection_genes_count={len(term.intersectingGenes)}|intersection_genes_preview={_safe_context_text(';'.join(genes_preview))}|"
            f"intersection_preview_truncated={'true' if preview_truncated else 'false'}"
        )

    for index, term in enumerate(down_terms, start=1):
        genes_preview, preview_truncated = _preview_items([str(value) for value in term.intersectingGenes], max_intersection_preview)
        lines.append(
            "ora_term|"
            f"cluster=downregulated|rank={index}|source={_safe_context_text(term.source)}|term_id={_safe_context_text(term.termId)}|"
            f"name={_safe_context_text(term.name)}|term_size={term.termSize}|intersection_size={term.intersectionSize}|"
            f"gene_ratio={_fmt_value(term.geneRatio)}|hit_percent={_fmt_value(term.hitPercent)}|p_value={_fmt_value(term.pValue)}|adj_p_value={_fmt_value(term.adjPValue)}|"
            f"intersection_genes_count={len(term.intersectingGenes)}|intersection_genes_preview={_safe_context_text(';'.join(genes_preview))}|"
            f"intersection_preview_truncated={'true' if preview_truncated else 'false'}"
        )

    if result.warnings:
        lines.append(
            f"ora_warnings|count={len(result.warnings)}|messages={_safe_context_text(' || '.join(result.warnings))}"
        )


    return _text_payload("stats_ora_plot", "\n".join(lines))


def stats_pathway_heatmap_plot(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)
    kind = _normalize_stats_kind(workflow_key, mode)
    _, entity_plural = _entity_labels_from_stats_kind(kind)

    pathway = str(mode_pairs.get("pathway", "")).strip()
    organism = str(mode_pairs.get("organism", "human")).strip().lower() or "human"
    selected_conditions = _split_mode_list(mode_pairs.get("conditions", ""))
    value_type = str(mode_pairs.get("valuetype", mode_pairs.get("value_type", "z"))).strip().lower()
    if value_type not in {"log2", "z"}:
        value_type = "z"
    data_source = str(mode_pairs.get("datasource", "data")).strip().lower()
    if data_source not in _AI_DATA_SOURCES:
        data_source = "data"
    remove_empty = _bool_from_mode(mode_pairs, "removeempty", "remove_empty", default=True)
    include_id = _bool_from_mode(mode_pairs, "includeid", "include_id", default=False)
    header = _bool_from_mode(mode_pairs, "header", default=True)
    cluster_rows = _bool_from_mode(mode_pairs, "clusterrows", "cluster_rows", default=False)
    cluster_cols = _bool_from_mode(mode_pairs, "clustercols", "cluster_cols", default=False)
    max_gene_preview = int(
        _float_from_mode(
            mode_pairs,
            "maxgenepreview",
            "max_gene_preview",
            default=350.0,
            minimum=20.0,
            maximum=2000.0,
        )
    )
    max_condition_preview = int(
        _float_from_mode(
            mode_pairs,
            "maxconditionpreview",
            "max_condition_preview",
            default=80.0,
            minimum=10.0,
            maximum=500.0,
        )
    )

    lines: list[str] = []
    lines.append(
        f"pathway_heatmap_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}"
    )
    lines.append(
        f"pathway_heatmap_selection|pathway={_safe_context_text(pathway)}|organism={_safe_context_text(organism)}|data_source={data_source}|value_type={'z_score' if value_type == 'z' else 'log2'}|remove_empty={'true' if remove_empty else 'false'}|include_id={'true' if include_id else 'false'}|header={'true' if header else 'false'}|cluster_rows={'true' if cluster_rows else 'false'}|cluster_cols={'true' if cluster_cols else 'false'}"
    )
    if selected_conditions:
        condition_preview, condition_truncated = _preview_items(selected_conditions, max_condition_preview)
        lines.append(
            f"pathway_heatmap_conditions|selection=custom|selected_count={len(selected_conditions)}|preview_count={len(condition_preview)}|preview_truncated={'true' if condition_truncated else 'false'}|conditions={_safe_context_text(';'.join(condition_preview))}"
        )
    else:
        lines.append("pathway_heatmap_conditions|selection=all_available")
    lines.append(
        "pathway_heatmap_value_mode|log2=log2_intensities|z_score=row_wise_standardization_per_gene_across_selected_samples"
    )
    lines.append(
        "pathway_heatmap_gene_aggregation|unit=gene|duplicate_features=per_sample_median_ignoring_missing|all_missing=missing|source_feature_count=reported"
    )

    if not pathway:
        lines.append("pathway_heatmap_data|status=incomplete_parameters|detail=pathway_not_selected")
        return _text_payload("stats_pathway_heatmap_plot", "\n".join(lines))

    try:
        source_used, frame, metadata, warnings = _stats_tools._stats_source(  # type: ignore[attr-defined]
            kind,
            data_source=data_source,
        )
    except Exception as exc:
        lines.append(f"pathway_heatmap_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("stats_pathway_heatmap_plot", "\n".join(lines))

    gene_candidates = ["Gene_group", "GeneNames"] if kind == "phosprot" else ["GeneNames", "Gene_group"]
    gene_column = next((column for column in gene_candidates if column in frame.columns), None)
    if gene_column is None:
        lines.append("pathway_heatmap_data|status=error|detail=gene_label_column_not_available")
        return _text_payload("stats_pathway_heatmap_plot", "\n".join(lines))

    try:
        db = _stats_tools.load_go_db(organism)
        pathway_row = db.loc[db["description"].astype(str).str.lower() == pathway.strip().lower()]
        if pathway_row.empty:
            raise ValueError(f"No pathway found matching '{pathway}'.")
        pathway_genes = [
            gene.strip()
            for gene in str(pathway_row.iloc[0]["genes"]).split(";")
            if str(gene).strip()
        ]
        if not pathway_genes:
            raise ValueError("The selected pathway does not contain any genes.")

        meta_filtered = metadata.copy()
        if selected_conditions:
            selected_set = {value.strip() for value in selected_conditions if value.strip()}
            meta_filtered = meta_filtered[meta_filtered["condition"].astype(str).isin(selected_set)]
        if meta_filtered.empty:
            raise ValueError("No samples match the selected conditions.")

        sample_columns = [
            sample
            for sample in meta_filtered["sample"].astype(str).tolist()
            if sample in frame.columns
        ]
        if not sample_columns:
            raise ValueError("No selected samples are available in the current dataset.")

        heatmap_data, source_feature_counts = _stats_tools._aggregate_pathway_gene_values(
            frame,
            gene_column=gene_column,
            sample_columns=sample_columns,
            pathway_genes=pathway_genes,
        )
        pathway_genes = [str(gene) for gene in heatmap_data.index.tolist()]
        matched_genes_in_dataset = int((source_feature_counts > 0).sum())
        all_missing_rows = int(
            (
                (source_feature_counts > 0)
                & heatmap_data.isna().all(axis=1)
            ).sum()
        )
        if remove_empty:
            heatmap_data = heatmap_data.dropna(how="all")
            shown_source_counts = source_feature_counts.loc[heatmap_data.index]
        else:
            shown_source_counts = source_feature_counts
        shown_genes = [str(gene) for gene in heatmap_data.index.tolist()]

        missing_in_dataset = max(0, len(pathway_genes) - matched_genes_in_dataset)
        removed_due_empty = max(0, all_missing_rows) if remove_empty else 0

        pathway_gene_preview, pathway_gene_preview_truncated = _preview_items(pathway_genes, max_gene_preview)
        shown_gene_preview, shown_gene_preview_truncated = _preview_items(shown_genes, max_gene_preview)
        shown_count_preview = [
            f"{gene}:{int(shown_source_counts.loc[gene])}"
            for gene in shown_gene_preview
        ]

        lines.append(
            f"pathway_heatmap_data|status=available|source_used={source_used}|gene_column={_safe_context_text(gene_column)}|pathway_gene_count={len(pathway_genes)}|shown_gene_count={len(shown_genes)}|matched_gene_count={matched_genes_in_dataset}|missing_in_dataset_count={missing_in_dataset}|removed_due_all_missing_count={removed_due_empty}|sample_count={len(sample_columns)}"
        )
        lines.append(
            f"pathway_heatmap_pathway_genes|count={len(pathway_genes)}|preview_count={len(pathway_gene_preview)}|preview_truncated={'true' if pathway_gene_preview_truncated else 'false'}|genes={_safe_context_text(';'.join(pathway_gene_preview))}"
        )
        lines.append(
            f"pathway_heatmap_shown_genes|count={len(shown_genes)}|preview_count={len(shown_gene_preview)}|preview_truncated={'true' if shown_gene_preview_truncated else 'false'}|genes={_safe_context_text(';'.join(shown_gene_preview))}"
        )
        lines.append(
            f"pathway_heatmap_source_feature_counts|count={len(shown_genes)}|preview_count={len(shown_count_preview)}|preview_truncated={'true' if shown_gene_preview_truncated else 'false'}|gene_counts={_safe_context_text(';'.join(shown_count_preview))}"
        )
    except Exception as exc:
        lines.append(f"pathway_heatmap_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("stats_pathway_heatmap_plot", "\n".join(lines))

    if warnings:
        lines.append(
            f"pathway_heatmap_warnings|count={len(warnings)}|messages={_safe_context_text(' || '.join(warnings))}"
        )
    return _text_payload("stats_pathway_heatmap_plot", "\n".join(lines))


def comparison_pearson_correlation(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)
    kind = _normalize_stats_kind(workflow_key, mode)
    _, entity_plural = _entity_labels_from_stats_kind(kind)
    data_source = str(mode_pairs.get("datasource", "data")).strip().lower()
    if data_source not in {"data", "filtered", "imputed"}:
        data_source = "data"

    mode_raw = str(mode_pairs.get("mode", "Single")).strip().lower()
    if mode_raw in {"condition", "mean"}:
        selected_mode = "Mean"
        api_mode = "Condition"
    else:
        selected_mode = "Single"
        api_mode = "Single"

    sample1 = str(mode_pairs.get("sample1", "")).strip()
    sample2 = str(mode_pairs.get("sample2", "")).strip()
    condition1 = str(mode_pairs.get("condition1", "")).strip()
    condition2 = str(mode_pairs.get("condition2", "")).strip()
    alias1 = str(mode_pairs.get("alias1", "")).strip()
    alias2 = str(mode_pairs.get("alias2", "")).strip()

    if api_mode == "Single":
        left_fallback = sample1
        right_fallback = sample2
    else:
        left_fallback = condition1
        right_fallback = condition2
    left_input = alias1 or left_fallback
    right_input = alias2 or right_fallback

    lines: list[str] = []
    lines.append(
        f"comparison_pearson_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}|data_source={data_source}"
    )
    lines.append(
        "comparison_pearson_scope|purpose=interactive_view_of_linear_relationships_for_reproducibility_outlier_screening_and_sample_or_condition_comparison"
    )
    lines.append(
        "comparison_pearson_functions|single_mode_function=correlation_xy_intensity_single|mean_mode_function=correlation_xy_intensity"
    )
    lines.append(
        "comparison_pearson_workflow|steps=extract_values_remove_missing_compute_pearson_and_p_value_scatter_plot_with_regression_line"
    )
    lines.append(
        "comparison_pearson_rule|alias_priority=true|when_alias_is_provided_use_alias_labels_instead_of_raw_sample_or_condition_names"
    )
    if selected_mode == "Single":
        lines.append(
            "comparison_pearson_mode|selected=Single|comparison_level=sample_vs_sample|point_definition=one_entity_value_in_sample1_compared_with_sample2"
        )
        lines.append(
            f"comparison_pearson_selection|left={_safe_context_text(left_input)}|right={_safe_context_text(right_input)}"
        )
    else:
        lines.append(
            "comparison_pearson_mode|selected=Mean|comparison_level=condition_mean_vs_condition_mean|point_definition=one_entity_mean_across_replicates_in_condition1_compared_with_condition2"
        )
        lines.append(
            "comparison_pearson_mean_definition|per_entity_condition_value=mean_across_all_available_replicates_within_each_condition"
        )
        lines.append(
            f"comparison_pearson_selection|left={_safe_context_text(left_input)}|right={_safe_context_text(right_input)}"
        )

    incomplete = (api_mode == "Single" and (not sample1 or not sample2)) or (
        api_mode == "Condition" and (not condition1 or not condition2)
    )
    if incomplete:
        lines.append("comparison_pearson_data|status=incomplete_parameters")
        return _text_payload("comparison_pearson_correlation", "\n".join(lines))

    try:
        table = _comparison_tools.pearson_correlation_table(
            kind,  # type: ignore[arg-type]
            mode=api_mode,
            sample1=sample1,
            sample2=sample2,
            condition1=condition1,
            condition2=condition2,
            alias1=alias1,
            alias2=alias2,
            data_source=data_source,
        ).copy()
    except Exception as exc:
        lines.append(f"comparison_pearson_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("comparison_pearson_correlation", "\n".join(lines))

    lines.append(
        f"comparison_pearson_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("comparison_pearson_table|status=empty")
        return _text_payload("comparison_pearson_correlation", "\n".join(lines))
    if "Metric" not in table.columns or "Value" not in table.columns:
        lines.append("comparison_pearson_table|status=error|detail=missing_columns:Metric,Value")
        return _text_payload("comparison_pearson_correlation", "\n".join(lines))

    metric_values: dict[str, Any] = {}
    for _, row in table.iterrows():
        metric = str(row.get("Metric", "")).strip()
        if not metric:
            continue
        value = row.get("Value")
        metric_values[metric] = value

    left_label = str(metric_values.get("Left", left_input) or left_input).strip() or "unknown"
    right_label = str(metric_values.get("Right", right_input) or right_input).strip() or "unknown"
    lines.append(
        f"comparison_pearson_labels|left={_safe_context_text(left_label)}|right={_safe_context_text(right_label)}"
    )

    for metric in ["Left", "Right", "Points", "PearsonR"]:
        if metric not in metric_values:
            continue
        value = metric_values.get(metric)
        value_text = _safe_context_text(value)
        if metric == "Points":
            try:
                value_text = str(int(round(float(value))))
            except Exception:
                value_text = _safe_context_text(value)
        elif metric == "PearsonR":
            try:
                value_num = float(value)
                value_text = _fmt_value(value_num)
            except Exception:
                value_text = _safe_context_text(value)
        lines.append(
            f"comparison_pearson_table_metric|metric={metric}|value={value_text}"
        )

    lines.append(
        "comparison_pearson_reference|pearson_r_source=summary_table_metric_PearsonR"
    )

    return _text_payload("comparison_pearson_correlation", "\n".join(lines))


def comparison_venn_diagram(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)
    kind = _normalize_stats_kind(workflow_key, mode)
    _, entity_plural = _entity_labels_from_stats_kind(kind)
    data_source = str(mode_pairs.get("datasource", "data")).strip().lower()
    if data_source not in {"data", "filtered", "imputed"}:
        data_source = "data"

    mode_raw = str(mode_pairs.get("mode", "Single")).strip().lower()
    if mode_raw in {"condition", "mean"}:
        selected_mode = "Mean"
        api_mode = "Condition"
        level_text = "condition"
    else:
        selected_mode = "Single"
        api_mode = "Single"
        level_text = "sample"

    first = str(mode_pairs.get("first", "")).strip()
    second = str(mode_pairs.get("second", "")).strip()
    third = str(mode_pairs.get("third", "")).strip()
    alias1 = str(mode_pairs.get("alias1", "")).strip()
    alias2 = str(mode_pairs.get("alias2", "")).strip()
    alias3 = str(mode_pairs.get("alias3", "")).strip()
    color1 = str(mode_pairs.get("color1", "#1f77b4")).strip() or "#1f77b4"
    color2 = str(mode_pairs.get("color2", "#ff7f0e")).strip() or "#ff7f0e"
    color3 = str(mode_pairs.get("color3", "#2ca02c")).strip() or "#2ca02c"

    label1 = alias1 or first
    label2 = alias2 or second
    label3 = alias3 or third
    has_third = bool(third)
    set_count = 3 if has_third else 2

    lines: list[str] = []
    lines.append(
        f"comparison_venn_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}|set_count={set_count}|data_source={data_source}"
    )
    lines.append(
        "comparison_venn_scope|purpose=visualize_shared_and_unique_entities_across_samples_or_conditions"
    )
    lines.append(
        "comparison_venn_functions|single_mode_function=overlap_plot_single|mean_mode_function=overlap_plot_condition"
    )
    lines.append(
        "comparison_venn_processing|step1=extract_non_missing_entities_preserving_valid_log2_zeroes|step2=convert_to_sets|step3=render_venn2_or_venn3"
    )
    lines.append(
        "comparison_venn_rule|alias_priority=true|when_alias_is_provided_use_alias_labels_instead_of_raw_sample_or_condition_names"
    )
    if selected_mode == "Single":
        lines.append(
            "comparison_venn_mode|selected=Single|comparison_level=sample_vs_sample_or_sample_triplet|presence_rule=entity_is_present_if_non_missing_in_each_selected_sample"
        )
    else:
        lines.append(
            "comparison_venn_mode|selected=Mean|comparison_level=condition_vs_condition_or_condition_triplet|presence_rule=entity_is_present_if_detected_in_at_least_one_replicate_within_each_selected_condition"
        )
    lines.append(
        f"comparison_venn_selection|level={level_text}|first={_safe_context_text(label1)}|second={_safe_context_text(label2)}|third={_safe_context_text(label3 if has_third else 'not_selected')}"
    )
    lines.append(
        f"comparison_venn_colors|first={_safe_context_text(_color_name(color1))}|second={_safe_context_text(_color_name(color2))}|third={_safe_context_text(_color_name(color3) if has_third else 'not_used')}"
    )

    if not first or not second:
        lines.append("comparison_venn_data|status=incomplete_parameters")
        return _text_payload("comparison_venn_diagram", "\n".join(lines))

    try:
        table = _comparison_tools.venn_table(
            kind,  # type: ignore[arg-type]
            mode=api_mode,
            first=first,
            second=second,
            third=third,
            alias1=alias1,
            alias2=alias2,
            alias3=alias3,
            data_source=data_source,
        ).copy()
    except Exception as exc:
        lines.append(f"comparison_venn_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("comparison_venn_diagram", "\n".join(lines))

    lines.append(
        f"comparison_venn_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("comparison_venn_table|status=empty")
        return _text_payload("comparison_venn_diagram", "\n".join(lines))
    if "Region" not in table.columns or "Count" not in table.columns:
        lines.append("comparison_venn_table|status=error|detail=missing_columns:Region,Count")
        return _text_payload("comparison_venn_diagram", "\n".join(lines))

    data = table.copy()
    data["Region"] = data["Region"].astype(str)
    data["Count"] = pd.to_numeric(data["Count"], errors="coerce")
    data = data.dropna(subset=["Count"]).copy()

    if data.empty:
        lines.append("comparison_venn_table|status=empty_after_numeric_filter")
        return _text_payload("comparison_venn_diagram", "\n".join(lines))

    for _, row in data.iterrows():
        region = str(row.get("Region", "")).strip()
        count = int(round(float(row.get("Count", 0))))
        lines.append(
            f"comparison_venn_table_row|region={_safe_context_text(region)}|count={count}"
        )

    total_rows = data[data["Region"].str.startswith("Total ")].copy()
    for _, row in total_rows.iterrows():
        region = str(row.get("Region", "")).strip()
        label = region[6:].strip() if region.startswith("Total ") else region
        count = int(round(float(row.get("Count", 0))))
        lines.append(
            f"comparison_venn_group_size|group={_safe_context_text(label)}|count={count}"
        )

    unique_rows = data[data["Region"].str.endswith(" only")].copy()
    for _, row in unique_rows.iterrows():
        region = str(row.get("Region", "")).strip()
        count = int(round(float(row.get("Count", 0))))
        lines.append(
            f"comparison_venn_unique|region={_safe_context_text(region)}|count={count}"
        )

    overlap_rows = data[
        data["Region"].str.contains(" & ", regex=False)
        & ~data["Region"].str.startswith("Total ")
    ].copy()
    for _, row in overlap_rows.iterrows():
        region = str(row.get("Region", "")).strip()
        count = int(round(float(row.get("Count", 0))))
        lines.append(
            f"comparison_venn_overlap|region={_safe_context_text(region)}|count={count}"
        )

    lines.append(
        "comparison_venn_interpretation_scope|supports=identify_shared_entities_unique_entities_and_coverage_differences_across_selected_sets"
    )

    return _text_payload("comparison_venn_diagram", "\n".join(lines))


def phospho_phosphosite_plot(workflow: str = "phosphosite", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    from app.services.phospho_localization import get_localization_cutoff

    # The session-wide localization cutoff, the one the plot was drawn with.
    cutoff = get_localization_cutoff()

    lines: list[str] = []
    lines.append(
        f"phosphosite_summary_overview|workflow={workflow_key}|dataset_level=phospho|entity=phosphosites"
    )
    lines.append(
        f"phosphosite_summary_cutoff|ptm_localization_probability_min={_fmt_value(cutoff)}"
    )
    lines.append(
        "phosphosite_summary_cutoff_rule|filter=retain_rows_where_PTM_localization_is_greater_than_or_equal_to_cutoff|missing_probability_excluded_when_cutoff_above_zero|shared_by_every_phosphosite_module"
    )
    lines.append(
        "phosphosite_summary_entities|phosphoproteins=distinct_protein_groups_with_at_least_one_site_passing_cutoff|phosphopeptides=unique_modified_peptide_sequences|phosphosites=unique_PTM_collapse_keys"
    )
    lines.append(
        "phosphosite_summary_visual|plot=horizontal_bar_chart|ordering=descending_by_count|labels=exact_count_shown_at_bar_end"
    )
    lines.append(
        "phosphosite_summary_general|expected_hierarchy=phosphopeptides_and_phosphosites_often_exceed_phosphoproteins_due_to_modification_hierarchy"
    )
    lines.append(
        "phosphosite_summary_general|cutoff_interpretation=sharp_count_drop_with_higher_cutoff_can_indicate_many_low_confidence_localizations_while_stable_counts_can_indicate_robust_localization"
    )

    try:
        table = _phospho_tools.phosphosite_plot_table().copy()
    except Exception as exc:
        lines.append(f"phosphosite_summary_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("phospho_phosphosite_plot", "\n".join(lines))

    lines.append(
        f"phosphosite_summary_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("phosphosite_summary_table|status=empty")
        return _text_payload("phospho_phosphosite_plot", "\n".join(lines))
    if "Term" not in table.columns or "Count" not in table.columns:
        lines.append("phosphosite_summary_table|status=error|detail=missing_columns:Term,Count")
        return _text_payload("phospho_phosphosite_plot", "\n".join(lines))

    data = table.copy()
    data["Term"] = data["Term"].astype(str)
    data["Count"] = pd.to_numeric(data["Count"], errors="coerce")
    data = data.dropna(subset=["Count"]).copy()

    if data.empty:
        lines.append("phosphosite_summary_table|status=empty_after_numeric_filter")
        return _text_payload("phospho_phosphosite_plot", "\n".join(lines))

    phosphosites_count: int | None = None
    phosphopeptides_count: int | None = None
    phosphoproteins_count: int | None = None

    for _, row in data.iterrows():
        term = str(row.get("Term", "")).strip()
        count = int(round(float(row.get("Count", 0))))
        lines.append(
            f"phosphosite_summary_table_row|term={_safe_context_text(term)}|count={count}"
        )
        term_norm = term.lower().replace(" ", "")
        if "phosphosite" in term_norm:
            phosphosites_count = count
        elif "phosphopeptide" in term_norm:
            phosphopeptides_count = count
        elif "phosphoprotein" in term_norm:
            phosphoproteins_count = count

    lines.append(
        f"phosphosite_summary_under_cutoff|cutoff={_fmt_value(cutoff)}|phosphosites={phosphosites_count if phosphosites_count is not None else 'unknown'}|phosphopeptides={phosphopeptides_count if phosphopeptides_count is not None else 'unknown'}|phosphoproteins={phosphoproteins_count if phosphoproteins_count is not None else 'unknown'}"
    )

    return _text_payload("phospho_phosphosite_plot", "\n".join(lines))


def phospho_phosphosite_coverage_plot(workflow: str = "phosphosite", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)
    mode_raw = str(mode_pairs.get("mode", "Normal")).strip().lower()
    plot_mode = "Summary" if mode_raw == "summary" else "Normal"
    include_id = _bool_from_mode(mode_pairs, "includeid", "include_id", default=False)
    selected_conditions = _split_mode_list(mode_pairs.get("conditions", ""))

    lines: list[str] = []
    lines.append(
        f"phospho_coverage_overview|workflow={workflow_key}|dataset_level=phospho|entity=phosphosites|mode={plot_mode}"
    )
    lines.append(
        "phospho_coverage_functions|per_sample_view=phossite_coverage_plot|summary_view=phossite_coverage_plot_summary"
    )
    lines.append(
        "phospho_coverage_class_rule|class_i=PTM_localization_greater_than_or_equal_to_0.75|not_class_i=PTM_localization_less_than_0.75"
    )
    lines.append(
        "phospho_coverage_calculation|per_sample_detected_sites=total_sites_minus_missing_values|computed_separately_for_class_i_and_not_class_i"
    )
    lines.append(
        "phospho_coverage_visual_encoding|color_mapping=class_i_vs_not_class_i|not_colored_by_condition"
    )
    lines.append(
        "phospho_coverage_normal_view|bars=stacked_per_sample|stack_order=class_i_bottom_then_not_class_i_top"
    )
    lines.append(
        "phospho_coverage_summary_view|bars=condition_level_mean_for_class_i_and_not_class_i|points=replicate_values|error_bars=standard_deviation"
    )
    lines.append(
        f"phospho_coverage_parameters|include_id={'true' if include_id else 'false'}|conditions={_safe_context_text(','.join(selected_conditions)) if selected_conditions else 'all_available'}"
    )

    conditions_arg = selected_conditions if selected_conditions else None
    try:
        table = _phospho_tools.phospho_coverage_table(
            include_id=include_id,
            conditions=conditions_arg,
            mode=plot_mode,
        ).copy()
    except Exception as exc:
        lines.append(f"phospho_coverage_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("phospho_phosphosite_coverage_plot", "\n".join(lines))

    lines.append(
        f"phospho_coverage_table|status=available|mode={plot_mode}|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("phospho_coverage_table|status=empty")
        return _text_payload("phospho_phosphosite_coverage_plot", "\n".join(lines))

    if plot_mode == "Normal":
        required_columns = ["Sample", "Class I", "Not Class I", "Condition", "Total"]
        missing_columns = [column for column in required_columns if column not in table.columns]
        if missing_columns:
            lines.append(
                f"phospho_coverage_table|status=error|detail=missing_columns:{_safe_context_text(','.join(missing_columns))}"
            )
            return _text_payload("phospho_phosphosite_coverage_plot", "\n".join(lines))

        data = table.copy()
        data["Sample"] = data["Sample"].astype(str)
        data["Condition"] = data["Condition"].astype(str)
        data["Class I"] = pd.to_numeric(data["Class I"], errors="coerce")
        data["Not Class I"] = pd.to_numeric(data["Not Class I"], errors="coerce")
        data["Total"] = pd.to_numeric(data["Total"], errors="coerce")
        data = data.dropna(subset=["Class I", "Not Class I", "Total"])
        if data.empty:
            lines.append("phospho_coverage_table|status=empty_after_numeric_filter")
            return _text_payload("phospho_phosphosite_coverage_plot", "\n".join(lines))

        sample_count = int(data["Sample"].nunique())
        condition_order = _condition_order(data[["Condition"]].copy())
        lines.append(
            f"phospho_coverage_counts|sample_count={sample_count}|condition_count={len(condition_order)}"
        )
        for _, row in data.iterrows():
            lines.append(
                "phospho_coverage_sample|"
                f"condition={_safe_context_text(row['Condition'])}|sample={_safe_context_text(row['Sample'])}|"
                f"class_i={_fmt_value(float(row['Class I']))}|not_class_i={_fmt_value(float(row['Not Class I']))}|total={_fmt_value(float(row['Total']))}"
            )

        for condition in condition_order:
            subset = data[data["Condition"] == condition].copy()
            if subset.empty:
                continue
            sample_names = subset["Sample"].astype(str).tolist()
            class_vals = subset["Class I"].astype(float)
            not_vals = subset["Not Class I"].astype(float)
            total_vals = subset["Total"].astype(float)
            lines.append(
                "phospho_coverage_condition|"
                f"name={_safe_context_text(condition)}|sample_count={len(sample_names)}|samples={_safe_context_text(','.join(sample_names))}|"
                f"class_i_mean={_fmt_value(class_vals.mean())}|class_i_median={_fmt_value(class_vals.median())}|class_i_min={_fmt_value(class_vals.min())}|class_i_max={_fmt_value(class_vals.max())}|"
                f"not_class_i_mean={_fmt_value(not_vals.mean())}|not_class_i_median={_fmt_value(not_vals.median())}|not_class_i_min={_fmt_value(not_vals.min())}|not_class_i_max={_fmt_value(not_vals.max())}|"
                f"total_mean={_fmt_value(total_vals.mean())}|total_median={_fmt_value(total_vals.median())}|total_min={_fmt_value(total_vals.min())}|total_max={_fmt_value(total_vals.max())}"
            )
    else:
        required_columns = ["Condition", "classIMean", "classISd", "notClassIMean", "notClassISd"]
        missing_columns = [column for column in required_columns if column not in table.columns]
        if missing_columns:
            lines.append(
                f"phospho_coverage_table|status=error|detail=missing_columns:{_safe_context_text(','.join(missing_columns))}"
            )
            return _text_payload("phospho_phosphosite_coverage_plot", "\n".join(lines))

        data = table.copy()
        data["Condition"] = data["Condition"].astype(str)
        data["classIMean"] = pd.to_numeric(data["classIMean"], errors="coerce")
        data["classISd"] = pd.to_numeric(data["classISd"], errors="coerce")
        data["notClassIMean"] = pd.to_numeric(data["notClassIMean"], errors="coerce")
        data["notClassISd"] = pd.to_numeric(data["notClassISd"], errors="coerce")
        data = data.dropna(subset=["classIMean", "classISd", "notClassIMean", "notClassISd"])
        if data.empty:
            lines.append("phospho_coverage_table|status=empty_after_numeric_filter")
            return _text_payload("phospho_phosphosite_coverage_plot", "\n".join(lines))

        lines.append(
            f"phospho_coverage_summary_counts|condition_count={int(data['Condition'].nunique())}"
        )
        for _, row in data.iterrows():
            lines.append(
                "phospho_coverage_condition_summary|"
                f"condition={_safe_context_text(row['Condition'])}|"
                f"class_i_mean={_fmt_value(float(row['classIMean']))}|class_i_sd={_fmt_value(float(row['classISd']))}|"
                f"not_class_i_mean={_fmt_value(float(row['notClassIMean']))}|not_class_i_sd={_fmt_value(float(row['notClassISd']))}"
            )

        try:
            replicate_table = _phospho_tools.phospho_coverage_table(
                include_id=include_id,
                conditions=conditions_arg,
                mode="Normal",
            ).copy()
        except Exception:
            replicate_table = pd.DataFrame()
        if not replicate_table.empty and all(
            column in replicate_table.columns for column in ["Condition", "Sample", "Class I", "Not Class I", "Total"]
        ):
            rep = replicate_table.copy()
            rep["Condition"] = rep["Condition"].astype(str)
            rep["Sample"] = rep["Sample"].astype(str)
            rep["Class I"] = pd.to_numeric(rep["Class I"], errors="coerce")
            rep["Not Class I"] = pd.to_numeric(rep["Not Class I"], errors="coerce")
            rep["Total"] = pd.to_numeric(rep["Total"], errors="coerce")
            rep = rep.dropna(subset=["Class I", "Not Class I", "Total"])
            for condition in _condition_order(rep[["Condition"]].copy()):
                subset = rep[rep["Condition"] == condition].copy()
                if subset.empty:
                    continue
                sample_values = ";".join(
                    [
                        f"{_safe_context_text(row['Sample'])}:class_i={_fmt_value(float(row['Class I']))},not_class_i={_fmt_value(float(row['Not Class I']))},total={_fmt_value(float(row['Total']))}"
                        for _, row in subset.iterrows()
                    ]
                )
                lines.append(
                    "phospho_coverage_summary_points|"
                    f"condition={_safe_context_text(condition)}|n_replicates={int(subset.shape[0])}|values={sample_values}"
                )

    return _text_payload("phospho_phosphosite_coverage_plot", "\n".join(lines))


def phospho_phosphosite_distribution_plot(workflow: str = "phosphosite", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)
    cutoff = _float_from_mode(
        mode_pairs,
        "cutoff",
        default=0.0,
        minimum=0.0,
        maximum=1.0,
    )

    lines: list[str] = []
    lines.append(
        f"phospho_distribution_overview|workflow={workflow_key}|dataset_level=phospho|entity=phosphoproteins_and_phosphosites"
    )
    lines.append(
        "phospho_distribution_scope|purpose=show_how_many_phosphosites_are_detected_per_phosphoprotein"
    )
    lines.append(
        "phospho_distribution_function|plot_function=phossite_dist"
    )
    lines.append(
        "phospho_distribution_required_columns|primary=Phosphoprotein_and_site_num|fallback=Protein_group_or_Phosphoprotein_with_PTM_Collapse_key"
    )
    lines.append(
        "phospho_distribution_computation|x_axis=number_of_phosphosites_per_phosphoprotein|y_axis=frequency_number_of_phosphoproteins_with_that_site_count"
    )
    lines.append(
        f"phospho_distribution_cutoff|value={_fmt_value(cutoff)}|type=upper_quantile_filter_on_site_count_distribution"
    )
    if cutoff > 0:
        lines.append(
            "phospho_distribution_cutoff_effect|rule=remove_phosphoproteins_with_site_counts_above_quantile_threshold_q_equal_1_minus_cutoff"
        )
    else:
        lines.append(
            "phospho_distribution_cutoff_effect|rule=no_quantile_filter_applied_full_distribution_retained"
        )

    try:
        table = _phospho_tools.phospho_distribution_table(cutoff=float(cutoff)).copy()
    except Exception as exc:
        lines.append(f"phospho_distribution_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("phospho_phosphosite_distribution_plot", "\n".join(lines))

    lines.append(
        f"phospho_distribution_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("phospho_distribution_table|status=empty")
        return _text_payload("phospho_phosphosite_distribution_plot", "\n".join(lines))
    if "SiteCount" not in table.columns or "Frequency" not in table.columns:
        lines.append("phospho_distribution_table|status=error|detail=missing_columns:SiteCount,Frequency")
        return _text_payload("phospho_phosphosite_distribution_plot", "\n".join(lines))

    data = table.copy()
    data["SiteCount"] = pd.to_numeric(data["SiteCount"], errors="coerce")
    data["Frequency"] = pd.to_numeric(data["Frequency"], errors="coerce")
    data = data.dropna(subset=["SiteCount", "Frequency"]).copy()
    if data.empty:
        lines.append("phospho_distribution_table|status=empty_after_numeric_filter")
        return _text_payload("phospho_phosphosite_distribution_plot", "\n".join(lines))

    data["SiteCount"] = data["SiteCount"].astype(int)
    data["Frequency"] = data["Frequency"].astype(int)
    data = data.sort_values("SiteCount").reset_index(drop=True)

    total_phosphoproteins = int(data["Frequency"].sum())
    min_site_count = int(data["SiteCount"].min())
    max_site_count = int(data["SiteCount"].max())
    lines.append(
        f"phospho_distribution_summary|total_phosphoproteins_represented={total_phosphoproteins}|min_site_count={min_site_count}|max_site_count={max_site_count}"
    )

    for _, row in data.iterrows():
        lines.append(
            "phospho_distribution_bin|"
            f"site_count={int(row['SiteCount'])}|frequency={int(row['Frequency'])}"
        )

    lines.append(
        "phospho_distribution_general_pattern|often_right_skewed_with_many_proteins_having_few_sites_and_fewer_proteins_having_many_sites"
    )
    lines.append(
        "phospho_distribution_general_pattern|broad_or_multimodal_patterns_can_reflect_complex_signaling_or_dataset_specific_characteristics"
    )
    return _text_payload("phospho_phosphosite_distribution_plot", "\n".join(lines))


def phospho_sty_plot(workflow: str = "phosphosite", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)

    lines: list[str] = []
    lines.append(
        f"phospho_sty_overview|workflow={workflow_key}|dataset_level=phospho|entity=phosphosites"
    )
    lines.append(
        "phospho_sty_scope|purpose=report_number_and_percentage_of_phosphosites_on_serine_S_threonine_T_and_tyrosine_Y"
    )
    lines.append(
        "phospho_sty_visual|plot=bar_chart_with_residue_categories_S_T_Y|y_axis=count|labels=percentage_annotations"
    )
    lines.append(
        "phospho_sty_table_definition|columns=Residue_Count_Percentage"
    )

    try:
        table = _phospho_tools.phospho_sty_table().copy()
    except Exception as exc:
        lines.append(f"phospho_sty_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("phospho_sty_plot", "\n".join(lines))

    lines.append(
        f"phospho_sty_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("phospho_sty_table|status=empty")
        return _text_payload("phospho_sty_plot", "\n".join(lines))
    if not all(column in table.columns for column in ["Residue", "Count", "Percentage"]):
        lines.append("phospho_sty_table|status=error|detail=missing_columns:Residue,Count,Percentage")
        return _text_payload("phospho_sty_plot", "\n".join(lines))

    data = table.copy()
    data["Residue"] = data["Residue"].astype(str)
    data["Count"] = pd.to_numeric(data["Count"], errors="coerce")
    data["Percentage"] = pd.to_numeric(data["Percentage"], errors="coerce")
    data = data.dropna(subset=["Count", "Percentage"]).copy()
    if data.empty:
        lines.append("phospho_sty_table|status=empty_after_numeric_filter")
        return _text_payload("phospho_sty_plot", "\n".join(lines))

    data["Count"] = data["Count"].astype(int)
    total_count = int(data["Count"].sum())
    lines.append(f"phospho_sty_total|total_phosphosite_count={total_count}")

    for residue in ["S", "T", "Y"]:
        subset = data[data["Residue"].str.upper() == residue]
        if subset.empty:
            lines.append(f"phospho_sty_row|residue={residue}|count=0|percentage=0")
            continue
        row = subset.iloc[0]
        lines.append(
            "phospho_sty_row|"
            f"residue={residue}|count={int(row['Count'])}|percentage={_fmt_value(float(row['Percentage']))}"
        )

    for _, row in data.iterrows():
        lines.append(
            "phospho_sty_table_row|"
            f"residue={_safe_context_text(row['Residue'])}|count={int(row['Count'])}|percentage={_fmt_value(float(row['Percentage']))}"
        )

    return _text_payload("phospho_sty_plot", "\n".join(lines))


def phospho_phosprot_regulation_plot(workflow: str = "phosphoprotein", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)

    condition1 = str(mode_pairs.get("condition1", "")).strip()
    condition2 = str(mode_pairs.get("condition2", "")).strip()
    p_value_threshold = _float_from_mode(
        mode_pairs,
        "pvaluethreshold",
        "p_value_threshold",
        default=0.05,
        minimum=1e-12,
        maximum=1.0,
    )
    log2fc_threshold = _float_from_mode(
        mode_pairs,
        "log2fcthreshold",
        "log2fc_threshold",
        default=1.0,
        minimum=0.0,
    )
    test_type = _normalize_stats_test_type(mode_pairs.get("testtype", "unpaired"))
    use_uncorrected = _bool_from_mode(mode_pairs, "useuncorrected", "use_uncorrected", default=False)
    max_hover_sites = int(
        _float_from_mode(
            mode_pairs,
            "maxhoversites",
            "max_hover_sites",
            default=20.0,
            minimum=1.0,
        )
    )
    show_phosphosites = _bool_from_mode(mode_pairs, "showphosphosites", "show_phosphosites", default=True)
    data_source = str(mode_pairs.get("datasource", "data")).strip().lower()
    if data_source not in {"data", "filtered", "imputed"}:
        data_source = "data"

    lines: list[str] = []
    lines.append(
        f"phosprot_regulation_overview|workflow={workflow_key}|dataset_level=phospho|entity=phosphoproteins|data_source={data_source}"
    )
    lines.append(
        "phosprot_regulation_scope|purpose=descriptive_protein_level_view_of_cumulative_significant_phosphosite_log2_fold_change_contributions"
    )
    lines.append(
        "phosprot_regulation_function|plot_function=phosprot_regulation"
    )
    lines.append(
        f"phosprot_regulation_parameters|condition1={_safe_context_text(condition1)}|condition2={_safe_context_text(condition2)}|p_value_threshold={_fmt_value(p_value_threshold)}|log2fc_threshold={_fmt_value(log2fc_threshold)}|test_type={test_type}|use_uncorrected={'true' if use_uncorrected else 'false'}|max_hover_sites={max_hover_sites}|show_phosphosites={'true' if show_phosphosites else 'false'}|data_source={data_source}"
    )
    lines.append(
        f"phosprot_regulation_testing|selected_test={test_type}|"
        f"selected_test_description={_stats_test_description(test_type)}"
    )
    lines.append(
        "phosprot_regulation_core_steps|step1=compute_phosphosite_log2_fold_changes_between_selected_conditions|step2=classify_sites_that_pass_the_selected_p_value_and_absolute_log2fc_thresholds|step3=sum_positive_significant_site_log2fc_for_x_and_absolute_negative_significant_site_log2fc_for_y"
    )
    lines.append(
        "phosprot_regulation_coordinate_definition|x_axis=cumulative_significant_up_site_log2fc|y_axis=cumulative_significant_down_site_absolute_log2fc|point=one_protein|score_type=descriptive_not_a_protein_level_fold_change"
    )
    lines.append(
        "phosprot_regulation_hover_definition|hover_can_include_significant_up_and_down_site_counts_identifiers_and_individual_log2fc_values_with_optional_truncation"
    )
    lines.append(
        "phosprot_regulation_table_definition|columns=Protein_group_Upregulated_sites_Downregulated_sites_Upregulated_site_effects_Downregulated_site_effects_Upregulated_count_Downregulated_count_Upregulated_log2FC_sum_Downregulated_log2FC_sum_x_y_color_val"
    )
    lines.append(
        "phosprot_regulation_parameter_note|only_sites_passing_both_the_selected_p_value_and_absolute_log2fc_thresholds_contribute|proteins_without_significant_sites_are_omitted"
    )
    lines.append(
        "phosprot_regulation_interpretation_scope|supports_descriptive_comparison_of_cumulative_significant_up_and_down_site_effects|does_not_estimate_a_protein_level_fold_change_or_adjust_for_parent_protein_abundance"
    )

    return _text_payload("phospho_phosprot_regulation_plot", "\n".join(lines))


def single_protein_boxplot(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)
    kind = _normalize_stats_kind(workflow_key, mode)
    entity_singular, entity_plural = _entity_labels_from_stats_kind(kind)
    data_source = str(mode_pairs.get("datasource", "data")).strip().lower()
    if data_source not in {"data", "filtered", "imputed"}:
        data_source = "data"
    identifier = str(mode_pairs.get("identifier", "workflow")).strip().lower()
    if identifier not in {"workflow", "genes"}:
        identifier = "workflow"
    selected_protein = str(mode_pairs.get("protein", "")).strip()
    selected_conditions = _split_mode_list(mode_pairs.get("conditions", ""))
    outliers = _bool_from_mode(mode_pairs, "outliers", default=False)
    dots = _bool_from_mode(mode_pairs, "dots", default=False)
    random_seed = int(
        _float_from_mode(mode_pairs, "randomseed", "random_seed", default=69.0, minimum=0.0)
    )
    header = _bool_from_mode(mode_pairs, "header", default=True)
    legend = _bool_from_mode(mode_pairs, "legend", default=True)

    lines: list[str] = []
    lines.append(
        f"single_protein_boxplot_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}|identifier={identifier}|data_source={data_source}"
    )
    lines.append(
        f"single_protein_boxplot_selection|selected_input={_safe_context_text(selected_protein)}|conditions={_safe_context_text(','.join(selected_conditions)) if selected_conditions else 'all_available'}|outliers={'true' if outliers else 'false'}|dots={'true' if dots else 'false'}|random_seed={random_seed}|header={'true' if header else 'false'}|legend={'true' if legend else 'false'}"
    )
    lines.append(
        "single_protein_boxplot_general|description=distribution_of_log2_transformed_intensity_values_for_one_selected_entity_across_conditions"
    )
    lines.append(
        "single_protein_boxplot_general|per_condition_processing=for_selected_entity_extract_all_intensity_values_from_replicates_in_each_condition"
    )
    if identifier == "genes":
        lines.append(
            "single_protein_boxplot_gene_aggregation|biological_unit=sample|duplicate_mapped_features=per_sample_median_ignoring_missing|sample_count_and_source_feature_count=reported_separately"
        )
    lines.append(
        "single_protein_boxplot_general|interpretation_scope=compare_conditions_detect_shifts_outliers_and_distribution_shape_symmetry_spread_skewness"
    )
    lines.append(
        "single_protein_boxplot_definition|median=50th_percentile|IQR=Q3-Q1|whiskers=outermost_observed_values_within_the_1.5_IQR_fences|fences=Q1-1.5xIQR_to_Q3+1.5xIQR|outliers=observations_outside_the_fences"
    )
    lines.append(
        f"single_protein_boxplot_labels|entity_terms={entity_singular}/{entity_plural}"
    )

    if not selected_protein:
        lines.append("single_protein_boxplot_data|status=incomplete_parameters|detail=protein_not_selected")
        return _text_payload("single_protein_boxplot", "\n".join(lines))

    try:
        table = _single_protein_tools.single_protein_boxplot_table(
            kind,  # type: ignore[arg-type]
            selected_protein,
            selected_conditions,
            identifier=identifier,
            data_source=data_source,
        ).copy()
    except Exception as exc:
        lines.append(f"single_protein_boxplot_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("single_protein_boxplot", "\n".join(lines))

    lines.append(
        f"single_protein_boxplot_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )

    if table.empty:
        lines.append("single_protein_boxplot_table|status=empty")
        return _text_payload("single_protein_boxplot", "\n".join(lines))

    data = table.copy()
    ordered_columns: list[str] = [
        column
        for column in [
            "Condition",
            "N",
            "SampleCount",
            "SourceFeatureCount",
            "SourceFeatures",
            "Aggregation",
            "Warning",
            "Mean",
            "Median",
            "Q1",
            "Q3",
            "Min",
            "Max",
        ]
        if column in data.columns
    ]
    for column in data.columns:
        if column not in ordered_columns:
            ordered_columns.append(str(column))

    lines.append(
        f"single_protein_boxplot_table_columns|values={_safe_context_text(','.join(ordered_columns))}"
    )

    numeric_hints = {
        "N",
        "SampleCount",
        "SourceFeatureCount",
        "Mean",
        "Median",
        "Q1",
        "Q3",
        "Min",
        "Max",
    }
    for rank, (_, row) in enumerate(data.iterrows(), start=1):
        row_parts = [f"rank={rank}"]
        for column in ordered_columns:
            raw_value = row.get(column)
            key = _safe_context_text(column).replace(" ", "_")
            if raw_value is None or (isinstance(raw_value, float) and pd.isna(raw_value)):
                row_parts.append(f"{key}=na")
                continue
            if column in numeric_hints:
                try:
                    value_num = float(raw_value)
                    if column in {"N", "SampleCount", "SourceFeatureCount"}:
                        row_parts.append(f"{key}={int(round(value_num))}")
                    else:
                        row_parts.append(f"{key}={_fmt_value(value_num)}")
                    continue
                except Exception:
                    pass
            row_parts.append(f"{key}={_safe_context_text(raw_value)}")
        lines.append("single_protein_boxplot_table_row|" + "|".join(row_parts))

    return _text_payload("single_protein_boxplot", "\n".join(lines))


def single_protein_lineplot(workflow: str = "protein", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)
    kind = _normalize_stats_kind(workflow_key, mode)
    entity_singular, entity_plural = _entity_labels_from_stats_kind(kind)
    data_source = str(mode_pairs.get("datasource", "data")).strip().lower()
    if data_source not in {"data", "filtered", "imputed"}:
        data_source = "data"
    identifier = str(mode_pairs.get("identifier", "workflow")).strip().lower()
    if identifier not in {"workflow", "genes"}:
        identifier = "workflow"
    selected_proteins = _split_mode_list(mode_pairs.get("proteins", ""))
    selected_conditions = _split_mode_list(mode_pairs.get("conditions", ""))
    include_id = _bool_from_mode(mode_pairs, "includeid", "include_id", default=False)
    show_na_low = _bool_from_mode(mode_pairs, "shownalow", "show_na_low", default=False)
    header = _bool_from_mode(mode_pairs, "header", default=True)
    legend = _bool_from_mode(mode_pairs, "legend", default=True)
    max_item_preview = int(
        _float_from_mode(
            mode_pairs,
            "maxitempreview",
            "max_item_preview",
            default=200.0,
            minimum=20.0,
            maximum=2000.0,
        )
    )

    lines: list[str] = []
    lines.append(
        f"single_protein_lineplot_overview|workflow={workflow_key}|dataset_level={kind}|entity={entity_plural}|identifier={identifier}|data_source={data_source}"
    )
    lines.append(
        f"single_protein_lineplot_selection|proteins={_safe_context_text(','.join(selected_proteins)) if selected_proteins else 'none_selected'}|conditions={_safe_context_text(','.join(selected_conditions)) if selected_conditions else 'all_available'}|include_id={'true' if include_id else 'false'}|header={'true' if header else 'false'}|legend={'true' if legend else 'false'}"
    )
    lines.append(
        "single_protein_lineplot_context_policy|data_volume_control=per_entity_min_max_mean_median_plus_per_sample_values_when_at_most_40_points"
    )
    lines.append(
        "single_protein_lineplot_general|description=each_selected_entity_is_plotted_as_an_independent_trajectory_across_ordered_samples_and_conditions"
    )
    if identifier == "genes":
        lines.append(
            "single_protein_lineplot_gene_aggregation|biological_unit=sample|duplicate_mapped_features=per_sample_median_ignoring_missing|sample_count_and_source_feature_count=reported_separately"
        )
    lines.append(
        "single_protein_lineplot_axes|x_axis=samples|y_axis=log2_intensity|conditions_define_sample_grouping_and_ordering"
    )
    lines.append(
        "single_protein_lineplot_general|sample_ordering=samples_follow_user_selected_condition_sequence_for_consistent_experimental_alignment"
    )
    lines.append(
        "single_protein_lineplot_general|missing_values=" + (
            "NA_positions_have_display_only_log2_0_vertices_without_markers_not_measurements_or_imputation"
            if show_na_low else "NA_markers_are_omitted_while_lines_remain_connected_across_missing_positions")
    )
    lines.append(
        "single_protein_lineplot_general|interpretation_scope=evaluate_condition_or_temporal_trends_replicate_variation_and_sample_level_shifts"
    )
    lines.append(
        f"single_protein_lineplot_labels|entity_terms={entity_singular}/{entity_plural}"
    )

    if not selected_proteins:
        lines.append("single_protein_lineplot_data|status=incomplete_parameters|detail=proteins_not_selected")
        return _text_payload("single_protein_lineplot", "\n".join(lines))

    try:
        table = _single_protein_tools.single_protein_lineplot_table(
            kind,  # type: ignore[arg-type]
            selected_proteins,
            selected_conditions,
            include_id=include_id,
            identifier=identifier,
            data_source=data_source,
        ).copy()
    except Exception as exc:
        lines.append(f"single_protein_lineplot_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("single_protein_lineplot", "\n".join(lines))

    lines.append(
        f"single_protein_lineplot_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("single_protein_lineplot_table|status=empty")
        return _text_payload("single_protein_lineplot", "\n".join(lines))

    data = table.copy()
    required_columns = ["Feature", "Sample", "Condition", "Value"]
    missing_columns = [column for column in required_columns if column not in data.columns]
    if missing_columns:
        lines.append(
            f"single_protein_lineplot_table|status=error|detail=missing_columns:{_safe_context_text(','.join(missing_columns))}"
        )
        return _text_payload("single_protein_lineplot", "\n".join(lines))

    data["Feature"] = data["Feature"].astype(str)
    data["Sample"] = data["Sample"].astype(str)
    data["Condition"] = data["Condition"].astype(str)
    data["Value"] = pd.to_numeric(data["Value"], errors="coerce")
    data = data.dropna(subset=["Value"]).copy()

    if data.empty:
        lines.append("single_protein_lineplot_table|status=empty_after_numeric_filter")
        return _text_payload("single_protein_lineplot", "\n".join(lines))

    lines.append(
        "single_protein_lineplot_table_representation|mode=aggregated_entity_statistics_only|source=single_protein_lineplot_table"
    )

    entity_count = int(data["Feature"].nunique())
    condition_count = int(data["Condition"].nunique())
    lines.append(
        f"single_protein_lineplot_counts|entity_count={entity_count}|condition_count={condition_count}"
    )

    feature_values = data["Feature"].drop_duplicates().tolist()
    feature_preview, feature_truncated = _preview_items(feature_values, max_item_preview)
    selected_preview, selected_truncated = _preview_items(selected_proteins, max_item_preview)
    lines.append(
        f"single_protein_lineplot_selected_entities|requested_count={len(selected_proteins)}|requested_preview_count={len(selected_preview)}|requested_preview_truncated={'true' if selected_truncated else 'false'}|requested_values={_safe_context_text(';'.join(selected_preview))}"
    )
    lines.append(
        f"single_protein_lineplot_entities|count={entity_count}|preview_count={len(feature_preview)}|preview_truncated={'true' if feature_truncated else 'false'}|values={_safe_context_text(';'.join(feature_preview))}"
    )
    # Names that match no row are left out of the plot; the page says so under
    # it, and so does this. A JSON list, because a name may hold ";" or ",".
    try:
        not_found = _single_protein_tools.unmatched_lineplot_names(
            kind,  # type: ignore[arg-type]
            selected_proteins,
            identifier=identifier,
            data_source=data_source,
        )
    except ValueError:
        not_found = []
    if not_found:
        not_found_preview, not_found_truncated = _preview_items(not_found, max_item_preview)
        lines.append(
            f"single_protein_lineplot_not_found|count={len(not_found)}|preview_truncated={'true' if not_found_truncated else 'false'}|values={_safe_context_text(json.dumps(not_found_preview, ensure_ascii=False))}|not_plotted=true"
        )
    lines.append(
        "single_protein_lineplot_focus|answer_entity_questions_using_the_per_entity_and_per_condition_statistics_and_listed_sample_values_and_plot_structure_explanation"
    )

    observed_conditions = data["Condition"].drop_duplicates().tolist()
    condition_preview, condition_truncated = _preview_items(observed_conditions, max_item_preview)
    lines.append(
        f"single_protein_lineplot_conditions|count={condition_count}|preview_count={len(condition_preview)}|preview_truncated={'true' if condition_truncated else 'false'}|values={_safe_context_text(';'.join(condition_preview))}"
    )

    for feature in feature_values:
        feature_data = data[data["Feature"] == feature].copy()
        if feature_data.empty:
            continue
        values_all = feature_data["Value"].astype(float)
        count_fields = ""
        if "SampleCount" in feature_data.columns:
            count_fields += f"|sample_count={int(pd.to_numeric(feature_data['SampleCount'], errors='coerce').max())}"
        if "SourceFeatureCount" in feature_data.columns:
            count_fields += f"|source_feature_count={int(pd.to_numeric(feature_data['SourceFeatureCount'], errors='coerce').max())}"
        if "SourceFeatures" in feature_data.columns:
            count_fields += f"|source_features={_safe_context_text(feature_data['SourceFeatures'].iloc[0])}"
        lines.append(
            "single_protein_lineplot_entity_summary|"
            f"entity={_safe_context_text(feature)}|n_values={int(values_all.shape[0])}|"
            f"mean={_fmt_value(values_all.mean())}|median={_fmt_value(values_all.median())}|"
            f"min={_fmt_value(values_all.min())}|max={_fmt_value(values_all.max())}{count_fields}"
        )
        if int(data.shape[0]) <= 40:
            # A few proteins across a few samples is what the plot shows point by point, and
            # "how does CCN1 look across my samples?" asks for exactly those values (2026-10-13).
            for condition, group in feature_data.groupby("Condition", sort=False):
                values = group["Value"].astype(float)
                points = ";".join(f"{sample}={_fmt_value(value)}" for sample, value in zip(group["Sample"], values))
                lines.append(
                    "single_protein_lineplot_entity_condition|"
                    f"entity={_safe_context_text(feature)}|condition={_safe_context_text(str(condition))}|n_values={int(values.shape[0])}|"
                    f"mean={_fmt_value(values.mean())}|median={_fmt_value(values.median())}|"
                    f"min={_fmt_value(values.min())}|max={_fmt_value(values.max())}|samples={_safe_context_text(points)}"
                )
    lines.append(
        f"single_protein_lineplot_final_entities|values={_safe_context_text(';'.join(feature_values))}"
    )

    return _text_payload("single_protein_lineplot", "\n".join(lines))


def single_protein_phosphosite_heatmap(workflow: str = "phosphosite", mode: ContextMode | None = None) -> dict[str, Any]:
    workflow_key = _normalize_coverage_workflow(workflow)
    mode_pairs = _mode_fields(mode)
    data_source = str(mode_pairs.get("datasource", "data")).strip().lower()
    if data_source not in {"data", "filtered", "imputed"}:
        data_source = "data"
    identifier = str(mode_pairs.get("identifier", "workflow")).strip().lower()
    if identifier not in {"workflow", "genes"}:
        identifier = "workflow"
    selected_protein = str(mode_pairs.get("protein", "")).strip()
    selected_conditions = _split_mode_list(mode_pairs.get("conditions", ""))
    include_id = _bool_from_mode(mode_pairs, "includeid", "include_id", default=False)
    header = _bool_from_mode(mode_pairs, "header", default=True)
    filter_m1 = _bool_from_mode(mode_pairs, "filterm1", "filter_m1", default=True)
    cluster_rows = _bool_from_mode(mode_pairs, "clusterrows", "cluster_rows", default=False)
    cluster_cols = _bool_from_mode(mode_pairs, "clustercols", "cluster_cols", default=False)
    value_type = str(mode_pairs.get("valuetype", mode_pairs.get("value_type", "log2"))).strip().lower()
    if value_type not in {"log2", "z"}:
        value_type = "log2"
    max_site_preview = int(
        _float_from_mode(
            mode_pairs,
            "maxsitepreview",
            "max_site_preview",
            default=500.0,
            minimum=20.0,
            maximum=5000.0,
        )
    )

    lines: list[str] = []
    lines.append(
        f"single_protein_heatmap_overview|workflow={workflow_key}|dataset_level=phospho|entity=phosphosites|identifier={identifier}|data_source={data_source}"
    )
    lines.append(
        f"single_protein_heatmap_selection|protein={_safe_context_text(selected_protein)}|conditions={_safe_context_text(','.join(selected_conditions)) if selected_conditions else 'all_available'}|include_id={'true' if include_id else 'false'}|header={'true' if header else 'false'}|filter_m1={'true' if filter_m1 else 'false'}|cluster_rows={'true' if cluster_rows else 'false'}|cluster_cols={'true' if cluster_cols else 'false'}|value_type={value_type}"
    )
    lines.append(
        "single_protein_heatmap_visual|x_axis=samples|y_axis=phosphosites_for_selected_protein|cells=transformed_intensity_values"
    )
    lines.append(
        "single_protein_heatmap_general|description=heatmap_shows_selected_protein_with_site_rows_listed_in_context_across_samples"
    )

    if not selected_protein:
        lines.append("single_protein_heatmap_data|status=incomplete_parameters|detail=protein_not_selected")
        return _text_payload("single_protein_phosphosite_heatmap", "\n".join(lines))

    try:
        table = _single_protein_tools.single_protein_heatmap_table(
            "phospho",  # type: ignore[arg-type]
            selected_protein,
            selected_conditions,
            identifier=identifier,
            include_id=include_id,
            filter_m1=filter_m1,
            cluster_rows=cluster_rows,
            cluster_cols=cluster_cols,
            value_type=value_type,
            data_source=data_source,
        ).copy()
    except Exception as exc:
        lines.append(f"single_protein_heatmap_data|status=error|detail={_safe_context_text(exc)}")
        return _text_payload("single_protein_phosphosite_heatmap", "\n".join(lines))

    lines.append(
        f"single_protein_heatmap_table|status=available|rows={int(table.shape[0])}|columns={int(table.shape[1])}"
    )
    if table.empty:
        lines.append("single_protein_heatmap_table|status=empty")
        return _text_payload("single_protein_phosphosite_heatmap", "\n".join(lines))

    site_column = "Site" if "Site" in table.columns else str(table.columns[0])
    sample_columns = [str(column) for column in table.columns if str(column) != site_column]
    sites = table[site_column].astype(str).dropna().drop_duplicates().tolist()
    site_preview, site_truncated = _preview_items(sites, max_site_preview)

    lines.append(
        f"single_protein_heatmap_structure|selected_protein={_safe_context_text(selected_protein)}|site_column={_safe_context_text(site_column)}|site_count={len(sites)}|sample_count={len(sample_columns)}"
    )
    lines.append(
        f"single_protein_heatmap_sites|count={len(sites)}|preview_count={len(site_preview)}|preview_truncated={'true' if site_truncated else 'false'}|values={_safe_context_text(';'.join(site_preview))}"
    )
    if len(sites) == 1:
        lines.append(
            f"single_protein_heatmap_single_site|site={_safe_context_text(sites[0])}"
        )
    else:
        lines.append(
            f"single_protein_heatmap_exact_sites|values={_safe_context_text(';'.join(sites))}"
        )
    lines.append(
        f"single_protein_heatmap_samples|count={len(sample_columns)}|values={_safe_context_text(';'.join(sample_columns))}"
    )

    return _text_payload("single_protein_phosphosite_heatmap", "\n".join(lines))


__all__ = [
    "data_distribution_summary", "stats_simulation_plot", "phospho_ksea_export", "analysis_canvas_context",
    "stats_anova_plot",
    "general_proteomics_context",
    "completeness_missing_value_plot_context",
    "completeness_missing_value_heatmap_context",
    "completeness_missing_value_tables",
    "stats_volcano_plot",
    "stats_ora_plot",
    "stats_pathway_heatmap_plot",
    "comparison_pearson_correlation",
    "comparison_venn_diagram",
    "phospho_phosphosite_plot",
    "phospho_phosphosite_coverage_plot",
    "phospho_phosphosite_distribution_plot",
    "phospho_sty_plot",
    "phospho_phosprot_regulation_plot",
    "single_protein_boxplot",
    "single_protein_lineplot",
    "single_protein_phosphosite_heatmap",
    "peptide_rt_plot_context",
    "peptide_modification_plot_context",
    "peptide_missed_cleavage_plot_context",
    "peptide_sequence_coverage_context",
    "qc_coverage_plot_context",
    "qc_histogram_intensity",
    "qc_boxplot_intensity",
    "qc_cov_plot",
    "qc_pca_plot_context",
    "qc_abundance_plot_context",
    "qc_correlation_plot_context",
]

# The assistant's tool names are the renderers' names: that is what the frontend
# asks for and what the narrative matches on (`item.tool`). The functions that
# build a tool's context are named `*_context`, so a renderer and its context
# builder no longer share a name across modules; this map joins the two.
CONTEXT_TOOL_FUNCTIONS: dict[str, str] = {
    "qc_coverage_plot": "qc_coverage_plot_context",
    "qc_pca_plot": "qc_pca_plot_context",
    "qc_abundance_plot": "qc_abundance_plot_context",
    "qc_correlation_plot": "qc_correlation_plot_context",
    "peptide_rt_plot": "peptide_rt_plot_context",
    "peptide_modification_plot": "peptide_modification_plot_context",
    "peptide_missed_cleavage_plot": "peptide_missed_cleavage_plot_context",
    "peptide_sequence_coverage": "peptide_sequence_coverage_context",
    "completeness_missing_value_plot": "completeness_missing_value_plot_context",
    "completeness_missing_value_heatmap": "completeness_missing_value_heatmap_context",
}
