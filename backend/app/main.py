import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes_annotations import router as annotations_router
from app.api.routes_data_tools import router as data_tools_router
from app.api.routes_datasets import router as datasets_router
from app.api.routes_external import router as external_router
from app.api.routes_plots import router as plots_router
from app.api.routes_qc import router as qc_router
from app.api.routes_peptide import router as peptide_router
from app.api.routes_stats import router as stats_router
from app.api.routes_summary import router as summary_router
from app.services.viewer_bootstrap import bootstrap_viewer_mode_if_enabled

app = FastAPI(title="Proteomics CoPYlot API")


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

app.include_router(datasets_router)
app.include_router(annotations_router)
app.include_router(data_tools_router)
app.include_router(stats_router)
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
