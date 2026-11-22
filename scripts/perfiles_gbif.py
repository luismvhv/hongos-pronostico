"""Temporada y hábitat de las especies nuevas a partir de sus hallazgos en GBIF (a mano, no en Render).

Para cada especie de app/catalogo_especies.NUEVAS:
- Temporada: reparto mensual de sus hallazgos (CyL ampliada, 2000-2026) normalizado al mes máximo;
  meses con < 2 % de hallazgos a 0. Mismo criterio que la recalibración de las 7 primeras (NOTAS §5g).
- Hábitat: se prueban varias definiciones (coníferas, frondosas, pradera y combinaciones) y
  saturaciones; se elige la de mayor AUC frente a los hallazgos de las OTRAS especies (corrige el
  sesgo de dónde busca la gente). Si la ganancia de saturación es < 0,01, la que deja menos hallazgos
  fuera. Si ninguna definición llega a AUC 0,55, la especie NO se filtra por hábitat (factor 1):
  mejor no ocultar zonas donde sí aparece.

Uso: python scripts/perfiles_gbif.py HRL_DIR CACHE_REGISTROS.json
     (HRL_DIR con HRL_ForestType_2018.tif y HRL_Grassland_2018.tif de CyL ampliada a 0,001°)
Salida: app/perfiles_gbif.json (solo agregados; los registros no se publican).
"""
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))
import gbif_descarga as gd  # noqa: E402
import gbif_validacion as gv  # noqa: E402
from app import modelo  # noqa: E402
from app.catalogo_especies import NUEVAS  # noqa: E402

UMBRAL_SIN_FILTRO = 0.55
ALTERNATIVAS = {
    "coníferas": {"conifera": 1.0},
    "frondosas": {"frondosa": 1.0},
    "bosque (coníferas y frondosas)": {"conifera": 1.0, "frondosa": 1.0},
    "coníferas y algo de frondosas": {"conifera": 1.0, "frondosa": 0.5},
    "frondosas y algo de coníferas": {"frondosa": 1.0, "conifera": 0.5},
    "praderas": {"pradera": 1.0},
    "praderas y bosque claro de frondosas": {"pradera": 1.0, "frondosa": 0.5},
}
SATURACIONES = (0.2, 0.3, 0.5)


def descargar(cache: Path) -> list[dict]:
    if cache.exists():
        return json.loads(cache.read_text())
    taxones = {**gd.ESPECIES, **{k: v["taxon"] for k, v in NUEVAS.items()}}
    filas = []
    for sp, key in taxones.items():
        offset, n = 0, 0
        while True:
            d = gd.pedir({**gd.FILTROS, "taxonKey": key, "limit": 300, "offset": offset})
            for r in d["results"]:
                if not gd.es_ausencia(r):
                    filas.append({"especie": sp, **{c: r.get(c) for c in gd.CAMPOS}})
                    n += 1
            offset += 300
            if d.get("endOfRecords") or offset >= d["count"]:
                break
        print(f"{sp}: {n}", flush=True)
        if n == 0:
            raise RuntimeError(f"GBIF no devolvió registros de {sp}: no se guarda la caché")
    cache.write_text(json.dumps(filas))
    return filas


def temporada(regs) -> tuple[dict, int]:
    meses = Counter(r["month"] for r in regs if r["month"])
    n = sum(meses.values())
    mx = max(meses.values())
    return {m: round(c / mx, 2) for m, c in sorted(meses.items()) if c / n >= 0.02}, n


def habitat(sp, pres, otras) -> dict:
    filas = []
    for nombre, capas in ALTERNATIVAS.items():
        for sat in SATURACIONES:
            h = lambda f: min(1.0, sum(w * f[k] for k, w in capas.items()) / sat)
            hp = [h(f) for f in pres]
            filas.append({"nombre": nombre, "capas": capas, "saturacion": sat,
                          "auc": gv.auc(hp, [h(f) for f in otras]),
                          "pct_sin_habitat": round(100 * sum(x < 0.05 for x in hp) / len(hp), 1)})
    # por cada definición, la saturación: mayor AUC salvo ganancia < 0,01 → la que oculta menos
    elegidas = []
    for nombre in ALTERNATIVAS:
        fs = sorted([f for f in filas if f["nombre"] == nombre], key=lambda f: -f["auc"])
        mejor = fs[0]
        for f in fs[1:]:
            if mejor["auc"] - f["auc"] < 0.01 and f["pct_sin_habitat"] < mejor["pct_sin_habitat"]:
                mejor = f
        elegidas.append(mejor)
    mejor = max(elegidas, key=lambda f: f["auc"])
    medias = {k: sum(f[k] for f in pres) / len(pres) for k in ("conifera", "frondosa", "pradera")}
    medias_o = {k: sum(f[k] for f in otras) / len(otras) for k in ("conifera", "frondosa", "pradera")}
    enriq = {k: round(medias[k] / medias_o[k], 2) for k in medias}
    if mejor["auc"] < UMBRAL_SIN_FILTRO:
        return {"capas": {}, "saturacion": 1.0, "auc": mejor["auc"], "pct_sin_habitat": 0.0,
                "texto": "Sin preferencia clara de hábitat en los hallazgos (AUC < 0,55): no se filtra por hábitat.",
                "enriquecimiento": enriq}
    detalle = ", ".join(f"{k} ×{v}".replace(".", ",") for k, v in enriq.items())
    return {"capas": mejor["capas"], "saturacion": mejor["saturacion"], "auc": mejor["auc"],
            "pct_sin_habitat": mejor["pct_sin_habitat"],
            "texto": f"{mejor['nombre'].capitalize()}, según sus hallazgos (frente a otras setas: {detalle}).",
            "enriquecimiento": enriq}


def main(hrl_dir: Path, cache: Path):
    regs = gv.deduplicar(descargar(cache))
    capas = gv.Capas(hrl_dir)
    precisos = [r for r in regs if r["coordinateUncertaintyInMeters"] is not None
                and r["coordinateUncertaintyInMeters"] <= 1000]
    for r in precisos:
        r["_f"] = capas.fracciones(r["decimalLatitude"], r["decimalLongitude"])
    precisos = [r for r in precisos if r["_f"]]
    out = {"generado": date.today().isoformat(), "registros": len(regs), "registros_habitat": len(precisos),
           "especies": {}}
    for sp in NUEVAS:
        fen, n = temporada([r for r in regs if r["especie"] == sp])
        pres = [r["_f"] for r in precisos if r["especie"] == sp]
        otras = [r["_f"] for r in precisos if r["especie"] != sp]
        hab = habitat(sp, pres, otras)
        out["especies"][sp] = {
            "fenologia": fen,
            "habitat": {k: hab[k] for k in ("capas", "saturacion", "texto")},
            "validacion": {"habitat": {"auc": hab["auc"], "n": len(pres), "pct_sin_habitat": hab["pct_sin_habitat"],
                                       "enriquecimiento": hab["enriquecimiento"]},
                           "temporada": {"n": n}},
        }
        print(f"{sp:28s} n={n:4d} hábitat n={len(pres):3d} AUC {hab['auc']:.3f} {hab['capas'] or 'sin filtro'} "
              f"sat {hab['saturacion']} | temporada {fen}", flush=True)
    (RAIZ / "app" / "perfiles_gbif.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("escrito app/perfiles_gbif.json")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
