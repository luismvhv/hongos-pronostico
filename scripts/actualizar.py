"""Cálculo diario por lotes de las 9 provincias de Castilla y León (fase 4.1).

Lo ejecuta GitHub Actions cada mañana (.github/workflows/actualizar.yml) y escribe en SALIDA/datos/:
  especies.json            catálogo de especies, fuentes y validación (para la web estática)
  mapa/<PROVINCIA>.json    lo mismo que devuelve /api/mapa, ya calculado
  resumen_cyl.json         índice medio por provincia y especie (para el selector de provincias)
  estado.json              cuándo se generó, estado de cada proveedor y de cada provincia

Resiliencia:
- AEMET se pide en bloque (aemet.daily_all, máx. 15 días por petición): ~5 peticiones para toda CyL.
  Si AEMET falla, las provincias se calculan solo con Open-Meteo y confianza baja.
- Open-Meteo con limitador de ritmo (por minuto y por hora) para no superar el plan gratuito.
- Si una provincia falla, se reutiliza su último mapa publicado (--previo) y se marca con su fecha.
- El script termina con código 0 si hay datos (frescos o reutilizados) para todas las provincias;
  el estado degradado lo detecta un paso posterior del workflow, que avisa sin impedir publicar.

Uso: python scripts/actualizar.py --salida sitio [--previo https://.../] [--provincias BURGOS,SORIA]
La clave de AEMET se lee de la variable de entorno AEMET_API_KEY (secreto de GitHub, nunca en el código).
"""
import argparse
import asyncio
import json
import math
import os
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from app import aemet, mapa, modelo, openmeteo, provincias  # noqa: E402

DIAS_VALIDACION = 60          # días de comparación AEMET vs Open-Meteo (≥ 30 exigidos)
BLOQUE_AEMET = 15             # máximo admitido por el endpoint de todas las estaciones
RITMO_OPENMETEO = (450, 4500)  # llamadas por minuto y por hora (límites: 600 y 5 000)


def escribir(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")))


async def aemet_en_bloque(dias: int) -> tuple[dict | None, dict]:
    """Series diarias de las estaciones de CyL de los últimos `dias` días, agrupadas por indicativo."""
    info = {"ok": False, "peticiones": 0, "filas": 0, "estaciones": 0, "ultimo_dato": None, "errores": []}
    if not os.getenv("AEMET_API_KEY"):
        info["errores"].append("Falta AEMET_API_KEY")
        return None, info
    fin = date.today() - timedelta(days=1)
    inicio = fin - timedelta(days=dias - 1)
    series: dict[str, list] = defaultdict(list)
    t = inicio
    while t <= fin:
        b = min(t + timedelta(days=BLOQUE_AEMET - 1), fin)
        info["peticiones"] += 1
        try:
            for f in await aemet.daily_all(t, b):
                if provincias.normalizar(f.get("provincia") or ""):
                    series[f["indicativo"]].append(f)
        except aemet.SinDatos:
            pass  # bloque reciente aún sin publicar (AEMET va con ~3-4 días de retraso)
        except Exception as e:
            info["errores"].append(f"{t}..{b}: {e}")
        t = b + timedelta(days=1)
    for v in series.values():
        v.sort(key=lambda x: x["fecha"] or "")
    info["filas"] = sum(len(v) for v in series.values())
    info["estaciones"] = len(series)
    info["ultimo_dato"] = max((v[-1]["fecha"] for v in series.values() if v), default=None)
    info["ok"] = info["filas"] > 0
    return (dict(series) if info["ok"] else None), info


def resumen_provincia(res: dict, clave: str) -> dict:
    """Índice medio por especie: del clima en las celdas y, si hay capa, solo donde hay hábitat."""
    celdas = res["celdas"]
    por_clave = {f"{c['lat']:.2f},{c['lon']:.2f}": c for c in celdas}
    out = {"celdas": len(celdas),
           "confianza": {n: sum(c["confianza"] == n for c in celdas) for n in ("alta", "media", "baja")},
           "especies": {}}
    subs = []
    ruta = provincias.habitat(clave)
    if ruta.exists():
        h = json.loads(ruta.read_text())
        for f in h["celdas"]:
            sub = dict(zip(h["campos"], f))
            k = f"{math.floor(sub['lat'] * 10 + 1e-9) / 10 + 0.05:.2f},{math.floor(sub['lon'] * 10 + 1e-9) / 10 + 0.05:.2f}"
            if k in por_clave:
                subs.append((sub, por_clave[k]))
    for sp in modelo.ESPECIES:
        clima = [c["especies"][sp]["indice"] for c in celdas]
        con_hab = [(c["especies"][sp]["indice"], modelo.habitat(sp, s)) for s, c in subs]
        con_hab = [(i, h) for i, h in con_hab if h >= 0.05]
        out["especies"][sp] = {
            "clima_medio": round(sum(clima) / len(clima), 1) if clima else None,
            "clima_max": max(clima) if clima else None,
            "con_habitat_medio": round(sum(i * h for i, h in con_hab) / len(con_hab), 1) if con_hab else None,
            "pct_superficie_con_habitat": round(100 * len(con_hab) / len(subs), 1) if subs else None,
        }
    return out


def previo(base: str | None, ruta: str):
    if not base:
        return None
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/" + ruta, timeout=60) as r:
            return json.load(r)
    except Exception:
        return None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", type=Path, required=True)
    ap.add_argument("--previo", help="URL base del sitio publicado (para reutilizar datos si algo falla)")
    ap.add_argument("--provincias", help="Subconjunto separado por comas (pruebas)")
    ap.add_argument("--reutilizar", action="store_true",
                    help="No recalcula: copia los datos ya publicados (republicar la web tras un cambio de código)")
    args = ap.parse_args()
    datos = args.salida / "datos"
    t0 = time.time()
    openmeteo.RITMO = RITMO_OPENMETEO

    claves = [provincias.normalizar(p) for p in args.provincias.split(",")] if args.provincias else list(provincias.PROVINCIAS)
    escribir(datos / "especies.json", modelo.catalogo())

    est = previo(args.previo, "datos/estado.json") if args.reutilizar else None
    if args.reutilizar and not est:
        print("No hay datos publicados que reutilizar: se hace el cálculo completo", flush=True)
    if est:
        # Si el código ha cambiado el catálogo de especies, los datos publicados ya no valen
        muestra = previo(args.previo, "datos/mapa/BURGOS.json")
        publicadas = set(muestra["celdas"][0]["especies"]) if muestra and muestra.get("celdas") else set()
        if publicadas != set(modelo.ESPECIES):
            print(f"El catálogo cambió ({len(publicadas)} → {len(modelo.ESPECIES)} especies): cálculo completo", flush=True)
            est = None
    if est:
        res = previo(args.previo, "datos/resumen_cyl.json")
        faltan = []
        for clave in provincias.PROVINCIAS:
            m = previo(args.previo, f"datos/mapa/{clave}.json")
            if m:
                escribir(datos / "mapa" / f"{clave}.json", m)
            else:
                faltan.append(clave)
        escribir(datos / "estado.json", est)
        if res:
            escribir(datos / "resumen_cyl.json", res)
        print("Datos reutilizados del", est.get("generado"), "; faltan:", faltan)
        return 0

    series, info_aemet = await aemet_en_bloque(DIAS_VALIDACION)
    print("AEMET:", {k: v for k, v in info_aemet.items() if k != "errores"}, info_aemet["errores"][:3], flush=True)

    estado_prov, resumen = {}, {}
    for clave in claves:
        t = time.time()
        try:
            res = await mapa.calcular_lote(clave, series, DIAS_VALIDACION)
            escribir(datos / "mapa" / f"{clave}.json", res)
            resumen[clave] = resumen_provincia(res, clave)
            estado_prov[clave] = {"ok": True, "fresco": True, "fecha_datos": res["datos_hasta"],
                                  "aemet": res["aviso_global"] is None, "segundos": round(time.time() - t)}
        except Exception as e:  # la provincia falla: se reutiliza lo último publicado
            ant = previo(args.previo, f"datos/mapa/{clave}.json")
            if ant:
                escribir(datos / "mapa" / f"{clave}.json", ant)
                resumen[clave] = resumen_provincia(ant, clave)
            estado_prov[clave] = {"ok": ant is not None, "fresco": False, "error": str(e)[:300],
                                  "fecha_datos": ant.get("datos_hasta") if ant else None}
        print(clave, estado_prov[clave], f"Open-Meteo acumulado ≈ {openmeteo.GASTO_TOTAL['llamadas']:.0f} llamadas",
              flush=True)

    estado = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "version": os.getenv("GITHUB_SHA", "local")[:7],
        "segundos": round(time.time() - t0),
        "proveedores": {
            "aemet": info_aemet,
            "openmeteo": {"llamadas_estimadas": round(openmeteo.GASTO_TOTAL["llamadas"])},
        },
        "provincias": estado_prov,
        "degradado": not all(p.get("fresco") and p.get("aemet") for p in estado_prov.values()),
    }
    escribir(datos / "estado.json", estado)
    escribir(datos / "resumen_cyl.json", {"generado": estado["generado"], "provincias": resumen,
                                          "nombres": {k: v["nombre"] for k, v in provincias.PROVINCIAS.items()}})
    print("estado:", json.dumps({k: v for k, v in estado.items() if k != "proveedores"}, ensure_ascii=False))
    return 0 if all(p["ok"] for p in estado_prov.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
