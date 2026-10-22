from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.schemas.runtime import (
    NormalizationCapabilityResponse,
    RRuntimeStatusResponse,
    StatisticsCapabilityResponse,
)
from app.services.functions import _TEST_TYPES, is_moderated_test_type
from app.services.r_runtime import clear_r_runtime_cache, detect_r_runtime
from app.services.request_security import local_runtime_diagnostics_allowed
from app.services.r_limma import (
    clear_limma_availability_cache,
    limma_availability,
    limma_reference_version,
)
from app.services.r_vsn import (
    clear_vsn_availability_cache,
    vsn_availability,
    vsn_reference_version,
)

router = APIRouter(prefix="/api/runtime", tags=["runtime"])


@router.get("/r", response_model=RRuntimeStatusResponse)
def r_runtime_status_route(request: Request, refresh: bool = False) -> RRuntimeStatusResponse:
    if refresh:
        clear_r_runtime_cache()
        clear_vsn_availability_cache()
        clear_limma_availability_cache()
    runtime = detect_r_runtime()
    if local_runtime_diagnostics_allowed(request):
        return RRuntimeStatusResponse(**runtime)
    # Construct a public response; never mutate the cached diagnostic dictionary.
    return RRuntimeStatusResponse(
        available=bool(runtime["available"]),
        version=runtime.get("version"),
        diagnosticsHidden=True,
        error=None if runtime["available"] else "R runtime is unavailable. Contact the deployment administrator.",
    )


@router.get("/normalization", response_model=NormalizationCapabilityResponse)
def normalization_capability_route(request: Request, refresh: bool = False) -> NormalizationCapabilityResponse:
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
        vsnUnavailableReason=None if vsn_ok else (str(availability.get("reason") or "")
            if local_runtime_diagnostics_allowed(request) else "VSN is unavailable. Contact the deployment administrator."),
        vsnPackageVersion=vsn_reference_version(),
    )


@router.get("/statistics", response_model=StatisticsCapabilityResponse)
def statistics_capability_route(request: Request, refresh: bool = False) -> StatisticsCapabilityResponse:
    """Which volcano test types this installation can actually run.

    The moderated t-tests are delegated to Bioconductor `limma`, so they are
    only offered when Rscript and the package are both present; the UI hides
    them otherwise, as it hides VSN.
    """
    if refresh:
        clear_r_runtime_cache()
        clear_limma_availability_cache()
    availability = limma_availability()
    ok = bool(availability.get("available"))
    test_types = [name for name in _TEST_TYPES if ok or not is_moderated_test_type(name)]
    return StatisticsCapabilityResponse(
        testTypes=test_types,
        moderatedAvailable=ok,
        moderatedUnavailableReason=None if ok else (str(availability.get("reason") or "")
            if local_runtime_diagnostics_allowed(request) else "Moderated t-tests are unavailable. Contact the deployment administrator."),
        limmaPackageVersion=limma_reference_version(),
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
