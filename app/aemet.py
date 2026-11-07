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


class SinDatos(AemetError):
    """AEMET responde estado 404: no hay datos para esa estación y periodo."""


async def _get_reintentos(client: httpx.AsyncClient, url: str, headers: dict | None = None) -> httpx.Response:
    """GET con espera ante 429 (límite por minuto de AEMET) y ante errores 5xx/red transitorios.

    Comprobado en Render (nov-2026): ~40 peticiones seguidas disparan 429, y las URL de
    `datos` devuelven 500 de vez en cuando; reintentando al cabo de unos segundos funcionan.
    """
    ultimo = None
    for intento in range(6):
        try:
            r = await client.get(url, headers=headers)
        except httpx.TransportError as e:
            ultimo = e
            await asyncio.sleep(3 * (intento + 1))
            continue
        limite = r.status_code == 429
        if not limite and r.headers.get("content-type", "").startswith("application/json"):
            try:
                limite = r.json().get("estado") == 429
            except ValueError:
                pass
        if limite or r.status_code >= 500:
            ultimo = AemetError(f"AEMET respondió {r.status_code}")
            await asyncio.sleep(min(60, 10 * (intento + 1)))
            continue
        r.raise_for_status()
        return r
    raise AemetError(f"AEMET no responde tras varios reintentos: {ultimo}")


async def _fetch_datos(client: httpx.AsyncClient, url: str):
    """Pide una URL de AEMET y sigue el campo 'datos' hasta obtener el contenido."""
    r = await _get_reintentos(client, url, {"api_key": _api_key(), "Accept": "application/json"})
    meta = r.json()
    if meta.get("estado") == 404:
        raise SinDatos("Sin datos de AEMET para esa estación y periodo")
    if meta.get("estado") != 200:
        raise AemetError(meta.get("descripcion", "Error devuelto por AEMET"))
    r2 = await _get_reintentos(client, meta["datos"])
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


_DIARIOS: dict = {}
DIARIOS_TTL = 6 * 3600  # caché por estación y periodo: evita repetir peticiones y el 429


async def daily_values(station_id: str, start: date, end: date) -> list[dict]:
    """Valores diarios de una estación entre dos fechas, normalizados a números.

    Un bloque sin datos (estado 404) no invalida los demás: la estación puede tener huecos.
    Solo si ningún bloque tiene datos se lanza SinDatos.
    """
    clave = (station_id, start.isoformat(), end.isoformat())
    hit = _DIARIOS.get(clave)
    if hit and time.time() - hit[0] < DIARIOS_TTL:
        return hit[1]
    rows: list[dict] = []
    sin_datos = 0
    bloques = 0
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
            bloques += 1
            try:
                raw = await _fetch_datos(client, url)
            except SinDatos:
                raw = []
                sin_datos += 1
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
    if sin_datos == bloques:
        raise SinDatos("Sin datos de AEMET para esa estación y periodo")
    _DIARIOS[clave] = (time.time(), rows)
    return rows
