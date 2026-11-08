"""Valida el modelo con observaciones reales de GBIF (se ejecuta a mano, no en Render).

Tres pruebas, con los registros de scripts/gbif_descarga.py (Castilla y León ampliada, 2000-2026):

1. HÁBITAT. Factor de hábitat del modelo (app.modelo.habitat) en una ventana de 0,02° centrada en
   cada hallazgo (incertidumbre ≤ 1 km), frente a dos fondos:
   - "territorio": puntos al azar en tierra española de la región;
   - "otras setas" (target-group background): hallazgos de las otras 6 especies. Corrige el sesgo
     de muestreo (la gente busca setas en ciertos sitios, no al azar).
   Métrica: AUC (probabilidad de que un hallazgo tenga más hábitat que un punto de fondo; 0,5 = azar).
   También el "enriquecimiento" de coníferas/frondosas/praderas (media en hallazgos / media en el fondo).
2. FENOLOGÍA. Reparto mensual de los hallazgos frente a los pesos mensuales supuestos del modelo.
3. CLIMA. Para una muestra de hallazgos con fecha exacta: índice climático del modelo (sin hábitat,
   solo Open-Meteo) el día del hallazgo frente al MISMO día y lugar de otros dos años. La época y el
   sitio son iguales, solo cambia el tiempo: si el modelo tiene señal, el día del hallazgo debe puntuar
   más. Métrica: % de pares en que gana el hallazgo (50 % = azar) y prueba de signos.

Limitaciones: datos de solo presencia y sesgados (zonas accesibles, fines de semana, observadores
aficionados); la fecha de observación no es la de inicio de la fructificación. Sirve para ordenar y
calibrar, no da probabilidades absolutas.

Uso: python scripts/gbif_validacion.py REGISTROS.json HRL_DIR PROVINCIAS.geojson CACHE_DIR
     (HRL_DIR con HRL_ForestType_2018.tif y HRL_Grassland_2018.tif de la región, a 0,001°)
Salida: static/validacion_gbif.json (solo agregados; los registros no se publican).
"""
import asyncio
import json
import math
import random
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np
import rasterio

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from app import modelo, openmeteo  # noqa: E402
from app.mapa import _dentro  # noqa: E402

BBOX = (-7.1, 40.0, -1.7, 43.3)
VENTANA = 0.02
MAX_CLIMA_POR_ESPECIE = 50
random.seed(42)


def auc(pos, neg):
    """AUC de Mann-Whitney (empates cuentan 0,5)."""
    pos, neg = np.asarray(pos), np.asarray(neg)
    if not len(pos) or not len(neg):
        return None
    orden = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    rangos = np.empty(len(orden))
    valores = np.concatenate([pos, neg])[orden]
    i = 0
    while i < len(valores):  # rangos medios para empates
        j = i
        while j + 1 < len(valores) and valores[j + 1] == valores[i]:
            j += 1
        rangos[orden[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    r_pos = rangos[:len(pos)].sum()
    return round(float((r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))), 3)


def prueba_signos(ganados, perdidos):
    """p bilateral de la prueba de signos (aprox. normal; empates excluidos)."""
    n = ganados + perdidos
    if n == 0:
        return None
    z = (ganados - n / 2) / math.sqrt(n / 4)
    return round(math.erfc(abs(z) / math.sqrt(2)), 4)


class Capas:
    def __init__(self, d: Path):
        with rasterio.open(d / "HRL_ForestType_2018.tif") as r:
            self.tipo = r.read(1)
            self.t = r.transform
        with rasterio.open(d / "HRL_Grassland_2018.tif") as r:
            self.prad = r.read(1)

    def fracciones(self, lat, lon):
        res = self.t[0]
        c0 = int((lon - VENTANA / 2 - self.t[2]) / res); c1 = int((lon + VENTANA / 2 - self.t[2]) / res)
        f0 = int((self.t[5] - (lat + VENTANA / 2)) / res); f1 = int((self.t[5] - (lat - VENTANA / 2)) / res)
        if c0 < 0 or f0 < 0 or c1 > self.tipo.shape[1] or f1 > self.tipo.shape[0]:
            return None
        tp, pr = self.tipo[f0:f1, c0:c1], self.prad[f0:f1, c0:c1]
        validos = tp != 255
        n = int(validos.sum())
        if n < 0.8 * tp.size:
            return None
        return {"conifera": float(((tp == 2) & validos).sum()) / n,
                "frondosa": float(((tp == 1) & validos).sum()) / n,
                "pradera": float(((pr == 1) & validos).sum()) / n}


def deduplicar(regs):
    vistos, out = set(), []
    for r in regs:
        k = (r["especie"], r["eventDate"][:10] if r["eventDate"] else None,
             round(r["decimalLatitude"], 3), round(r["decimalLongitude"], 3))
        if k not in vistos:
            vistos.add(k)
            out.append(r)
    return out


def validar_habitat(regs, capas, anillos):
    precisos = [r for r in regs if r["coordinateUncertaintyInMeters"] is not None
                and r["coordinateUncertaintyInMeters"] <= 1000]
    for r in precisos:
        r["_frac"] = capas.fracciones(r["decimalLatitude"], r["decimalLongitude"])
    precisos = [r for r in precisos if r["_frac"]]
    # Fondo "territorio": tierra española dentro de la región
    fondo = []
    while len(fondo) < 3000:
        lat, lon = random.uniform(BBOX[1], BBOX[3]), random.uniform(BBOX[0], BBOX[2])
        if any(_dentro(lon, lat, a) for a in anillos):
            f = capas.fracciones(lat, lon)
            if f:
                fondo.append(f)
    out = {}
    for sp in modelo.ESPECIES:
        pres = [r["_frac"] for r in precisos if r["especie"] == sp]
        otras = [r["_frac"] for r in precisos if r["especie"] != sp]
        h_pres = [modelo.habitat(sp, f) for f in pres]
        h_terr = [modelo.habitat(sp, f) for f in fondo]
        h_otras = [modelo.habitat(sp, f) for f in otras]
        media = lambda xs, k: float(np.mean([x[k] for x in xs])) if xs else None
        enriq = {}
        for k in ("conifera", "frondosa", "pradera"):
            m_p, m_t, m_o = media(pres, k), media(fondo, k), media(otras, k)
            enriq[k] = {"hallazgos": round(m_p, 3) if m_p is not None else None,
                        "territorio": round(m_t, 3),
                        "vs_territorio": round(m_p / m_t, 2) if m_p is not None and m_t else None,
                        "vs_otras_setas": round(m_p / m_o, 2) if m_p is not None and m_o else None}
        out[sp] = {
            "n": len(pres),
            "auc_vs_territorio": auc(h_pres, h_terr),
            "auc_vs_otras_setas": auc(h_pres, h_otras),
            "habitat_medio": {"hallazgos": round(float(np.mean(h_pres)), 3) if h_pres else None,
                              "territorio": round(float(np.mean(h_terr)), 3),
                              "otras_setas": round(float(np.mean(h_otras)), 3) if h_otras else None},
            "pct_hallazgos_sin_habitat": round(100 * float(np.mean([h < 0.05 for h in h_pres])), 1) if h_pres else None,
            "pct_territorio_sin_habitat": round(100 * float(np.mean([h < 0.05 for h in h_terr])), 1),
            "composicion": enriq,
        }
    return out, len(precisos)


def validar_fenologia(regs):
    out = {}
    for sp, perfil in modelo.ESPECIES.items():
        meses = Counter(r["month"] for r in regs if r["especie"] == sp and r["month"])
        n = sum(meses.values())
        reparto = {m: round(meses.get(m, 0) / n, 3) for m in range(1, 13)} if n else {}
        pesos = perfil["fenologia"]
        modelo_norm = {m: pesos.get(m, 0.0) for m in range(1, 13)}
        s = sum(modelo_norm.values()) or 1
        modelo_norm = {m: round(v / s, 3) for m, v in modelo_norm.items()}
        # % de hallazgos en meses a los que el modelo da peso 0 (el modelo los descartaría)
        fuera = sum(meses.get(m, 0) for m in range(1, 13) if pesos.get(m, 0) == 0)
        out[sp] = {"n": n, "reparto_real": reparto, "reparto_modelo": modelo_norm,
                   "pct_fuera_de_temporada_modelo": round(100 * fuera / n, 1) if n else None,
                   "solapamiento": round(sum(min(reparto.get(m, 0), modelo_norm[m]) for m in range(1, 13)), 3) if n else None}
    return out


_CLIENTE = None


async def serie(lat, lon, dia, cache):
    global _CLIENTE
    clave = f"{lat:.2f},{lon:.2f},{dia.isoformat()}"
    if clave in cache:
        return cache[clave]
    fin = dia - timedelta(days=1)
    ini = fin - timedelta(days=44)
    if _CLIENTE is None:  # una sola conexión para cientos de consultas
        _CLIENTE = httpx.AsyncClient(timeout=90, http2=False)
    res = await openmeteo.diarios([(lat, lon)], ini, fin, client=_CLIENTE)
    if len(cache) % 25 == 0:
        print("  series en caché:", len(cache), flush=True)
    cache[clave] = res[0]["valores"]
    return cache[clave]


async def validar_clima(regs, cache_path: Path):
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    hoy = date.today()
    out = {}
    for sp in modelo.ESPECIES:
        cand = [r for r in regs if r["especie"] == sp and r["day"] and 2001 <= r["year"] <= 2026
                and (r["coordinateUncertaintyInMeters"] is None or r["coordinateUncertaintyInMeters"] <= 5000)]
        # una por celda de 0,1° y fecha; muestra repartida por años
        unicos = {}
        for r in cand:
            unicos.setdefault((round(r["decimalLatitude"], 1), round(r["decimalLongitude"], 1), r["eventDate"][:10]), r)
        cand = list(unicos.values())
        random.shuffle(cand)
        cand = cand[:MAX_CLIMA_POR_ESPECIE]
        pares, factores = [], defaultdict(lambda: [0, 0])
        for r in cand:
            d = date(r["year"], r["month"], r["day"])
            if d >= hoy:
                continue
            lat, lon = round(r["decimalLatitude"], 2), round(r["decimalLongitude"], 2)
            otros = [y for y in (r["year"] - 1, r["year"] + 1, r["year"] - 2) if 2001 <= y and date(y, 12, 31) < hoy][:2]
            try:
                v = await serie(lat, lon, d, cache)
                s_h = modelo.puntuar(modelo.ESPECIES[sp], modelo.indicadores(v), d)
                for y in otros:
                    dc = d.replace(year=y) if not (d.month == 2 and d.day == 29) else date(y, 2, 28)
                    vc = await serie(lat, lon, dc, cache)
                    s_c = modelo.puntuar(modelo.ESPECIES[sp], modelo.indicadores(vc), dc)
                    pares.append((s_h["indice"], s_c["indice"]))
                    for k in ("agua", "temperatura", "heladas"):
                        a, b = s_h["factores"][k], s_c["factores"][k]
                        if a > b:
                            factores[k][0] += 1
                        elif a < b:
                            factores[k][1] += 1
            except openmeteo.OpenMeteoError as e:
                print("Open-Meteo:", e)
                break
        cache_path.write_text(json.dumps(cache))
        g = sum(a > b for a, b in pares)
        p_ = sum(a < b for a, b in pares)
        out[sp] = {
            "n_hallazgos": len(cand), "n_pares": len(pares),
            "gana_hallazgo_pct": round(100 * g / (g + p_), 1) if g + p_ else None,
            "empates": len(pares) - g - p_,
            "p_signos": prueba_signos(g, p_),
            "indice_medio": {"hallazgo": round(float(np.mean([a for a, _ in pares])), 1) if pares else None,
                             "control": round(float(np.mean([b for _, b in pares])), 1) if pares else None},
            "factores_gana_hallazgo_pct": {k: round(100 * w / (w + l), 1) if w + l else None
                                           for k, (w, l) in factores.items()},
        }
        print(sp, out[sp])
    return out


def main():
    regs_path, hrl_dir, prov_path, cache_dir = map(Path, sys.argv[1:5])
    cache_dir.mkdir(parents=True, exist_ok=True)
    regs = deduplicar(json.loads(regs_path.read_text()))
    prov = json.loads(prov_path.read_text())
    anillos = []
    for f in prov["features"]:
        g = f["geometry"]
        for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]):
            anillos.append(poly[0])
    capas = Capas(hrl_dir)
    hab, n_hab = validar_habitat(regs, capas, anillos)
    print(json.dumps(hab, ensure_ascii=False, indent=1))
    fen = validar_fenologia(regs)
    clima = asyncio.run(validar_clima(regs, cache_dir / "clima_cache.json"))
    resumen = {
        "fecha": date.today().isoformat(),
        "region": "Castilla y León ampliada (lat 40-43,3; lon −7,1 a −1,7), España, 2000-2026",
        "registros": len(regs), "registros_habitat": n_hab,
        "origen": Counter(r["datasetName"] or r["datasetKey"] for r in regs).most_common(8),
        "licencias": Counter(r["license"] for r in regs).most_common(),
        "habitat": hab, "fenologia": fen, "clima": clima,
        "fuente": "GBIF.org, búsqueda por API (occurrence/search), consultada el " + date.today().isoformat(),
    }
    (RAIZ / "static" / "validacion_gbif.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1))
    print("escrito static/validacion_gbif.json")


if __name__ == "__main__":
    main()
