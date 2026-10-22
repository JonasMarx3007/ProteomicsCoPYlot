from __future__ import annotations

"""Phosphosite plots, KSEA and phosphoprotein regulation (`/api/plots/phospho/...`).

One of the routers `routes_plots` combines; see that module for what is shared.
"""


from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

from app.services.plot_export import note_notebook_unavailable
from app.schemas.annotation import DataSource
from app.schemas.qc import PhosphoCoverageMode
from app.services.plot_styling import (
    parse_advanced_plot_settings,
)
from app.services.phospho_tools import (
    ksea_uploaded_volcano_html,
    ksea_table,
    phosprot_regulation_html,
    phosprot_regulation_table,
    phospho_coverage_table,
    phospho_distribution_table,
    phospho_options,
    phospho_sty_table,
    phosphosite_plot_table,
)
from app.services.dataset_reader import read_dataframe
from app.services.upload_limits import ensure_upload_size
from app.api.plot_responses import csv_values, plot_errors, png_response, snapshot_table, table_rows

router = APIRouter()  # mounted under /api/plots by routes_plots


@router.get("/phospho/options")
def phospho_options_route() -> dict[str, object]:
    with plot_errors("Failed to load phospho options"):
        return phospho_options()


@router.get("/phospho/phosphosite-plot.png")
def phosphosite_plot_route(
    color: str = "#87CEEB",
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render phosphosite plot", optional_dependency=True):
        from app.services.notebook_phospho import render_counts
        content, token = render_counts(color=color, width_cm=widthCm, height_cm=heightCm,
            dpi=dpi, advanced=parse_advanced_plot_settings(advanced))
        response = png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get("/phospho/phosphosite-plot-table")
def phosphosite_plot_table_route(snapshot: str = '') -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return snapshot_table('phospho', 'phosphosite_counts', snapshot)
    with plot_errors("Failed to load phosphosite table"):
        return table_rows(phosphosite_plot_table())


@router.get("/phospho/coverage.png")
def phospho_coverage_route(
    includeId: bool = False,
    header: bool = True,
    legend: bool = True,
    mode: PhosphoCoverageMode = "Normal",
    colorClassI: str = "#2563eb",
    colorNotClassI: str = "#f59e0b",
    randomSeed: int = 69,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    conditions: str = "",
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render phospho coverage plot", optional_dependency=True):
        from app.services.notebook_phospho import render_coverage
        content, token = render_coverage(
            include_id=includeId,
            header=header,
            legend=legend,
            mode=mode,
            color_class_i=colorClassI,
            color_not_class_i=colorNotClassI,
            random_seed=randomSeed,
            width_cm=widthCm,
            height_cm=heightCm,
            dpi=dpi,
            conditions=csv_values(conditions),
            advanced=parse_advanced_plot_settings(advanced),
        )
        response = png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get("/phospho/coverage-table")
def phospho_coverage_table_route(
    includeId: bool = False,
    mode: PhosphoCoverageMode = "Normal",
    conditions: str = "",
    snapshot: str = "",
) -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return snapshot_table('phospho', 'phosphosite_coverage', snapshot,
            include_id=includeId, mode=mode, conditions=csv_values(conditions))
    with plot_errors("Failed to load phospho coverage table"):
        return table_rows(
            phospho_coverage_table(
                include_id=includeId,
                mode=mode,
                conditions=csv_values(conditions),
            )
        )


@router.get("/phospho/distribution.png")
def phospho_distribution_route(
    cutoff: float = 0.0,
    header: bool = True,
    color: str = "#87CEEB",
    widthCm: float = 20,
    heightCm: float = 15,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render phospho distribution plot", optional_dependency=True):
        from app.services.notebook_phospho import render_distribution
        content, token = render_distribution(cutoff=cutoff, header=header, color=color,
            width_cm=widthCm, height_cm=heightCm, dpi=dpi, advanced=parse_advanced_plot_settings(advanced))
        response = png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get("/phospho/distribution-table")
def phospho_distribution_table_route(
    cutoff: float = 0.0,
    snapshot: str = '',
) -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return snapshot_table('phospho', 'phosphosite_distribution', snapshot, cutoff=cutoff)
    with plot_errors("Failed to load phospho distribution table"):
        return table_rows(phospho_distribution_table(cutoff=cutoff))


@router.get("/phospho/ksea-table")
def phospho_ksea_table_route(
    condition1: str,
    condition2: str,
    source: str = "volcano",
    dataSource: str = "data",
    condition1Control: str | None = None,
    condition2Control: str | None = None,
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: str = "unpaired",
    useUncorrected: bool = False,
    organism: str = "human",
    proteinCorrection: bool = False,
) -> dict[str, object]:
    with plot_errors("Failed to load Kinase Library table"):
        from app.services.notebook_ksea import capture_table
        from app.services.notebook_provenance import NotebookProvenanceError
        options: dict[str, Any] = dict(
                organism=organism,
                condition1=condition1,
                condition2=condition2,
                source=source,
                data_source=dataSource,
                condition1_control=condition1Control,
                condition2_control=condition2Control,
                p_value_threshold=pValueThreshold,
                log2fc_threshold=log2fcThreshold,
                test_type=testType,
                use_uncorrected=useUncorrected,
                protein_correction=proteinCorrection,
        )
        try:
            table, token = capture_table(**options)
        except NotebookProvenanceError as exc:
            note_notebook_unavailable(exc)
            table, token = ksea_table(**options), ''
        return {**table_rows(table), 'notebookToken': token or None}


@router.post("/phospho/ksea-volcano.html", response_class=HTMLResponse)
def phospho_ksea_uploaded_volcano_route(
    fileSt: UploadFile = File(...),
    fileTnc: UploadFile = File(...),
    pValueThreshold: float = Form(0.1),
    header: bool = Form(True),
    condition1: str = Form(""),
    condition2: str = Form(""),
    condition1Control: str = Form(""),
    condition2Control: str = Form(""),
    annotateHits: bool = Form(False),
    advanced: str = Form(""),
) -> HTMLResponse:
    if not fileSt.filename or not fileTnc.filename:
        raise HTTPException(status_code=400, detail="Both Kinase Library result files are required.")

    with plot_errors("Failed to generate Kinase Library volcano", optional_dependency=True):
        ensure_upload_size(fileSt, label="Kinase Library S/T result file")
        ensure_upload_size(fileTnc, label="Kinase Library Y result file")
        df_st = read_dataframe(fileSt.filename, fileSt.file)
        df_tnc = read_dataframe(fileTnc.filename, fileTnc.file)
        from app.services.assistant_snapshots import store_snapshot
        evidence: dict[str, Any] = {}
        response = HTMLResponse(
            content=ksea_uploaded_volcano_html(
                st_results=df_st,
                evidence_out=evidence,
                tnc_results=df_tnc,
                p_value_threshold=pValueThreshold,
                header=header,
                condition1=condition1,
                condition2=condition2,
                condition1_control=condition1Control,
                condition2_control=condition2Control,
                annotate_hits=annotateHits,
                advanced=parse_advanced_plot_settings(advanced),
            )
        )
        response.headers["X-Copylot-Evidence"] = store_snapshot(evidence)
        return response


def _regulation_notebook_response(**options):
    from app.services.notebook_regulation import render_regulation
    from app.services.notebook_provenance import NotebookProvenanceError
    try:
        content, token = render_regulation(interactive=True, **options)
    except NotebookProvenanceError as exc:
        note_notebook_unavailable(exc)
        content, token = phosprot_regulation_html(**options), ''
    response = HTMLResponse(content=content)
    if token:
        response.headers['X-CoPYlot-Notebook'] = token
    return response


@router.get("/phospho/phosprot-regulation.html", response_class=HTMLResponse)
def phospho_phosprot_regulation_html_route(
    condition1: str,
    condition2: str,
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: str = "unpaired",
    useUncorrected: bool = False,
    maxHoverSites: int = 20,
    showPhosphosites: bool = True,
    dataSource: DataSource = "data",
    proteinCorrection: bool = False,
    header: bool = True,
    advanced: str = "",
) -> HTMLResponse:
    with plot_errors("Failed to render interactive phosprot regulation plot", optional_dependency=True):
        return _regulation_notebook_response(
            condition1=condition1,
            condition2=condition2,
            p_value_threshold=pValueThreshold,
            log2fc_threshold=log2fcThreshold,
            test_type=testType,
            use_uncorrected=useUncorrected,
            max_hover_sites=maxHoverSites,
            show_phosphosites=showPhosphosites,
            data_source=dataSource,
            protein_correction=proteinCorrection,
            header=header,
            advanced=parse_advanced_plot_settings(advanced),
        )


@router.get("/phospho/phosprot-regulation-table")
def phospho_phosprot_regulation_table_route(
    condition1: str,
    condition2: str,
    pValueThreshold: float = 0.05,
    log2fcThreshold: float = 1.0,
    testType: str = "unpaired",
    useUncorrected: bool = False,
    maxHoverSites: int = 20,
    showPhosphosites: bool = True,
    dataSource: DataSource = "data",
    proteinCorrection: bool = False,
    snapshot: str = '',
) -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return snapshot_table('phospho', 'phosprot_regulation', snapshot,
            condition1=condition1, condition2=condition2, p_value_threshold=pValueThreshold,
            log2fc_threshold=log2fcThreshold, test_type=testType, use_uncorrected=useUncorrected,
            max_hover_sites=maxHoverSites, show_phosphosites=showPhosphosites, data_source=dataSource,
            protein_correction=proteinCorrection)
    with plot_errors("Failed to load phosprot regulation table"):
        return table_rows(
            phosprot_regulation_table(
                condition1=condition1,
                condition2=condition2,
                p_value_threshold=pValueThreshold,
                log2fc_threshold=log2fcThreshold,
                test_type=testType,
                use_uncorrected=useUncorrected,
                max_hover_sites=maxHoverSites,
                show_phosphosites=showPhosphosites,
                data_source=dataSource,
                protein_correction=proteinCorrection,
            )
        )


@router.get("/phospho/sty.png")
def phospho_sty_route(
    header: bool = True,
    widthCm: float = 20,
    heightCm: float = 10,
    dpi: int = 300,
    advanced: str = "",
) -> Response:
    with plot_errors("Failed to render STY plot", optional_dependency=True):
        from app.services.notebook_phospho import render_sty
        content, token = render_sty(header=header, width_cm=widthCm, height_cm=heightCm,
            dpi=dpi, advanced=parse_advanced_plot_settings(advanced))
        response = png_response(content)
        if token:
            response.headers['X-CoPYlot-Notebook'] = token
        return response


@router.get("/phospho/sty-table")
def phospho_sty_table_route(snapshot: str = '') -> dict[str, list[dict[str, object]]]:
    if snapshot:
        return snapshot_table('phospho', 'phosphosite_sty', snapshot)
    with plot_errors("Failed to load STY table"):
        return table_rows(phospho_sty_table())
