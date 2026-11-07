"""Mapa de favorabilidad de Burgos: malla regular, datos fusionados AEMET + Open-Meteo y confianza.

Malla: celdas de 0,1° (≈ 8 × 11 km), del orden de la resolución de ECMWF IFS (~9 km);
una malla más fina aparentaría un detalle que el dato no tiene. Se conservan las celdas
cuyo centro cae dentro del contorno provincial (IGN vía es-atlas, static/burgos.geojson).

Fusión con AEMET (provisional; ver NOTAS §6.4 y §4c):
- Peso de la estación más cercana con validación correcta: k = exp(−d / 20 km) (20 km SUPUESTO).
- Lluvia diaria: k·AEMET + (1 − k)·Open-Meteo los días con dato AEMET (llega con ~3 días de retraso).
- tmin/tmax/tmed: Open-Meteo − k·sesgo de la estación (Open-Meteo pierde heladas: tmin ≈ +1 °C).

Confianza por celda:
- Partimos del nivel de la estación más cercana (validación AEMET vs Open-Meteo).
- d ≤ 15 km: ese nivel; 15-35 km: baja un nivel; > 35 km o sin estación válida: baja.
"""
import asyncio
import json
import math
import time
from datetime import date, timedelta
from pathlib import Path

from app import modelo, openmeteo, progreso, validacion

PASO = 0.1
DIAS = 45
RADIO_PESO_KM = 20.0
CACHE_TTL = 6 * 3600
CONTORNOS = {"BURGOS": Path(__file__).resolve().parent.parent / "static" / "burgos.geojson"}
NIVELES = ["baja", "media", "alta"]
AVISOS = {
    "alta": None,
    "media": "Open-Meteo diverge algo de AEMET en esta zona o la estación queda a más de 15 km: "
             "la estimación es menos fiable.",
    "baja": "Lejos de estaciones AEMET validadas o el modelo diverge de AEMET en esta zona: "
            "la estimación es poco fiable.",
}

_cache: dict = {}
_candado = asyncio.Lock()  # un solo cálculo a la vez (precálculo de arranque + visitas) para no saturar AEMET


def en_cache(provincia: str = "BURGOS") -> bool:
    hit = _cache.get(provincia)
    return bool(hit and time.time() - hit[0] < CACHE_TTL)


def _poligonos(provincia: str) -> list[list[list[float]]]:
    g = json.loads(CONTORNOS[provincia].read_text())
    anillos = []
    for f in g["features"]:
        geo = f["geometry"]
        polys = geo["coordinates"] if geo["type"] == "MultiPolygon" else [geo["coordinates"]]
        for poly in polys:
            anillos.append(poly[0])  # anillo exterior (los huecos no importan a esta escala)
    return anillos


def _dentro(lon: float, lat: float, anillo: list[list[float]]) -> bool:
    """Ray casting."""
    dentro = False
    j = len(anillo) - 1
    for i in range(len(anillo)):
        xi, yi = anillo[i]
        xj, yj = anillo[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def malla(provincia: str = "BURGOS") -> list[tuple[float, float]]:
    anillos = _poligonos(provincia)
    xs = [c[0] for a in anillos for c in a]
    ys = [c[1] for a in anillos for c in a]
    celdas = []
    lat = math.floor(min(ys) / PASO) * PASO + PASO / 2
    while lat < max(ys):
        lon = math.floor(min(xs) / PASO) * PASO + PASO / 2
        while lon < max(xs):
            if any(_dentro(lon, lat, a) for a in anillos):
                celdas.append((round(lat, 3), round(lon, 3)))
            lon += PASO
        lat += PASO
    return celdas


def _dist_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _confianza(est: dict | None, d: float | None) -> str:
    if est is None or d is None or d > 35:
        return "baja"
    nivel = NIVELES.index(est["confianza"])
    if d > 15:
        nivel = max(0, nivel - 1)
    return NIVELES[nivel]


def fusionar(om_vals: list[dict], est: dict | None, k: float) -> list[dict]:
    """Corrige la serie Open-Meteo de una celda con la estación AEMET más cercana."""
    if est is None or k <= 0:
        return om_vals
    aemet = {v["fecha"]: v for v in est.get("aemet", [])}
    temp = est.get("temperatura", {})
    out = []
    for v in om_vals:
        w = dict(v)
        for t in ("tmin", "tmax", "tmed"):
            sesgo = (temp.get(t) or {}).get("sesgo")
            if w.get(t) is not None and sesgo is not None:
                w[t] = round(w[t] - k * sesgo, 1)
        a = aemet.get(v["fecha"])
        if a and a.get("prec") is not None and w.get("prec") is not None:
            w["prec"] = round(k * a["prec"] + (1 - k) * w["prec"], 1)
        out.append(w)
    return out


async def calcular(provincia: str = "BURGOS") -> dict:
    if en_cache(provincia):
        return _cache[provincia][1]
    async with _candado:
        if en_cache(provincia):  # otro cálculo lo terminó mientras esperábamos
            return _cache[provincia][1]
        progreso.empezar()
        try:
            return await _calcular(provincia)
        finally:
            progreso.terminar()


async def _calcular(provincia: str) -> dict:
    hoy = date.today()
    fin = hoy - timedelta(days=1)
    inicio = fin - timedelta(days=DIAS - 1)
    celdas = malla(provincia)

    aviso_global = None
    estaciones = []
    try:
        val = await validacion.validar({provincia}, 90)
        # Las series AEMET de la validación (90 días) cubren de sobra la ventana del mapa
        estaciones = [e for e in val["estaciones"] if e.get("confianza") in NIVELES]
    except Exception as e:  # AEMET caído: el mapa sigue, solo con Open-Meteo y confianza baja
        aviso_global = f"No se pudo validar con AEMET ({e}); todo el mapa tiene confianza baja."

    progreso.fase("openmeteo_malla")
    om = await openmeteo.diarios([(lat, lon) for lat, lon in celdas], inicio, fin)
    progreso.fase("modelo", len(celdas))

    resultado = []
    for (lat, lon), serie in zip(celdas, om):
        cercana, d = None, None
        for e in estaciones:
            de = _dist_km(lat, lon, e["lat"], e["lon"])
            if d is None or de < d:
                cercana, d = e, de
        k = math.exp(-d / RADIO_PESO_KM) if d is not None else 0.0
        valores = fusionar(serie["valores"], cercana, k)
        punt = modelo.puntuar_todas(valores, hoy)
        conf = _confianza(cercana, d)
        progreso.avanzar()
        resultado.append({
            "lat": lat, "lon": lon, "elevacion": serie.get("elevacion"),
            "estacion": cercana["nombre"] if cercana else None,
            "dist_km": None if d is None else round(d, 1),
            "peso_aemet": round(k, 2),
            "confianza": conf,
            "aviso": AVISOS[conf],
            "indicadores": punt["indicadores"],
            "especies": {sp: {"indice": r["indice"], "limitante": r["limitante"], "factores": r["factores"]}
                         for sp, r in punt["especies"].items()},
        })

    res = {
        "provincia": provincia, "fecha": hoy.isoformat(), "datos_hasta": fin.isoformat(),
        "paso_grados": PASO, "celdas": resultado,
        "estaciones": [{k2: e.get(k2) for k2 in ("indicativo", "nombre", "lat", "lon", "altitud", "confianza", "motivos")}
                       for e in estaciones],
        "aviso_global": aviso_global,
        "nota": "Índice de favorabilidad climática (0-100), no probabilidad calibrada. "
                "No considera bosque, suelo ni orientación (Fase 2).",
        "fuentes": ["AEMET OpenData", openmeteo.ATRIBUCION, "Límites: IGN (es-atlas)"],
    }
    if aviso_global is None:
        _cache[provincia] = (time.time(), res)
    return res
