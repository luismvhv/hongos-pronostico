"""Validación AEMET (observado) vs Open-Meteo (modelo) por estación.

Métricas (umbrales PROVISIONALES de NOTAS.md, a ajustar con más datos):
- Temperatura (tmax, tmin, tmed): MAE y sesgo (Open-Meteo − AEMET). OK si MAE medio < 2 °C.
- Lluvia: acierto llovió/no llovió con umbral de 1 mm/día. OK si > 75 %.
  Como en épocas secas casi todos los días aciertan "no llovió", se informa también
  la detección de días de lluvia (POD) y el ratio de acumulados (OM/AEMET), OK en [0,7, 1,4].
- Confianza: alta si se cumplen las tres; media si falla una; baja si fallan dos o más,
  o si hay menos de 30 días comparables.

Alineación: la `prec` de AEMET del día D es de 07 UTC D a 07 UTC D+1 (ver openmeteo.precip_07a07).
Temperaturas: día civil de Europe/Madrid, con la altitud de la estación pasada a Open-Meteo.
"""
import asyncio
import time
from datetime import date, timedelta

from app import aemet, openmeteo

UMBRAL_LLUVIA_MM = 1.0
UMBRAL_MAE_T = 2.0
UMBRAL_ACIERTO = 0.75
RATIO_MIN, RATIO_MAX = 0.7, 1.4
MIN_DIAS = 30
CACHE_TTL = 12 * 3600
MAX_CONCURRENCIA = 3

_cache: dict = {}


def _mae_sesgo(pares):
    if not pares:
        return None, None
    dif = [m - o for o, m in pares]
    return round(sum(abs(x) for x in dif) / len(dif), 2), round(sum(dif) / len(dif), 2)


def metricas(aemet_vals: list[dict], om_vals: list[dict], om_prec: dict) -> dict:
    """Compara las series de una estación. Función pura (sin red) para poder probarla."""
    om = {v["fecha"]: v for v in om_vals}
    temp = {}
    for k in ("tmax", "tmin", "tmed"):
        pares = [(a[k], om[a["fecha"]][k]) for a in aemet_vals
                 if a.get(k) is not None and om.get(a["fecha"], {}).get(k) is not None]
        mae, sesgo = _mae_sesgo(pares)
        temp[k] = {"n": len(pares), "mae": mae, "sesgo": sesgo}

    pares = [(a["prec"], om_prec[a["fecha"]]) for a in aemet_vals
             if a.get("prec") is not None and om_prec.get(a["fecha"]) is not None]
    n = len(pares)
    lluvia = {"n": n}
    if n:
        u = UMBRAL_LLUVIA_MM
        acierto = sum((o >= u) == (m >= u) for o, m in pares) / n
        dias_lluvia = [(o, m) for o, m in pares if o >= u]
        pod = (sum(m >= u for o, m in dias_lluvia) / len(dias_lluvia)) if dias_lluvia else None
        falsas = [(o, m) for o, m in pares if m >= u]
        far = (sum(o < u for o, m in falsas) / len(falsas)) if falsas else None
        suma_o = sum(o for o, _ in pares)
        suma_m = sum(m for _, m in pares)
        lluvia.update({
            "acierto": round(acierto, 3),
            "pod": None if pod is None else round(pod, 3),
            "falsas_alarmas": None if far is None else round(far, 3),
            "dias_lluvia_aemet": len(dias_lluvia),
            "acum_aemet_mm": round(suma_o, 1),
            "acum_openmeteo_mm": round(suma_m, 1),
            "ratio_acum": round(suma_m / suma_o, 2) if suma_o >= 5 else None,
        })

    # Nivel de confianza
    maes = [t["mae"] for t in temp.values() if t["mae"] is not None]
    mae_medio = round(sum(maes) / len(maes), 2) if maes else None
    fallos = []
    if mae_medio is None or mae_medio >= UMBRAL_MAE_T:
        fallos.append(f"temperatura (MAE {mae_medio} °C ≥ {UMBRAL_MAE_T})")
    if lluvia.get("acierto") is None or lluvia["acierto"] <= UMBRAL_ACIERTO:
        fallos.append(f"lluvia sí/no (acierto {lluvia.get('acierto')} ≤ {UMBRAL_ACIERTO})")
    ratio = lluvia.get("ratio_acum")
    if ratio is not None and not (RATIO_MIN <= ratio <= RATIO_MAX):
        fallos.append(f"lluvia acumulada (ratio {ratio} fuera de [{RATIO_MIN}, {RATIO_MAX}])")
    n_min = min(n, max((t["n"] for t in temp.values()), default=0))
    if n_min < MIN_DIAS:
        nivel = "baja"
        fallos.append(f"pocos días comparables ({n_min} < {MIN_DIAS})")
    else:
        nivel = "alta" if not fallos else ("media" if len(fallos) == 1 else "baja")
    return {"temperatura": temp, "mae_t_medio": mae_medio, "lluvia": lluvia,
            "confianza": nivel, "motivos": fallos}


async def validar(provincias: set[str], dias: int = 90) -> dict:
    clave = (tuple(sorted(provincias)), dias)
    hit = _cache.get(clave)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return hit[1]

    fin = date.today() - timedelta(days=1)
    inicio = fin - timedelta(days=dias - 1)
    todas = await aemet.stations()
    estaciones = [s for s in todas if (s.get("provincia") or "").upper() in provincias]

    sem = asyncio.Semaphore(MAX_CONCURRENCIA)

    async def bajar(est):
        async with sem:
            try:
                return await aemet.daily_values(est["indicativo"], inicio, fin), None
            except Exception as e:
                return [], str(e)

    series = await asyncio.gather(*(bajar(e) for e in estaciones))
    puntos = [(e["lat"], e["lon"], e.get("altitud")) for e in estaciones]
    om = await openmeteo.diarios(puntos, inicio, fin, ["temperature_2m_mean", "temperature_2m_max",
                                                       "temperature_2m_min", "precipitation_sum"])
    om_prec = await openmeteo.precip_07a07(puntos, inicio, fin)

    filas = []
    for est, (vals, err), o, p in zip(estaciones, series, om, om_prec):
        if err or not vals:
            filas.append({**est, "error": err or "Sin datos AEMET", "confianza": "sin_datos", "aemet": []})
            continue
        filas.append({**est, **metricas(vals, o["valores"], p), "error": None, "aemet": vals})

    validas = [f for f in filas if f["confianza"] != "sin_datos"]
    cuenta = {n: sum(f["confianza"] == n for f in validas) for n in ("alta", "media", "baja")}
    res = {
        "desde": inicio.isoformat(), "hasta": fin.isoformat(),
        "umbrales": {"mae_t": UMBRAL_MAE_T, "acierto_lluvia": UMBRAL_ACIERTO,
                     "lluvia_mm": UMBRAL_LLUVIA_MM, "ratio_acum": [RATIO_MIN, RATIO_MAX],
                     "min_dias": MIN_DIAS, "nota": "Umbrales provisionales"},
        "resumen": {"estaciones": len(filas), "validas": len(validas), **cuenta},
        "estaciones": filas,
        "fuente_modelo": openmeteo.ATRIBUCION,
    }
    _cache[clave] = (time.time(), res)
    return res
