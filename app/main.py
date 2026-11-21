from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import aemet
from app import openmeteo
from app import validacion
from app import modelo
from app import mapa
from app import progreso
from app import provincias as provs
from app import comparar as comparacion

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

app = FastAPI(title="Pronóstico de fructificación (piloto)")
app.add_middleware(GZipMiddleware, minimum_size=1000)  # el JSON del mapa pasa de ~220 KB a ~25 KB
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


@app.get("/api/comparar")
async def comparar(
    provincias: str = Query("BURGOS", description="Provincias separadas por comas"),
    dias: int = Query(21, ge=3, le=60, description="Días hacia atrás desde ayer"),
):
    """Resumen por estación (lluvia, heladas, sol) en los últimos N días, ordenado por lluvia."""
    filtro = {p.strip().upper() for p in provincias.split(",") if p.strip()}
    try:
        resultados = await comparacion.comparar(filtro, dias)
    except aemet.AemetError as e:
        raise HTTPException(status_code=502, detail=str(e))
    fin = date.today() - timedelta(days=1)
    inicio = fin - timedelta(days=dias - 1)
    return {"desde": inicio.isoformat(), "hasta": fin.isoformat(), "total": len(resultados), "estaciones": resultados}


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


@app.get("/api/openmeteo")
async def openmeteo_diarios(
    lat: float = Query(..., ge=35, le=44.5),
    lon: float = Query(..., ge=-10, le=5),
    dias: int = Query(30, ge=1, le=120, description="Días hacia atrás desde ayer"),
    elevacion: float | None = Query(None, description="Altitud en m para corregir la temperatura"),
):
    """Serie diaria de Open-Meteo (reanálisis/análisis) en un punto: T, lluvia, HR, humedad del suelo, ET0."""
    fin = date.today() - timedelta(days=1)
    inicio = fin - timedelta(days=dias - 1)
    try:
        res = await openmeteo.diarios([(lat, lon, elevacion)], inicio, fin)
    except openmeteo.OpenMeteoError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"desde": inicio.isoformat(), "hasta": fin.isoformat(), "fuente": openmeteo.ATRIBUCION, **res[0]}


@app.get("/api/validacion")
async def validacion_endpoint(
    provincias: str = Query("BURGOS", description="Provincias separadas por comas"),
    dias: int = Query(90, ge=30, le=180),
    series: bool = Query(False, description="Incluir las series diarias de AEMET"),
):
    """Compara AEMET (observado) con Open-Meteo (modelo) por estación y da un nivel de confianza."""
    filtro = {p.strip().upper() for p in provincias.split(",") if p.strip()}
    try:
        res = await validacion.validar(filtro, dias)
    except (aemet.AemetError, openmeteo.OpenMeteoError) as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not series:
        res = {**res, "estaciones": [{k: v for k, v in e.items() if k != "aemet"} for e in res["estaciones"]]}
    return res


@app.get("/api/especies")
async def especies():
    """Catálogo de especies del modelo v0, con las fuentes de cada perfil."""
    return modelo.catalogo()


@app.get("/api/favorabilidad")
async def favorabilidad(
    lat: float = Query(..., ge=35, le=44.5),
    lon: float = Query(..., ge=-10, le=5),
    elevacion: float | None = Query(None),
):
    """Índice de favorabilidad v0 (0-100) por especie en un punto, solo con Open-Meteo."""
    fin = date.today() - timedelta(days=1)
    inicio = fin - timedelta(days=44)
    try:
        res = await openmeteo.diarios([(lat, lon, elevacion)], inicio, fin)
    except openmeteo.OpenMeteoError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"lat": lat, "lon": lon, "hasta": fin.isoformat(), "fuente": openmeteo.ATRIBUCION,
            **modelo.puntuar_todas(res[0]["valores"])}


@app.get("/api/mapa")
async def mapa_endpoint(provincia: str = Query("BURGOS")):
    """Malla de favorabilidad por especie con confianza por celda (la primera vez tarda ~2 min)."""
    prov = provs.normalizar(provincia)
    if prov is None:
        raise HTTPException(status_code=404, detail=f"Provincia no disponible (solo Castilla y León): {provincia}")
    try:
        return await mapa.calcular(prov)
    except openmeteo.OpenMeteoError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/aemet/prueba_todas")
async def prueba_todas(dias: int = Query(5, ge=1, le=62)):
    """Diagnóstico (fase 4.0): ¿da AEMET todas las estaciones en una petición? Solo recuentos."""
    import time
    from collections import Counter
    fin = date.today() - timedelta(days=3)  # AEMET publica con ~3 días de retraso
    inicio = fin - timedelta(days=dias - 1)
    t0 = time.time()
    try:
        filas = await aemet.daily_all(inicio, fin)
    except Exception as e:
        return {"ok": False, "dias": dias, "error": str(e), "segundos": round(time.time() - t0, 1)}
    cyl = [f for f in filas if provs.normalizar(f.get("provincia") or "")]
    return {
        "ok": True, "dias": dias, "desde": inicio.isoformat(), "hasta": fin.isoformat(),
        "segundos": round(time.time() - t0, 1), "filas": len(filas),
        "estaciones": len({f["indicativo"] for f in filas}),
        "estaciones_cyl": len({f["indicativo"] for f in cyl}),
        "filas_cyl_por_provincia": dict(Counter(f["provincia"] for f in cyl)),
        "fechas": sorted({f["fecha"] for f in filas})[:1] + sorted({f["fecha"] for f in filas})[-1:],
    }


@app.get("/api/provincias")
async def provincias_endpoint():
    """Provincias de Castilla y León disponibles (contorno y, si existe, capa de hábitat)."""
    return {"provincias": provs.listado()}


@app.get("/api/mapa/progreso")
async def mapa_progreso():
    """Estado del cálculo en curso (para la pantalla de carga)."""
    return {**progreso.leer(), "en_cache": mapa.en_cache("BURGOS")}


@app.on_event("startup")
async def precalentar():
    """Al arrancar (Render despierta el servicio), calcula el mapa en segundo plano."""
    import asyncio

    async def _tarea():
        try:
            await mapa.calcular("BURGOS")
        except Exception:
            pass  # se reintentará en la primera petición
    asyncio.create_task(_tarea())
