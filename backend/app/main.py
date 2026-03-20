from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_annotations import router as annotations_router
from app.api.routes_data_tools import router as data_tools_router
from app.api.routes_datasets import router as datasets_router
from app.api.routes_external import router as external_router
from app.api.routes_plots import router as plots_router
from app.api.routes_qc import router as qc_router
from app.api.routes_peptide import router as peptide_router
from app.api.routes_stats import router as stats_router

app = FastAPI(title="Proteomics CoPYlot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
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


@app.get("/")
async def root():
    return {"message": "Backend is running"}
