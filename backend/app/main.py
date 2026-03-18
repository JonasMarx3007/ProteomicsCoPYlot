from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Proteomics CoPYlot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/api/layout")
def layout_info():
    return {
        "app_name": "Proteomics CoPYlot",
        "panels": ["Volcano", "Boxplot", "Protein Details"]
    }