from __future__ import annotations

import io
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import pdist
from scipy.stats import hypergeom, t

from app.schemas.annotation import AnnotationKind
from app.schemas.stats import (
    EnrichmentRequest,
    EnrichmentResultResponse,
    EnrichmentTerm,
    GseaDirection,
    HeatmapValueType,
    IdentifierOption,
    PathwayOptionsResponse,
    SimulationRequest,
    SimulationResultResponse,
    StatisticalOptionsResponse,
    StatsIdentifier,
    StatsSource,
    VolcanoControlRequest,
    VolcanoRequest,
    VolcanoResultResponse,
)
from app.services.annotation_store import get_annotation
from app.services.data_tools import _get_current_frame
from app.services.runtime_cache import apply_cached_wrappers


def _get_plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _get_plotly():
    import plotly.graph_objects as go

    return go


def _to_png_bytes(fig, plt, dpi: int = 150, tight: bool = True) -> bytes:
    buf = io.BytesIO()
    save_kwargs = {"format": "png", "dpi": max(72, int(dpi))}
    if tight:
        save_kwargs["bbox_inches"] = "tight"
    fig.savefig(buf, **save_kwargs)
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _plotly_html(fig) -> str:
    body = fig.to_html(
        full_html=False,
        include_plotlyjs=True,
        config={"displaylogo": False, "responsive": True},
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>"
        "html,body{margin:0;padding:0;background:#fff;width:100%;height:100%;}"
        "#plot-root{width:100%;height:100%;}"
        ".js-plotly-plot,.plotly-graph-div{width:100%!important;min-height:360px;}"
        "</style>"
        "</head><body><div id='plot-root'>"
        f"{body}"
        "</div>"
        "<script>"
        "(function(){"
        "function firstPlot(){"
        "return document.querySelector('.js-plotly-plot,.plotly-graph-div');"
        "}"
        "function resolveLayoutHeight(el){"
        "if(!el){return 0;}"
        "var value=0;"
        "if(el.layout && Number.isFinite(Number(el.layout.height))){value=Number(el.layout.height);}"
        "else if(el._fullLayout && Number.isFinite(Number(el._fullLayout.height))){value=Number(el._fullLayout.height);}"
        "return Math.max(0,value);"
        "}"
        "function resizePlot(){"
        "var el=firstPlot();"
        "if(!(el && window.Plotly)){return;}"
        "var viewportHeight=Math.max(360,(window.innerHeight||0)-8);"
        "var layoutHeight=resolveLayoutHeight(el);"
        "var nextHeight=Math.max(layoutHeight,viewportHeight);"
        "window.Plotly.relayout(el,{height:nextHeight}).catch(function(){});"
        "window.Plotly.Plots.resize(el);"
        "}"
        "window.addEventListener('load', resizePlot);"
        "window.addEventListener('resize', resizePlot);"
        "setTimeout(resizePlot, 80);"
        "setTimeout(resizePlot, 260);"
        "})();"
        "</script></body></html>"
    )


def _cm_to_inch(value_cm: float) -> float:
    return max(1.0, float(value_cm) / 2.54)


def _bh_adjust(pvalues: np.ndarray) -> np.ndarray:
    pvalues = np.asarray(pvalues, dtype=float)
    if pvalues.size == 0:
        return pvalues
    order = np.argsort(pvalues)
    ranked = pvalues[order]
    adjusted = np.empty_like(ranked)
    n = float(len(ranked))
    running = 1.0
    for idx in range(len(ranked) - 1, -1, -1):
        rank = idx + 1.0
        value = float(ranked[idx] * n / rank)
        running = min(running, value)
        adjusted[idx] = running
    adjusted = np.clip(adjusted, 0.0, 1.0)
    restored = np.empty_like(adjusted)
    restored[order] = adjusted
    return restored


def _safe_neg_log10(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values.astype(float), 1e-300, 1.0)
    return -np.log10(clipped)


def _stats_source(kind: AnnotationKind) -> tuple[StatsSource, pd.DataFrame, pd.DataFrame, list[str]]:
    raw = _get_current_frame(kind)
    annotation = get_annotation(kind)
    if annotation is None or annotation.metadata.empty:
        raise ValueError(f"No annotation metadata available for {kind}. Generate annotation first.")

    if not annotation.filtered_data.empty:
        return "filtered", annotation.filtered_data.copy(), annotation.metadata.copy(), []
    if not annotation.log2_data.empty:
        return "log2", annotation.log2_data.copy(), annotation.metadata.copy(), []
    return "raw", raw, annotation.metadata.copy(), [
        "Using raw data because filtered/log2 annotated data is unavailable.",
    ]


def _first_available_column(frame: pd.DataFrame, candidates: list[str]) -> str | None:
    for column in candidates:
        if column in frame.columns:
            return column
    return None


def _workflow_label_candidates(kind: AnnotationKind) -> list[str]:
    if kind == "protein":
        return ["ProteinNames"]
    if kind == "phospho":
        return ["PTM_Collapse_key"]
    return ["Phosphoprotein", "ProteinNames", "PTM_Collapse_key"]


def _gene_label_candidates(kind: AnnotationKind) -> list[str]:
    if kind == "phosprot":
        return ["Gene_group", "GeneNames"]
    return ["GeneNames", "Gene_group"]


def _identifier_options(kind: AnnotationKind, frame: pd.DataFrame) -> list[IdentifierOption]:
    options: list[IdentifierOption] = []
    workflow_column = _first_available_column(frame, _workflow_label_candidates(kind))
    if workflow_column:
        workflow_label_map = {
            "ProteinNames": "Protein Names",
            "PTM_Collapse_key": "Phosphosite Names",
            "Phosphoprotein": "Phosphoprotein Names",
        }
        options.append(
            IdentifierOption(
                key="workflow",
                label=workflow_label_map.get(workflow_column, "Workflow Names"),
            )
        )

    genes_column = _first_available_column(frame, _gene_label_candidates(kind))
    if genes_column:
        options.append(
            IdentifierOption(
                key="genes",
                label="Gene Group" if genes_column == "Gene_group" else "Gene Names",
            )
        )
    return options


def _resolve_label_column(kind: AnnotationKind, identifier: StatsIdentifier, frame: pd.DataFrame) -> str:
    candidates = _workflow_label_candidates(kind) if identifier == "workflow" else _gene_label_candidates(kind)
    resolved = _first_available_column(frame, candidates)
    if resolved:
        return resolved
    raise ValueError("The selected identifier is not available for the current dataset.")


def statistical_options(kind: AnnotationKind) -> StatisticalOptionsResponse:
    source_used, frame, metadata, warnings = _stats_source(kind)
    conditions = sorted(metadata["condition"].dropna().astype(str).drop_duplicates().tolist())
    identifiers = _identifier_options(kind, frame)
    if not identifiers:
        raise ValueError("No valid identifier columns are available for statistical analysis.")
    return StatisticalOptionsResponse(
        kind=kind,
        sourceUsed=source_used,
        availableConditions=conditions,
        availableIdentifiers=identifiers,
        warnings=warnings,
    )


def _clean_feature_name(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.split(";")[0].strip()


def _gene_tokens(value: object) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [token.strip() for token in text.split(";") if token.strip()]


def _normalize_highlight_token(value: object) -> str:
    token = str(value or "").strip().lower()
    if token.endswith("_human"):
        token = token[: -len("_human")]
    return token.strip()


def _volcano_dataframe(
    *,
    kind: AnnotationKind,
    condition1: str,
    condition2: str,
    identifier: StatsIdentifier,
    p_value_threshold: float,
    log2fc_threshold: float,
    test_type: str,
    use_uncorrected: bool,
    condition1_control: str | None = None,
    condition2_control: str | None = None,
) -> tuple[StatsSource, str, pd.DataFrame, list[str]]:
    source_used, frame, metadata, warnings = _stats_source(kind)
    label_column = _resolve_label_column(kind, identifier, frame)

    cols1 = metadata.loc[metadata["condition"] == condition1, "sample"].astype(str).tolist()
    cols2 = metadata.loc[metadata["condition"] == condition2, "sample"].astype(str).tolist()
    if not cols1 or not cols2:
        raise ValueError("Selected conditions do not have any annotated samples.")

    selected_columns = [label_column, *cols1, *cols2]
    if condition1_control and condition2_control:
        ctrl1_cols = metadata.loc[metadata["condition"] == condition1_control, "sample"].astype(str).tolist()
        ctrl2_cols = metadata.loc[metadata["condition"] == condition2_control, "sample"].astype(str).tolist()
        if not ctrl1_cols or not ctrl2_cols:
            raise ValueError("Selected control conditions do not have any annotated samples.")
        selected_columns.extend([*ctrl1_cols, *ctrl2_cols])
    else:
        ctrl1_cols = []
        ctrl2_cols = []

    for extra in (
        "GeneNames",
        "Gene_group",
        "ProteinNames",
        "PTM_Collapse_key",
        "Phosphoprotein",
        "site_num",
        "PTM_Collapse_keys",
    ):
        if extra in frame.columns and extra not in selected_columns:
            selected_columns.append(extra)

    df = frame[[col for col in selected_columns if col in frame.columns]].replace(0, np.nan).copy()
    arr_x = df[cols1].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    arr_y = df[cols2].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)

    if ctrl1_cols and ctrl2_cols:
        arr_ctrl1 = df[ctrl1_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        arr_ctrl2 = df[ctrl2_cols].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        arr_x = arr_x - np.nanmean(arr_ctrl1, axis=1)[:, None]
        arr_y = arr_y - np.nanmean(arr_ctrl2, axis=1)[:, None]

    n1_real = np.sum(~np.isnan(arr_x), axis=1)
    n2_real = np.sum(~np.isnan(arr_y), axis=1)
    valid_mask = (n1_real >= 2) & (n2_real >= 2)
    if not np.any(valid_mask):
        raise ValueError("No rows have enough replicate values for the selected comparison.")

    df = df.loc[valid_mask].reset_index(drop=True)
    arr_x = arr_x[valid_mask]
    arr_y = arr_y[valid_mask]
    n1 = n1_real[valid_mask].astype(float)
    n2 = n2_real[valid_mask].astype(float)

    mean1 = np.nanmean(arr_x, axis=1)
    mean2 = np.nanmean(arr_y, axis=1)
    log2fc = mean2 - mean1

    paired = test_type == "paired"
    if paired:
        if arr_x.shape[1] != arr_y.shape[1]:
            raise ValueError("Paired tests require the same number of replicates in both conditions.")
        diffs = arr_y - arr_x
        valid_pairs = np.sum(~np.isnan(diffs), axis=1) >= 2
        if not np.any(valid_pairs):
            raise ValueError("No rows have enough paired values for the selected comparison.")
        df = df.loc[valid_pairs].reset_index(drop=True)
        diffs = diffs[valid_pairs]
        log2fc = log2fc[valid_pairs]
        n_diff = np.sum(~np.isnan(diffs), axis=1).astype(float)
        mean_diff = np.nanmean(diffs, axis=1)
        se_diff = np.nanstd(diffs, axis=1, ddof=1) / np.sqrt(n_diff)
        with np.errstate(divide="ignore", invalid="ignore"):
            t_stat = mean_diff / se_diff
        pvals = 2.0 * t.sf(np.abs(t_stat), n_diff - 1.0)
    else:
        var1 = np.nanvar(arr_x, axis=1, ddof=1)
        var2 = np.nanvar(arr_y, axis=1, ddof=1)
        pooled_var = ((n1 - 1.0) * var1 + (n2 - 1.0) * var2) / (n1 + n2 - 2.0)
        se = np.sqrt(pooled_var * (1.0 / n1 + 1.0 / n2))
        with np.errstate(divide="ignore", invalid="ignore"):
            t_stat = log2fc / se
        pvals = 2.0 * t.sf(np.abs(t_stat), n1 + n2 - 2.0)

    pvals = np.nan_to_num(pvals, nan=1.0, posinf=1.0, neginf=1.0)
    adj_pvals = pvals if use_uncorrected else _bh_adjust(pvals)

    significance = np.full(len(log2fc), "Not significant", dtype=object)
    significance[(adj_pvals < p_value_threshold) & (log2fc > log2fc_threshold)] = "Upregulated"
    significance[(adj_pvals < p_value_threshold) & (log2fc < -log2fc_threshold)] = "Downregulated"

    result = df.copy()
    result["log2FC"] = log2fc
    result["pval"] = pvals
    result["adj_pval"] = adj_pvals
    result["neg_log10_adj_pval"] = _safe_neg_log10(adj_pvals if not use_uncorrected else pvals)
    result["significance"] = significance
    return source_used, label_column, result, warnings


def _volcano_response(
    kind: AnnotationKind,
    source_used: StatsSource,
    label_column: str,
    df: pd.DataFrame,
    warnings: list[str],
) -> VolcanoResultResponse:
    return VolcanoResultResponse(
        kind=kind,
        sourceUsed=source_used,
        labelColumn=label_column,
        totalRows=int(len(df)),
        upregulatedCount=int((df["significance"] == "Upregulated").sum()),
        downregulatedCount=int((df["significance"] == "Downregulated").sum()),
        notSignificantCount=int((df["significance"] == "Not significant").sum()),
        rows=df.where(pd.notna(df), None).to_dict(orient="records"),
        warnings=warnings,
    )


def run_volcano(payload: VolcanoRequest) -> VolcanoResultResponse:
    source_used, label_column, df, warnings = _volcano_dataframe(
        kind=payload.kind,
        condition1=payload.condition1,
        condition2=payload.condition2,
        identifier=payload.identifier,
        p_value_threshold=payload.pValueThreshold,
        log2fc_threshold=payload.log2fcThreshold,
        test_type=payload.testType,
        use_uncorrected=payload.useUncorrected,
    )
    return _volcano_response(payload.kind, source_used, label_column, df, warnings)


def run_volcano_control(payload: VolcanoControlRequest) -> VolcanoResultResponse:
    source_used, label_column, df, warnings = _volcano_dataframe(
        kind=payload.kind,
        condition1=payload.condition1,
        condition2=payload.condition2,
        identifier=payload.identifier,
        p_value_threshold=payload.pValueThreshold,
        log2fc_threshold=payload.log2fcThreshold,
        test_type=payload.testType,
        use_uncorrected=payload.useUncorrected,
        condition1_control=payload.condition1Control,
        condition2_control=payload.condition2Control,
    )
    return _volcano_response(payload.kind, source_used, label_column, df, warnings)


def _volcano_figure(
    volcano_df: pd.DataFrame,
    *,
    label_column: str,
    condition1: str,
    condition2: str,
    p_value_threshold: float,
    log2fc_threshold: float,
    use_uncorrected: bool,
    highlight_terms: list[str],
):
    go = _get_plotly()
    color_mapping = {
        "Downregulated": "#2563eb",
        "Not significant": "#94a3b8",
        "Upregulated": "#dc2626",
    }
    normalized_highlights = {_normalize_highlight_token(term) for term in highlight_terms if _normalize_highlight_token(term)}

    def is_highlighted(value: object) -> bool:
        if not normalized_highlights:
            return False
        return any(_normalize_highlight_token(token) in normalized_highlights for token in _gene_tokens(value))

    def truncate_ptm_text(value: object, max_chars: int = 100) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars]} ..."

    def build_hover_text(row: pd.Series) -> str:
        raw_label = row.get(label_column, "")
        label_text = "" if pd.isna(raw_label) else str(raw_label)
        parts = [label_text] if label_text else []
        phosphoprotein_value = row.get("Phosphoprotein")
        has_phospho_context = pd.notna(row.get("site_num")) or pd.notna(row.get("PTM_Collapse_keys")) or pd.notna(phosphoprotein_value)
        if has_phospho_context:
            phosphoprotein_text = "" if pd.isna(phosphoprotein_value) else str(phosphoprotein_value)
            site_value = row.get("site_num")
            site_text = ""
            if pd.notna(site_value):
                try:
                    site_text = str(int(float(site_value)))
                except Exception:
                    site_text = str(site_value)

            if label_column == "Phosphoprotein":
                if parts:
                    if site_text:
                        parts[0] = f"{parts[0]} ({site_text} sites)"
                elif phosphoprotein_text:
                    parts = [f"{phosphoprotein_text} ({site_text} sites)" if site_text else phosphoprotein_text]
            else:
                if phosphoprotein_text:
                    phospho_line = f"Phosphoprotein: {phosphoprotein_text}"
                    if site_text:
                        phospho_line = f"{phospho_line} ({site_text} sites)"
                    parts.append(phospho_line)
                elif site_text:
                    parts.append(f"Sites: {site_text}")

            ptm_value = row.get("PTM_Collapse_keys")
            ptm_text = truncate_ptm_text(ptm_value)
            if ptm_text:
                parts.append(ptm_text)

        if not parts:
            return ""
        return "<br>".join(parts)

    fig = go.Figure()
    for significance, color in color_mapping.items():
        subset = volcano_df[volcano_df["significance"] == significance].copy()
        if subset.empty:
            continue
        subset["_hover"] = subset.apply(build_hover_text, axis=1)
        subset["highlighted"] = subset[label_column].apply(is_highlighted)
        for highlighted, size, suffix in ((False, 6, ""), (True, 10, " (highlighted)")):
            part = subset[subset["highlighted"] == highlighted]
            if part.empty:
                continue
            marker = {"color": color, "size": size}
            if highlighted:
                marker["line"] = {"color": "#22c55e", "width": 2}
            fig.add_trace(
                go.Scatter(
                    x=part["log2FC"],
                    y=part["neg_log10_adj_pval"],
                    mode="markers",
                    marker=marker,
                    name=f"{significance}{suffix}",
                    text=part["_hover"],
                    hovertemplate="%{text}<br>log2FC=%{x:.3f}<br>-log10 p=%{y:.3f}<extra></extra>",
                )
            )

    y_line = float(-np.log10(max(p_value_threshold, 1e-300)))
    max_y = max(y_line, float(volcano_df["neg_log10_adj_pval"].max()) if not volcano_df.empty else y_line)
    fig.add_shape(type="line", x0=log2fc_threshold, x1=log2fc_threshold, y0=0, y1=max_y, line=dict(color="black", dash="dash"))
    fig.add_shape(type="line", x0=-log2fc_threshold, x1=-log2fc_threshold, y0=0, y1=max_y, line=dict(color="black", dash="dash"))
    fig.add_shape(
        type="line",
        x0=float(volcano_df["log2FC"].min()) if not volcano_df.empty else -log2fc_threshold,
        x1=float(volcano_df["log2FC"].max()) if not volcano_df.empty else log2fc_threshold,
        y0=y_line,
        y1=y_line,
        line=dict(color="black", dash="dash"),
    )
    fig.update_layout(
        title=f"{condition1} vs {condition2}",
        xaxis_title=f"log2 fold change ({condition2} - {condition1})",
        yaxis_title="-log10 adj. p-value" if not use_uncorrected else "-log10 p-value",
        hovermode="closest",
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return fig


def volcano_html(payload: VolcanoRequest) -> str:
    _, label_column, df, _ = _volcano_dataframe(
        kind=payload.kind,
        condition1=payload.condition1,
        condition2=payload.condition2,
        identifier=payload.identifier,
        p_value_threshold=payload.pValueThreshold,
        log2fc_threshold=payload.log2fcThreshold,
        test_type=payload.testType,
        use_uncorrected=payload.useUncorrected,
    )
    fig = _volcano_figure(
        df,
        label_column=label_column,
        condition1=payload.condition1,
        condition2=payload.condition2,
        p_value_threshold=payload.pValueThreshold,
        log2fc_threshold=payload.log2fcThreshold,
        use_uncorrected=payload.useUncorrected,
        highlight_terms=payload.highlightTerms,
    )
    return _plotly_html(fig)


def volcano_control_html(payload: VolcanoControlRequest) -> str:
    _, label_column, df, _ = _volcano_dataframe(
        kind=payload.kind,
        condition1=payload.condition1,
        condition2=payload.condition2,
        identifier=payload.identifier,
        p_value_threshold=payload.pValueThreshold,
        log2fc_threshold=payload.log2fcThreshold,
        test_type=payload.testType,
        use_uncorrected=payload.useUncorrected,
        condition1_control=payload.condition1Control,
        condition2_control=payload.condition2Control,
    )
    fig = _volcano_figure(
        df,
        label_column=label_column,
        condition1=payload.condition1,
        condition2=payload.condition2,
        p_value_threshold=payload.pValueThreshold,
        log2fc_threshold=payload.log2fcThreshold,
        use_uncorrected=payload.useUncorrected,
        highlight_terms=payload.highlightTerms,
    )
    return _plotly_html(fig)


def _go_db_candidates() -> list[Path]:
    here = Path(__file__).resolve()
    project_root = here.parents[3]
    sibling_root = project_root.parent / "proteomics-copylot"
    return [
        project_root / "data" / "db" / "all_go_terms_genes.csv",
        sibling_root / "data" / "db" / "all_go_terms_genes.csv",
    ]


@lru_cache(maxsize=1)
def load_go_db() -> pd.DataFrame:
    for path in _go_db_candidates():
        if path.exists():
            return pd.read_csv(path)
    searched = ", ".join(str(path) for path in _go_db_candidates())
    raise ValueError(f"Could not find all_go_terms_genes.csv. Checked: {searched}")


def pathway_options() -> PathwayOptionsResponse:
    db = load_go_db()
    pathways = sorted(db["description"].dropna().astype(str).drop_duplicates().tolist())
    return PathwayOptionsResponse(pathways=pathways)


def _different_genes(
    kind: AnnotationKind,
    condition1: str,
    condition2: str,
    p_value_threshold: float,
    log2fc_threshold: float,
    test_type: str,
    use_uncorrected: bool,
) -> tuple[StatsSource, list[str], list[str], list[str]]:
    source_used, gene_column, df, warnings = _volcano_dataframe(
        kind=kind,
        condition1=condition1,
        condition2=condition2,
        identifier="genes",
        p_value_threshold=p_value_threshold,
        log2fc_threshold=log2fc_threshold,
        test_type=test_type,
        use_uncorrected=use_uncorrected,
    )
    if gene_column not in df.columns:
        raise ValueError("A gene label column is required for enrichment analysis.")

    up_genes = [
        _clean_feature_name(value)
        for value in df.loc[df["significance"] == "Upregulated", gene_column].tolist()
    ]
    down_genes = [
        _clean_feature_name(value)
        for value in df.loc[df["significance"] == "Downregulated", gene_column].tolist()
    ]
    up_genes = [gene for gene in up_genes if gene]
    down_genes = [gene for gene in down_genes if gene]
    return source_used, sorted(set(up_genes)), sorted(set(down_genes)), warnings


def _enrichment_terms(gene_list: list[str], top_n: int, min_term_size: int, max_term_size: int) -> list[EnrichmentTerm]:
    genes = sorted({gene.strip() for gene in gene_list if gene and gene.strip()})
    if not genes:
        return []

    db = load_go_db().copy()
    db["gene_list"] = db["genes"].fillna("").astype(str).apply(
        lambda value: sorted({g.strip() for g in value.split(";") if g.strip()})
    )
    background = sorted({gene for genes_in_term in db["gene_list"] for gene in genes_in_term})
    if not background:
        return []

    query = sorted(set(genes).intersection(background))
    if not query:
        return []

    population_size = len(background)
    sample_size = len(query)
    pvalues: list[float] = []
    raw_rows: list[tuple[pd.Series, list[str], float]] = []

    for _, row in db.iterrows():
        term_genes = row["gene_list"]
        term_size = len(term_genes)
        if term_size < min_term_size or term_size > max_term_size:
            continue
        overlap = sorted(set(query).intersection(term_genes))
        if not overlap:
            continue
        p_value = float(hypergeom.sf(len(overlap) - 1, population_size, term_size, sample_size))
        pvalues.append(p_value)
        raw_rows.append((row, overlap, p_value))

    if not raw_rows:
        return []

    adj = _bh_adjust(np.asarray(pvalues, dtype=float))
    terms: list[EnrichmentTerm] = []
    for idx, (row, overlap, p_value) in enumerate(raw_rows):
        term_genes = row["gene_list"]
        terms.append(
            EnrichmentTerm(
                source=str(row.get("source", "")),
                termId=str(row.get("id", "")),
                name=str(row.get("description", "")),
                termSize=len(term_genes),
                intersectionSize=len(overlap),
                hitPercent=(len(overlap) / max(1, len(term_genes))) * 100.0,
                pValue=float(p_value),
                adjPValue=float(adj[idx]),
                intersectingGenes=overlap,
            )
        )

    terms.sort(key=lambda term: (term.adjPValue, term.pValue, -term.intersectionSize))
    return terms[:top_n]


def run_enrichment(payload: EnrichmentRequest) -> EnrichmentResultResponse:
    source_used, up_genes, down_genes, warnings = _different_genes(
        kind=payload.kind,
        condition1=payload.condition1,
        condition2=payload.condition2,
        p_value_threshold=payload.pValueThreshold,
        log2fc_threshold=payload.log2fcThreshold,
        test_type=payload.testType,
        use_uncorrected=payload.useUncorrected,
    )
    return EnrichmentResultResponse(
        kind=payload.kind,
        sourceUsed=source_used,
        upGenes=up_genes,
        downGenes=down_genes,
        upTerms=_enrichment_terms(up_genes, payload.topN, payload.minTermSize, payload.maxTermSize),
        downTerms=_enrichment_terms(down_genes, payload.topN, payload.minTermSize, payload.maxTermSize),
        warnings=warnings,
    )


def gsea_plot_png(payload: EnrichmentRequest, direction: GseaDirection) -> bytes:
    plt = _get_plt()
    result = run_enrichment(payload)
    terms = result.upTerms if direction == "up" else result.downTerms
    if not terms:
        raise ValueError(f"No {direction}regulated enrichment terms found for the selected parameters.")

    frame = pd.DataFrame(
        {
            "name": [term.name for term in terms],
            "hitPercent": [term.hitPercent for term in terms],
            "intersectionSize": [term.intersectionSize for term in terms],
            "score": [_safe_neg_log10(np.asarray([term.adjPValue]))[0] for term in terms],
        }
    )
    fig, ax = plt.subplots(figsize=(8, 6))
    scatter = ax.scatter(
        frame["hitPercent"],
        np.arange(len(frame)),
        s=frame["intersectionSize"] * 30,
        c=frame["score"],
        cmap="RdBu_r",
    )
    ax.set_yticks(np.arange(len(frame)))
    ax.set_yticklabels(frame["name"])
    ax.set_xlabel("Hits (%)")
    ax.set_title(f"{'Up' if direction == 'up' else 'Down'}regulated Gene Set Enrichment")
    cbar = fig.colorbar(scatter, ax=ax, pad=0.15)
    cbar.set_label("-log10 adjusted p-value")
    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=220)


def pathway_heatmap_png(
    *,
    kind: AnnotationKind,
    pathway: str,
    conditions: list[str],
    value_type: HeatmapValueType,
    include_id: bool,
    header: bool,
    remove_empty: bool,
    cluster_rows: bool,
    cluster_cols: bool,
    width_cm: float,
    height_cm: float,
    dpi: int,
) -> bytes:
    plt = _get_plt()
    _, frame, metadata, _ = _stats_source(kind)
    gene_column = _first_available_column(frame, _gene_label_candidates(kind))
    if gene_column is None:
        raise ValueError("A gene label column is required for pathway heatmaps.")

    db = load_go_db()
    pathway_row = db.loc[db["description"].astype(str).str.lower() == pathway.strip().lower()]
    if pathway_row.empty:
        raise ValueError(f"No pathway found matching '{pathway}'.")
    pathway_genes = [gene.strip() for gene in str(pathway_row.iloc[0]["genes"]).split(";") if gene.strip()]
    if not pathway_genes:
        raise ValueError("The selected pathway does not contain any genes.")

    meta_filtered = metadata.copy()
    if conditions:
        meta_filtered = meta_filtered[meta_filtered["condition"].isin(conditions)]
    if meta_filtered.empty:
        raise ValueError("No samples match the selected conditions.")

    sample_columns = meta_filtered["sample"].astype(str).tolist()
    value_frame = frame[sample_columns].apply(pd.to_numeric, errors="coerce")

    gene_to_row: dict[str, pd.Series] = {}
    for idx, gene_value in frame[gene_column].items():
        for token in _gene_tokens(gene_value):
            gene_to_row.setdefault(token.lower(), value_frame.loc[idx])

    matrix_rows: list[pd.Series] = []
    matrix_index: list[str] = []
    for gene in pathway_genes:
        row = gene_to_row.get(gene.lower())
        if row is None:
            matrix_rows.append(pd.Series([np.nan] * len(sample_columns), index=sample_columns))
        else:
            matrix_rows.append(row)
        matrix_index.append(gene)

    heatmap_data = pd.DataFrame(matrix_rows, index=matrix_index, columns=sample_columns)
    if remove_empty:
        heatmap_data = heatmap_data.dropna(how="all")
    if heatmap_data.empty:
        raise ValueError("No matching pathway genes were found in the current dataset.")

    if value_type == "z":
        def z_transform(row: pd.Series) -> pd.Series:
            mean = row.mean(skipna=True)
            std = row.std(skipna=True)
            if pd.isna(std) or float(std) == 0.0:
                return pd.Series([np.nan] * len(row), index=row.index)
            return (row - mean) / std

        heatmap_data = heatmap_data.apply(z_transform, axis=1)
        color_label = "Z-score"
    else:
        color_label = "log2 Intensity"

    meta_filtered = meta_filtered.reset_index(drop=True)
    # Keep pathway heatmap sample labels aligned with the app-wide convention:
    # condition + running number, without original sample names.
    meta_filtered["condition"] = meta_filtered["condition"].astype(str)
    meta_filtered["sample_index"] = meta_filtered.groupby("condition").cumcount() + 1
    meta_filtered["display"] = meta_filtered.apply(
        lambda row: f"{row['condition']}_{int(row['sample_index'])}",
        axis=1,
    )
    label_map = dict(zip(meta_filtered["sample"].astype(str), meta_filtered["display"]))
    heatmap_data = heatmap_data.rename(columns=label_map)

    if cluster_rows and heatmap_data.shape[0] > 1:
        row_order = leaves_list(linkage(pdist(heatmap_data.fillna(0.0).to_numpy(dtype=float)), method="average"))
        heatmap_data = heatmap_data.iloc[row_order]
    if cluster_cols and heatmap_data.shape[1] > 1:
        col_order = leaves_list(linkage(pdist(heatmap_data.fillna(0.0).T.to_numpy(dtype=float)), method="average"))
        heatmap_data = heatmap_data.iloc[:, col_order]

    fig, ax = plt.subplots(figsize=(_cm_to_inch(width_cm), _cm_to_inch(height_cm)), dpi=max(72, int(dpi)))
    matrix = np.ma.masked_invalid(heatmap_data.to_numpy(dtype=float))
    image = ax.imshow(matrix, aspect="auto", cmap="plasma")
    ax.set_xticks(np.arange(heatmap_data.shape[1]))
    ax.set_xticklabels(list(heatmap_data.columns), rotation=90)
    ax.set_yticks(np.arange(heatmap_data.shape[0]))
    ax.set_yticklabels(list(heatmap_data.index) if header else [""] * heatmap_data.shape[0])
    ax.set_title(f"{pathway} ({'Z-transformed' if value_type == 'z' else 'log2 Intensities'})")
    cbar = fig.colorbar(image, ax=ax)
    cbar.set_label(color_label)
    fig.tight_layout()
    return _to_png_bytes(fig, plt, dpi=dpi)


def _simulation_dataframe(payload: SimulationRequest) -> tuple[StatsSource, pd.DataFrame, list[str]]:
    source_used, frame, metadata, warnings = _stats_source(payload.kind)
    label_column = _first_available_column(frame, _workflow_label_candidates(payload.kind))
    if label_column is None:
        raise ValueError("A workflow label column is required for simulation.")

    cols1 = metadata.loc[metadata["condition"] == payload.condition1, "sample"].astype(str).tolist()
    cols2 = metadata.loc[metadata["condition"] == payload.condition2, "sample"].astype(str).tolist()
    if not cols1 or not cols2:
        raise ValueError("Selected conditions do not have any annotated samples.")

    data_filtered = frame[[label_column, *cols1, *cols2]].replace(0, np.nan).copy()
    x_data = data_filtered[cols1].apply(pd.to_numeric, errors="coerce")
    y_data = data_filtered[cols2].apply(pd.to_numeric, errors="coerce")
    n1_real = x_data.notna().sum(axis=1)
    n2_real = y_data.notna().sum(axis=1)
    valid_mask = (n1_real >= 2) & (n2_real >= 2)
    if not np.any(valid_mask):
        raise ValueError("No rows have enough replicate values for the selected simulation.")

    x_data = x_data.loc[valid_mask]
    y_data = y_data.loc[valid_mask]
    data_filtered = data_filtered.loc[valid_mask].reset_index(drop=True)
    mean1 = x_data.mean(axis=1)
    mean2 = y_data.mean(axis=1)
    var1 = x_data.var(axis=1, ddof=1)
    var2 = y_data.var(axis=1, ddof=1)

    if payload.sampleSizeOverride in (0, 1):
        n1 = n1_real.loc[valid_mask].astype(float)
        n2 = n2_real.loc[valid_mask].astype(float)
    else:
        n1 = pd.Series(float(payload.sampleSizeOverride), index=mean1.index)
        n2 = pd.Series(float(payload.sampleSizeOverride), index=mean2.index)

    pooled_var = ((n1 - 1.0) * var1 + (n2 - 1.0) * var2) / (n1 + n2 - 2.0)
    pooled_var = pooled_var * payload.varianceMultiplier
    se = np.sqrt(pooled_var * (1.0 / n1 + 1.0 / n2))
    log2fc = mean2 - mean1
    with np.errstate(divide="ignore", invalid="ignore"):
        t_stat = log2fc / se
    pvals_array = np.asarray(2.0 * t.sf(np.abs(t_stat), n1 + n2 - 2.0), dtype=float)
    pvals_array = np.nan_to_num(pvals_array, nan=1.0, posinf=1.0, neginf=1.0)
    adj_pvals = _bh_adjust(pvals_array)

    significance = np.full(len(log2fc), "Not significant", dtype=object)
    log2fc_array = log2fc.to_numpy(dtype=float)
    significance[(adj_pvals < payload.pValueThreshold) & (log2fc_array > payload.log2fcThreshold)] = "Upregulated"
    significance[(adj_pvals < payload.pValueThreshold) & (log2fc_array < -payload.log2fcThreshold)] = "Downregulated"

    result = pd.DataFrame(
        {
            "Feature": data_filtered[label_column].astype(str).tolist(),
            "log2FC": log2fc_array,
            "pval": pvals_array,
            "adj_pval": adj_pvals,
            "significance": significance,
        }
    )
    result["neg_log10_adj_pval"] = _safe_neg_log10(result["adj_pval"].to_numpy(dtype=float))
    return source_used, result, warnings


def run_simulation(payload: SimulationRequest) -> SimulationResultResponse:
    source_used, frame, warnings = _simulation_dataframe(payload)
    return SimulationResultResponse(
        kind=payload.kind,
        sourceUsed=source_used,
        totalRows=int(len(frame)),
        upregulatedCount=int((frame["significance"] == "Upregulated").sum()),
        downregulatedCount=int((frame["significance"] == "Downregulated").sum()),
        notSignificantCount=int((frame["significance"] == "Not significant").sum()),
        warnings=warnings,
    )


def simulation_html(payload: SimulationRequest) -> str:
    go = _get_plotly()
    _, frame, _ = _simulation_dataframe(payload)
    color_mapping = {
        "Downregulated": "#2563eb",
        "Not significant": "#94a3b8",
        "Upregulated": "#dc2626",
    }
    fig = go.Figure()
    for significance, color in color_mapping.items():
        subset = frame[frame["significance"] == significance]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset["log2FC"],
                y=subset["neg_log10_adj_pval"],
                mode="markers",
                marker=dict(color=color, size=6),
                name=significance,
                text=subset["Feature"],
                hovertemplate="%{text}<br>log2FC=%{x:.3f}<br>-log10 adj p=%{y:.3f}<extra></extra>",
            )
        )
    y_line = float(-np.log10(max(payload.pValueThreshold, 1e-300)))
    max_y = max(y_line, float(frame["neg_log10_adj_pval"].max()) if not frame.empty else y_line)
    fig.add_shape(type="line", x0=payload.log2fcThreshold, x1=payload.log2fcThreshold, y0=0, y1=max_y, line=dict(color="black", dash="dash"))
    fig.add_shape(type="line", x0=-payload.log2fcThreshold, x1=-payload.log2fcThreshold, y0=0, y1=max_y, line=dict(color="black", dash="dash"))
    fig.add_shape(
        type="line",
        x0=float(frame["log2FC"].min()) if not frame.empty else -payload.log2fcThreshold,
        x1=float(frame["log2FC"].max()) if not frame.empty else payload.log2fcThreshold,
        y0=y_line,
        y1=y_line,
        line=dict(color="black", dash="dash"),
    )
    fig.update_layout(
        title=f"{payload.condition1} vs {payload.condition2}",
        xaxis_title=f"log2 fold change ({payload.condition2} - {payload.condition1})",
        yaxis_title="-log10 adj. p-value",
        hovermode="closest",
        margin=dict(l=40, r=20, t=50, b=40),
    )
    return _plotly_html(fig)


apply_cached_wrappers(
    globals(),
    [
        "statistical_options",
        "run_volcano",
        "run_volcano_control",
        "volcano_html",
        "volcano_control_html",
        "pathway_options",
        "run_enrichment",
        "gsea_plot_png",
        "pathway_heatmap_png",
        "run_simulation",
        "simulation_html",
    ],
)
