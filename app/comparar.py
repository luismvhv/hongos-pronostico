"""Resumen comparativo de estaciones para el piloto de fructificación.

Para cada estación calcula, en un periodo reciente:
- lluvia acumulada (mm) y número de días con lluvia,
- número de heladas (tmin <= 0 °C),
- temperatura media y horas de sol medias.
"""
import asyncio
from datetime import date, timedelta

from app import aemet

MAX_CONCURRENCIA = 3  # peticiones simultáneas a AEMET (evita saturarla)


def resumir(valores: list[dict]) -> dict:
    """Resume una lista de valores diarios de una estación."""
    dias = [v for v in valores if v.get("fecha")]
    prec = [v["prec"] for v in dias if v.get("prec") is not None]
    tmin = [v["tmin"] for v in dias if v.get("tmin") is not None]
    tmed = [v["tmed"] for v in dias if v.get("tmed") is not None]
    sol = [v["sol"] for v in dias if v.get("sol") is not None]
    return {
        "dias": len(dias),
        "lluvia_mm": round(sum(prec), 1) if prec else None,
        "dias_con_lluvia": sum(1 for p in prec if p > 0),
        "heladas": sum(1 for t in tmin if t <= 0),
        "tmed_media": round(sum(tmed) / len(tmed), 1) if tmed else None,
        "sol_medio_h": round(sum(sol) / len(sol), 1) if sol else None,
    }


async def comparar(provincias: set[str], dias: int) -> list[dict]:
    """Compara las estaciones de las provincias indicadas en los últimos N días."""
    todas = await aemet.stations()
    estaciones = [s for s in todas if (s.get("provincia") or "").upper() in provincias]

    fin = date.today() - timedelta(days=1)
    inicio = fin - timedelta(days=dias - 1)
    semaforo = asyncio.Semaphore(MAX_CONCURRENCIA)

    async def procesar(est: dict) -> dict:
        async with semaforo:
            try:
                valores = await aemet.daily_values(est["indicativo"], inicio, fin)
                return {**est, **resumir(valores), "error": None}
            except Exception as e:  # una estación fallida no tumba la comparación
                return {**est, "error": str(e)}

    resultados = await asyncio.gather(*(procesar(e) for e in estaciones))
    # Ordena por lluvia acumulada (las que no tienen dato, al final)
    return sorted(resultados, key=lambda r: (r.get("lluvia_mm") is None, -(r.get("lluvia_mm") or 0)))
