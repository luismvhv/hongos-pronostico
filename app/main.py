from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import aemet

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

app = FastAPI(title="Pronóstico de fructificación (piloto)")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/estaciones")
async def estaciones(provincias: str = Query("", description="Provincias separadas por comas, p. ej. BURGOS,SORIA")):
    """Estaciones con coordenadas. Si se indican provincias, se filtran."""
    try:
        todas = await aemet.stations()
    except aemet.AemetError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if provincias:
        filtro = {p.strip().upper() for p in provincias.split(",") if p.strip()}
        todas = [s for s in todas if (s.get("provincia") or "").upper() in filtro]
    return {"total": len(todas), "estaciones": todas}


@app.get("/api/diarios/{indicativo}")
async def diarios(
    indicativo: str,
    dias: int = Query(30, ge=1, le=365, description="Días hacia atrás desde ayer"),
):
    """Valores diarios de una estación en los últimos N días."""
    fin = date.today() - timedelta(days=1)
    inicio = fin - timedelta(days=dias - 1)
    try:
        valores = await aemet.daily_values(indicativo, inicio, fin)
    except aemet.AemetError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"indicativo": indicativo, "desde": inicio.isoformat(), "hasta": fin.isoformat(), "valores": valores}
