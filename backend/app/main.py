from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_datasets import router as datasets_router

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


@app.get("/")
async def root():
    return {"message": "Backend is running"}