from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.schemas.runtime import NormalizationCapabilityResponse, RRuntimeStatusResponse
from app.services.r_runtime import clear_r_runtime_cache, detect_r_runtime
from app.services.r_vsn import (
    clear_vsn_availability_cache,
    vsn_availability,
    vsn_reference_version,
)

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.get("/r", response_model=RRuntimeStatusResponse)
def r_runtime_status_route(refresh: bool = False) -> RRuntimeStatusResponse:
    if refresh:
        clear_r_runtime_cache()
        clear_vsn_availability_cache()
    return RRuntimeStatusResponse(**detect_r_runtime())


@router.get("/normalization", response_model=NormalizationCapabilityResponse)
def normalization_capability_route(refresh: bool = False) -> NormalizationCapabilityResponse:
    """Which normalization methods this installation can actually run.

    VSN is delegated to Bioconductor `vsn`, so it is only offered when Rscript
    and the package are both present. The UI hides the option otherwise rather
    than letting a user pick something that will fail.
    """
    if refresh:
        clear_r_runtime_cache()
        clear_vsn_availability_cache()
    availability = vsn_availability()
    vsn_ok = bool(availability.get("available"))
    methods = ["none", "median", "quantile"] + (["vsn"] if vsn_ok else [])
    return NormalizationCapabilityResponse(
        methods=methods,
        vsnAvailable=vsn_ok,
        vsnUnavailableReason=None if vsn_ok else str(availability.get("reason") or ""),
        vsnPackageVersion=vsn_reference_version(),
    )


@router.get("/plotly-{version}.js")
def plotly_asset_route(version: str) -> Response:
    """plotly.js for the app's interactive plots; versioned, so cached for good."""
    from app.services.shared_plotly import plotly_bundle

    installed, source = plotly_bundle()
    if version != installed:
        raise HTTPException(status_code=404, detail="Unknown plotly.js version.")
    return Response(content=source, media_type="text/javascript",
                    headers={"Cache-Control": "private, max-age=31536000, immutable"})
