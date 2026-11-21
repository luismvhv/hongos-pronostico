"""Provincias de Castilla y León: metadatos y ficheros estáticos de cada una.

- clave: nombre tal y como lo devuelve AEMET en el inventario (`provincia`, sin tildes, mayúsculas).
- ine: código INE (es-atlas usa el mismo como `id`).
- gadm: identificador GADM nivel 2 que usa GBIF (`gadmGid`), comprobado con /v1/geocode/gadm (nov-2026).
Contornos: static/provincias/<CLAVE>.geojson (IGN vía es-atlas, MIT), y CYL.geojson con las 9.
Hábitat: static/habitat/<CLAVE>.json (scripts/habitat.py; puede no existir todavía para alguna).
"""
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"

PROVINCIAS = {
    "AVILA": {"nombre": "Ávila", "ine": "05", "gadm": "ESP.5.1_1"},
    "BURGOS": {"nombre": "Burgos", "ine": "09", "gadm": "ESP.5.2_1"},
    "LEON": {"nombre": "León", "ine": "24", "gadm": "ESP.5.3_1"},
    "PALENCIA": {"nombre": "Palencia", "ine": "34", "gadm": "ESP.5.4_1"},
    "SALAMANCA": {"nombre": "Salamanca", "ine": "37", "gadm": "ESP.5.5_1"},
    "SEGOVIA": {"nombre": "Segovia", "ine": "40", "gadm": "ESP.5.6_1"},
    "SORIA": {"nombre": "Soria", "ine": "42", "gadm": "ESP.5.7_1"},
    "VALLADOLID": {"nombre": "Valladolid", "ine": "47", "gadm": "ESP.5.8_1"},
    "ZAMORA": {"nombre": "Zamora", "ine": "49", "gadm": "ESP.5.9_1"},
}


def contorno(clave: str) -> Path:
    return STATIC / "provincias" / f"{clave}.geojson"


def habitat(clave: str) -> Path:
    return STATIC / "habitat" / f"{clave}.json"


def normalizar(texto: str) -> str | None:
    """'León', 'leon', 'LEÓN' -> 'LEON'. None si no es una provincia de CyL."""
    t = (texto or "").strip().upper()
    for a, b in zip("ÁÉÍÓÚÜ", "AEIOUU"):
        t = t.replace(a, b)
    return t if t in PROVINCIAS else None


def listado() -> list[dict]:
    return [{"clave": k, **v, "habitat": habitat(k).exists()} for k, v in PROVINCIAS.items()]
