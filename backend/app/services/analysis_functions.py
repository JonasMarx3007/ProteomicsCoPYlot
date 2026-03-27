from __future__ import annotations

import re

import pandas as pd

from app.schemas.analysis import (
    AnalysisVolcanoPoint,
    AnalysisVolcanoRequest,
    AnalysisVolcanoResponse,
)
from app.schemas.annotation import AnnotationKind
from app.schemas.stats import VolcanoControlRequest, VolcanoRequest
from app.services.runtime_cache import apply_cached_wrappers
from app.services.single_protein_tools import (
    single_protein_boxplot_plot,
    single_protein_boxplot_table,
    single_protein_lineplot_plot,
    single_protein_lineplot_table,
)
from app.services.stats_tools import run_volcano, run_volcano_control


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _workflow_label(row: dict[str, object]) -> str | None:
    for key in ("ProteinNames", "PTM_Collapse_key", "Phosphoprotein", "Protein_group"):
        value = _string_or_none(row.get(key))
        if value:
            return value
    return None


def _gene_label(row: dict[str, object]) -> str | None:
    for key in ("GeneNames", "Gene_group"):
        value = _string_or_none(row.get(key))
        if value:
            return value
    return None


def _gene_tokens(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [token.strip() for token in text.split(";") if token.strip()]


def _selection_label(
    *,
    kind: AnnotationKind,
    identifier: str,
    label_value: str,
) -> str:
    text = str(label_value).strip()
    if not text:
        return text

    if identifier == "genes":
        tokens = _gene_tokens(text)
        return tokens[0] if tokens else text

    if kind == "protein":
        head = text.split(";")[0].strip()
        return head or text

    return text


_UNIPROT_PATTERN = re.compile(
    r"\b(?:[OPQ][0-9][A-Z0-9]{3}[0-9](?:-\d+)?|[A-NR-Z][0-9](?:[A-Z][A-Z0-9]{2}[0-9]){1,2}(?:-\d+)?)\b"
)


def _extract_uniprot(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for token in re.split(r"[;,\s|]+", text):
        token = token.strip()
        if not token:
            continue
        match = _UNIPROT_PATTERN.search(token)
        if match:
            return match.group(0)
    fallback = _UNIPROT_PATTERN.search(text)
    if fallback:
        return fallback.group(0)
    return None


def _uniprot_accession(row: dict[str, object], label: str) -> str | None:
    for key in (
        "UniProt",
        "Uniprot",
        "UniProtKB",
        "UniProtID",
        "UniProtIDs",
        "Protein IDs",
        "ProteinIDs",
        "ProteinId",
        "Protein_id",
        "Majority protein IDs",
        "Protein_group",
        "ProteinNames",
    ):
        if key in row:
            accession = _extract_uniprot(row.get(key))
            if accession:
                return accession
    return _extract_uniprot(label)


def analysis_volcano_data(payload: AnalysisVolcanoRequest) -> AnalysisVolcanoResponse:
    if payload.source == "volcano_control":
        if not payload.condition1Control or not payload.condition2Control:
            raise ValueError("Volcano control source requires both control conditions.")
        result = run_volcano_control(
            VolcanoControlRequest(
                kind=payload.kind,
                condition1=payload.condition1,
                condition2=payload.condition2,
                condition1Control=payload.condition1Control,
                condition2Control=payload.condition2Control,
                identifier=payload.identifier,
                pValueThreshold=payload.pValueThreshold,
                log2fcThreshold=payload.log2fcThreshold,
                testType=payload.testType,
                useUncorrected=payload.useUncorrected,
                highlightTerms=[],
            )
        )
    else:
        result = run_volcano(
            VolcanoRequest(
                kind=payload.kind,
                condition1=payload.condition1,
                condition2=payload.condition2,
                identifier=payload.identifier,
                pValueThreshold=payload.pValueThreshold,
                log2fcThreshold=payload.log2fcThreshold,
                testType=payload.testType,
                useUncorrected=payload.useUncorrected,
                highlightTerms=[],
            )
        )

    points: list[AnalysisVolcanoPoint] = []
    for raw_row in result.rows:
        row = dict(raw_row)
        label = _string_or_none(row.get(result.labelColumn))
        if not label:
            continue
        try:
            log2fc = float(row.get("log2FC", 0.0))
            neg_log = float(row.get("neg_log10_adj_pval", 0.0))
        except Exception:
            continue
        points.append(
            AnalysisVolcanoPoint(
                label=label,
                selectionLabel=_selection_label(
                    kind=payload.kind,
                    identifier=payload.identifier,
                    label_value=label,
                ),
                uniprotAccession=_uniprot_accession(row, label),
                workflowLabel=_workflow_label(row),
                geneLabel=_gene_label(row),
                significance=str(row.get("significance") or "Not significant"),
                log2FC=log2fc,
                negLog10P=neg_log,
            )
        )

    return AnalysisVolcanoResponse(
        kind=result.kind,
        source=payload.source,
        labelColumn=result.labelColumn,
        totalRows=result.totalRows,
        upregulatedCount=result.upregulatedCount,
        downregulatedCount=result.downregulatedCount,
        notSignificantCount=result.notSignificantCount,
        points=points,
        warnings=result.warnings,
    )


def analysis_boxplot_png(
    kind: AnnotationKind,
    protein: str,
    conditions: list[str],
    identifier: str = "workflow",
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
) -> bytes:
    return single_protein_boxplot_plot(
        kind=kind,
        protein=protein,
        conditions=conditions,
        identifier=identifier,
        outliers=False,
        dots=False,
        header=True,
        legend=True,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
    )


def analysis_boxplot_table(
    kind: AnnotationKind,
    protein: str,
    conditions: list[str],
    identifier: str = "workflow",
) -> pd.DataFrame:
    return single_protein_boxplot_table(
        kind=kind,
        protein=protein,
        conditions=conditions,
        identifier=identifier,
    )


def analysis_lineplot_png(
    kind: AnnotationKind,
    proteins: list[str],
    conditions: list[str],
    identifier: str = "workflow",
    include_id: bool = False,
    width_cm: float = 20,
    height_cm: float = 10,
    dpi: int = 300,
) -> bytes:
    return single_protein_lineplot_plot(
        kind=kind,
        proteins=proteins,
        conditions=conditions,
        include_id=include_id,
        identifier=identifier,
        header=True,
        legend=True,
        width_cm=width_cm,
        height_cm=height_cm,
        dpi=dpi,
    )


def analysis_lineplot_table(
    kind: AnnotationKind,
    proteins: list[str],
    conditions: list[str],
    identifier: str = "workflow",
    include_id: bool = False,
) -> pd.DataFrame:
    return single_protein_lineplot_table(
        kind=kind,
        proteins=proteins,
        conditions=conditions,
        include_id=include_id,
        identifier=identifier,
    )


apply_cached_wrappers(
    globals(),
    [
        "analysis_volcano_data",
        "analysis_boxplot_png",
        "analysis_boxplot_table",
        "analysis_lineplot_png",
        "analysis_lineplot_table",
    ],
)
