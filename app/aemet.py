"""Cliente mínimo para AEMET OpenData (piloto).

La API funciona en dos pasos: la petición devuelve una URL en el campo
"datos" y es esa URL la que contiene los datos reales.
Los nombres de endpoints y campos deben verificarse contra la documentación
oficial de AEMET OpenData antes de dar el piloto por bueno.
"""
import asyncio
import json
import os
import time
from datetime import date, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE = "https://opendata.aemet.es/opendata"
CHUNK_DAYS = 30  # tamaño de cada petición de datos diarios (ajustable)


class AemetError(Exception):
    pass


def _api_key() -> str:
    key = os.getenv("AEMET_API_KEY", "").strip()
    if not key or key == "pon_aqui_tu_clave":
        raise AemetError("Falta AEMET_API_KEY en el fichero .env")
    return key


async def _fetch_datos(client: httpx.AsyncClient, url: str):
    """Pide una URL de AEMET y sigue el campo 'datos' hasta obtener el contenido."""
    for intento in range(3):
        r = await client.get(url, headers={"api_key": _api_key(), "Accept": "application/json"})
        # 429 = límite de peticiones por minuto de AEMET: esperar y reintentar
        if r.status_code == 429 or (r.headers.get("content-type", "").startswith("application/json")
                                    and r.json().get("estado") == 429):
            await asyncio.sleep(5 * (intento + 1))
            continue
        break
    r.raise_for_status()
    meta = r.json()
    if meta.get("estado") == 404:
        raise AemetError("Sin datos de AEMET para esa estación y periodo")
    if meta.get("estado") != 200:
        raise AemetError(meta.get("descripcion", "Error devuelto por AEMET"))
    r2 = await client.get(meta["datos"])
    r2.raise_for_status()
    # AEMET sirve los datos en ISO-8859-1 (acentos), no en UTF-8
    try:
        text = r2.content.decode("utf-8")
    except UnicodeDecodeError:
        text = r2.content.decode("latin-1")
    return json.loads(text)


def _to_float(value):
    """AEMET usa coma decimal y 'Ip' para precipitación inapreciable."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if s == "Ip":
        return 0.0
    if s == "":
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def _dms_to_decimal(value: str | None):
    """Convierte coordenadas tipo '421033N' (DDMMSS + hemisferio) a grados decimales."""
    if not value:
        return None
    s = value.strip()
    hemi = s[-1].upper()
    digits = s[:-1]
    try:
        # AEMET usa DDMMSS tanto para latitud como para longitud (p. ej. 033713W = 3°37'13" W)
        deg, minutes, seconds = int(digits[:2]), int(digits[2:4]), int(digits[4:6])
    except ValueError:
        return None
    dec = deg + minutes / 60 + seconds / 3600
    return -dec if hemi in "SW" else dec


_INVENTARIO: dict = {"t": 0.0, "datos": None}
INVENTARIO_TTL = 24 * 3600  # el inventario casi no cambia: se cachea un día en memoria


async def stations() -> list[dict]:
    """Inventario de estaciones climatológicas con coordenadas en grados decimales."""
    if _INVENTARIO["datos"] is not None and time.time() - _INVENTARIO["t"] < INVENTARIO_TTL:
        return _INVENTARIO["datos"]
    url = f"{BASE}/api/valores/climatologicos/inventarioestaciones/todasestaciones"
    async with httpx.AsyncClient(timeout=60) as client:
        raw = await _fetch_datos(client, url)
    out = []
    for s in raw:
        lat = _dms_to_decimal(s.get("latitud"))
        lon = _dms_to_decimal(s.get("longitud"))
        if lat is None or lon is None:
            continue
        out.append({
            "indicativo": s.get("indicativo"),
            "nombre": s.get("nombre"),
            "provincia": s.get("provincia"),
            "altitud": _to_float(s.get("altitud")),
            "lat": lat,
            "lon": lon,
        })
    _INVENTARIO.update(t=time.time(), datos=out)
    return out


async def daily_values(station_id: str, start: date, end: date) -> list[dict]:
    """Valores diarios de una estación entre dos fechas, normalizados a números."""
    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=60) as client:
        cursor = start
        while cursor <= end:
            chunk_end = min(cursor + timedelta(days=CHUNK_DAYS - 1), end)
            url = (
                f"{BASE}/api/valores/climatologicos/diarios/datos/"
                f"fechaini/{cursor.isoformat()}T00:00:00UTC/"
                f"fechafin/{chunk_end.isoformat()}T00:00:00UTC/"
                f"estacion/{station_id}"
            )
            raw = await _fetch_datos(client, url)
            for d in raw:
                rows.append({
                    "fecha": d.get("fecha"),
                    "tmed": _to_float(d.get("tmed")),
                    "tmin": _to_float(d.get("tmin")),
                    "tmax": _to_float(d.get("tmax")),
                    "prec": _to_float(d.get("prec")),
                    "hr": _to_float(d.get("hr")) if "hr" in d else None,
                    "sol": _to_float(d.get("sol")) if "sol" in d else None,
                })
            cursor = chunk_end + timedelta(days=1)
    return rows
