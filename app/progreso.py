"""Progreso del cálculo del mapa, para que la pantalla de carga muestre avances reales.

Un único cálculo a la vez (lo garantiza el candado de app/mapa.py), así que basta un estado global.
"""
import time

FASES = {
    "inventario": "Pidiendo el inventario de estaciones a AEMET",
    "aemet": "Descargando observaciones de las estaciones AEMET",
    "openmeteo_estaciones": "Comparando AEMET con Open-Meteo en cada estación",
    "openmeteo_malla": "Descargando lluvia, temperatura y humedad del suelo de toda la provincia",
    "modelo": "Calculando la favorabilidad de cada especie",
    "listo": "Listo",
}

ESTADO = {"activo": False, "fase": None, "texto": None, "hecho": 0, "total": 0, "inicio": None}


def empezar() -> None:
    ESTADO.update(activo=True, fase=None, texto=None, hecho=0, total=0, inicio=time.time())


def fase(nombre: str, total: int = 0) -> None:
    ESTADO.update(fase=nombre, texto=FASES.get(nombre, nombre), hecho=0, total=total)


def avanzar(n: int = 1) -> None:
    ESTADO["hecho"] = min(ESTADO["total"] or ESTADO["hecho"] + n, ESTADO["hecho"] + n)


def terminar() -> None:
    ESTADO.update(activo=False, fase="listo", texto=FASES["listo"])


def leer() -> dict:
    d = dict(ESTADO)
    d["segundos"] = round(time.time() - d["inicio"]) if d["inicio"] and d["activo"] else None
    return d
