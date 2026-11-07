"""Cliente de Open-Meteo Historical Weather API (archive-api.open-meteo.com).

Comprobado empíricamente contra la API (nov-2026), ver NOTAS.md §4b:
- Variables diarias válidas: temperature_2m_mean/max/min, precipitation_sum,
  relative_humidity_2m_mean, soil_moisture_0_to_7cm_mean, soil_moisture_7_to_28cm_mean,
  et0_fao_evapotranspiration. (soil_moisture_0_to_10cm_mean existe pero sale vacía aquí.)
- Modelo por defecto (best_match) = ECMWF IFS (~9 km), disponible hasta AYER.
  ERA5 / ERA5-Land llevan ~5-6 días de retraso, por eso no se fuerzan.
- Varias coordenadas por petición: latitude=a,b&longitude=c,d -> lista JSON.
- Parámetro `elevation`: corrige la temperatura por altitud (útil para comparar con estaciones).

Condiciones de uso (open-meteo.com/en/terms): API gratuita solo para uso NO comercial,
< 10 000 llamadas/día, 5 000/hora, 600/minuto; datos con licencia CC BY 4.0 -> hay que
atribuir ("Weather data by Open-Meteo.com"). Cada coordenada cuenta como una llamada y
las peticiones largas (>2 semanas o >10 variables) cuentan como fracciones adicionales,
así que se agrupan coordenadas y se cachean resultados.
"""
import asyncio
import time
from datetime import date

import httpx

URL = "https://archive-api.open-meteo.com/v1/archive"
TIMEZONE = "Europe/Madrid"
LOTE = 50          # coordenadas por petición
CACHE_TTL = 6 * 3600

DIARIAS = [
    "temperature_2m_mean",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "relative_humidity_2m_mean",
    "soil_moisture_0_to_7cm_mean",
    "soil_moisture_7_to_28cm_mean",
    "et0_fao_evapotranspiration",
]

# Nombres cortos homogéneos con los de AEMET (app/aemet.py)
RENOMBRA = {
    "temperature_2m_mean": "tmed",
    "temperature_2m_max": "tmax",
    "temperature_2m_min": "tmin",
    "precipitation_sum": "prec",
    "relative_humidity_2m_mean": "hr",
    "soil_moisture_0_to_7cm_mean": "suelo_0_7",
    "soil_moisture_7_to_28cm_mean": "suelo_7_28",
    "et0_fao_evapotranspiration": "et0",
}

ATRIBUCION = "Weather data by Open-Meteo.com (CC BY 4.0)"

_cache: dict = {}


class OpenMeteoError(Exception):
    pass


async def _get(client: httpx.AsyncClient, params: dict):
    """GET con reintentos: el proxy de la sesión y la red móvil cortan conexiones a veces."""
    ultimo = None
    for intento in range(5):
        try:
            r = await client.get(URL, params=params)
            if r.status_code == 429:
                ultimo = OpenMeteoError("Límite de peticiones de Open-Meteo (429)")
                await asyncio.sleep(10 * (intento + 1))
                continue
            data = r.json()
            if isinstance(data, dict) and data.get("error"):
                raise OpenMeteoError(data.get("reason", "Error de Open-Meteo"))
            return data
        except (httpx.TransportError, ValueError) as e:  # ValueError = JSON vacío/cortado
            ultimo = e
            await asyncio.sleep(2 ** intento)
    raise OpenMeteoError(f"Open-Meteo no responde: {ultimo}")


async def diarios(puntos: list[tuple], inicio: date, fin: date, variables: list[str] | None = None) -> list[dict]:
    """Series diarias para varios puntos.

    puntos: lista de (lat, lon) o (lat, lon, elevacion_m).
    Devuelve, en el mismo orden, {"lat", "lon", "elevacion", "valores": [{fecha, tmed, ...}]}.
    """
    variables = variables or DIARIAS
    clave = (tuple(tuple(round(c, 4) for c in p if c is not None) for p in puntos),
             inicio.isoformat(), fin.isoformat(), tuple(variables))
    hit = _cache.get(clave)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]

    out: list[dict] = []
    async with httpx.AsyncClient(timeout=90) as client:
        for i in range(0, len(puntos), LOTE):
            lote = puntos[i:i + LOTE]
            params = {
                "latitude": ",".join(f"{p[0]:.4f}" for p in lote),
                "longitude": ",".join(f"{p[1]:.4f}" for p in lote),
                "start_date": inicio.isoformat(),
                "end_date": fin.isoformat(),
                "daily": ",".join(variables),
                "timezone": TIMEZONE,
            }
            if all(len(p) > 2 and p[2] is not None for p in lote):
                params["elevation"] = ",".join(f"{p[2]:.0f}" for p in lote)
            data = await _get(client, params)
            if isinstance(data, dict):
                data = [data]
            for p, d in zip(lote, data):
                diario = d.get("daily", {})
                fechas = diario.get("time", [])
                valores = []
                for k, f in enumerate(fechas):
                    fila = {"fecha": f}
                    for v in variables:
                        serie = diario.get(v) or []
                        fila[RENOMBRA.get(v, v)] = serie[k] if k < len(serie) else None
                    valores.append(fila)
                out.append({
                    "lat": p[0], "lon": p[1],
                    "lat_modelo": d.get("latitude"), "lon_modelo": d.get("longitude"),
                    "elevacion": d.get("elevation"),
                    "valores": valores,
                })
    _cache[clave] = (time.time(), out)
    return out
