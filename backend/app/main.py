import os
import sys
import io
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.routes_annotations import router as annotations_router
from app.api.routes_data_tools import router as data_tools_router
from app.api.routes_datasets import router as datasets_router
from app.api.routes_external import router as external_router
from app.api.routes_plots import router as plots_router
from app.api.routes_qc import router as qc_router
from app.api.routes_peptide import router as peptide_router
from app.api.routes_stats import router as stats_router
from app.api.routes_analysis import router as analysis_router
from app.api.routes_summary import router as summary_router
from app.services.viewer_bootstrap import bootstrap_viewer_mode_if_enabled

app = FastAPI(title="Proteomics CoPYlot API")

_SUPPORTED_DOWNLOAD_FORMATS = {"png", "jpg", "jpeg", "webp", "pdf"}


def _convert_png_bytes(content: bytes, target_format: str) -> tuple[bytes, str]:
    fmt = target_format.strip().lower()
    if fmt == "png":
        return content, "image/png"
    if fmt not in _SUPPORTED_DOWNLOAD_FORMATS:
        raise ValueError(
            f"Unsupported download format '{target_format}'. Choose one of: "
            "png, jpg, jpeg, webp, pdf."
        )

    from PIL import Image

    image = Image.open(io.BytesIO(content))
    if fmt in {"jpg", "jpeg", "webp", "pdf"} and image.mode in {"RGBA", "LA", "P"}:
        image = image.convert("RGB")

    out = io.BytesIO()
    if fmt in {"jpg", "jpeg"}:
        image.save(out, format="JPEG", quality=95)
        media_type = "image/jpeg"
    elif fmt == "webp":
        image.save(out, format="WEBP", quality=95)
        media_type = "image/webp"
    else:
        image.save(out, format="PDF")
        media_type = "application/pdf"
    return out.getvalue(), media_type


def _resolve_frontend_dist() -> Path | None:
    candidates: list[Path] = []

    env_dist = os.getenv("COPYLOT_FRONTEND_DIST", "").strip()
    if env_dist:
        candidates.append(Path(env_dist))

    project_root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            project_root / "frontend" / "dist",
            project_root / "frontend_dist",
        ]
    )

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "frontend_dist")

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "frontend_dist")

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if (resolved / "index.html").is_file():
            return resolved

    return None

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def plot_download_format_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.method != "GET":
        return response
    if response.status_code < 200 or response.status_code >= 300:
        return response
    if not request.url.path.startswith("/api/plots/"):
        return response

    requested_format = request.query_params.get("downloadFormat", "").strip().lower()
    if not requested_format or requested_format == "png":
        return response

    media_type = response.headers.get("content-type", "").lower()
    if "image/png" not in media_type:
        return response

    body = b""
    body_iterator = getattr(response, "body_iterator", None)
    if body_iterator is not None:
        async for chunk in body_iterator:
            body += chunk
    else:
        body = getattr(response, "body", b"")

    try:
        converted, converted_media_type = _convert_png_bytes(body, requested_format)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"detail": f"Failed to convert plot to '{requested_format}': {exc}"},
        )

    passthrough_headers: dict[str, str] = {}
    for key, value in response.headers.items():
        lowered = key.lower()
        if lowered in {"content-type", "content-length"}:
            continue
        passthrough_headers[key] = value
    return Response(
        content=converted,
        status_code=response.status_code,
        media_type=converted_media_type,
        headers=passthrough_headers,
    )

app.include_router(datasets_router)
app.include_router(annotations_router)
app.include_router(data_tools_router)
app.include_router(stats_router)
app.include_router(analysis_router)
app.include_router(qc_router)
app.include_router(peptide_router)
app.include_router(plots_router)
app.include_router(external_router)
app.include_router(summary_router)

_FRONTEND_DIST = _resolve_frontend_dist()
if _FRONTEND_DIST is not None:
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")


@app.on_event("startup")
async def startup_event():
    bootstrap_viewer_mode_if_enabled()


@app.get("/api/health")
async def health():
    return {
        "message": "Backend is running",
        "frontendDist": str(_FRONTEND_DIST) if _FRONTEND_DIST else None,
    }


if _FRONTEND_DIST is None:
    @app.get("/")
    async def root():
        return {"message": "Backend is running"}
