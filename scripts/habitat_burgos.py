"""Precalcula la capa de hábitat de Burgos a partir de Copernicus (se ejecuta a mano, no en Render).

Salida: static/habitat_burgos.json — submalla de 0,02° (≈ 1,7 × 2,2 km) dentro del contorno
provincial, con, por subcelda:
  conifera, frondosa : fracción de la superficie con bosque de coníferas / frondosas
                       (Copernicus HRL Forest Type 2018, 10 m; bosque = cubierta arbórea ≥ 10 %)
  pradera            : fracción de pradera (Copernicus HRL Grassland 2018, 10 m)
  densidad           : densidad media de copas dentro del bosque, % (HRL Tree Cover Density 2018)
  altitud, pendiente : media en m y grados (Copernicus DEM GLO-90)
  umbria             : fracción de laderas orientadas al norte (aspecto 315-45°, pendiente > 5°)

Fuentes y acceso (comprobado nov-2026):
- HRL: ImageServer público de la EEA, sin autenticación, exportImage remuestreado a 0,001°
  (~100 m) por vecino más próximo:
  https://image.discomap.eea.europa.eu/arcgis/rest/services/GioLandPublic/<capa>/ImageServer
- DEM: COG públicos en AWS, https://copernicus-dem-90m.s3.amazonaws.com
Ambos con licencia libre de Copernicus (atribución).

Uso (dependencias solo de desarrollo, no van a requirements.txt):
  python -m venv /tmp/venv && /tmp/venv/bin/pip install rasterio numpy
  /tmp/venv/bin/python scripts/habitat_burgos.py --cache /tmp/copernicus
"""
import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from app.mapa import _dentro, _poligonos  # noqa: E402  (mismo contorno y test que el mapa)

BBOX = (-4.36, 41.44, -2.50, 43.21)   # lon_min, lat_min, lon_max, lat_max (contorno IGN + margen)
RES = 0.001                           # grados por píxel en la descarga HRL
PASO = 0.02                           # submalla de hábitat
HRL = "https://image.discomap.eea.europa.eu/arcgis/rest/services/GioLandPublic/{}/ImageServer/exportImage"
CAPAS = {"tipo": "HRL_ForestType_2018", "densidad": "HRL_TreeCoverDensity_2018", "pradera": "HRL_Grassland_2018"}
DEM = "https://copernicus-dem-90m.s3.amazonaws.com/{n}/{n}.tif"


def descargar(url: str, destino: Path) -> Path:
    if not destino.exists():
        print("descargando", url[:110])
        with urllib.request.urlopen(url, timeout=600) as r:
            destino.write_bytes(r.read())
    return destino


def hrl(nombre: str, cache: Path) -> np.ndarray:
    w = round((BBOX[2] - BBOX[0]) / RES)
    h = round((BBOX[3] - BBOX[1]) / RES)
    url = (HRL.format(nombre) + f"?bbox={BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]}&bboxSR=4326&imageSR=4326"
           f"&size={w},{h}&format=tiff&pixelType=U8&interpolation=RSP_NearestNeighbor&f=image")
    with rasterio.open(descargar(url, cache / f"{nombre}.tif")) as r:
        assert abs(r.transform[0] - RES) < 1e-9 and abs(r.bounds.left - BBOX[0]) < 1e-6, "rejilla inesperada"
        return r.read(1)


def dem(cache: Path):
    rutas = []
    for la in range(math.floor(BBOX[1]), math.floor(BBOX[3]) + 1):
        for lo in range(math.floor(BBOX[0]), math.floor(BBOX[2]) + 1):
            n = f"Copernicus_DSM_COG_30_N{la:02d}_00_W{abs(lo):03d}_00_DEM"
            rutas.append(descargar(DEM.format(n=n), cache / f"{n}.tif"))
    fuentes = [rasterio.open(p) for p in rutas]
    z, t = merge(fuentes, bounds=BBOX)
    for f in fuentes:
        f.close()
    z = z[0].astype("float32")
    # Pendiente y orientación en coordenadas geográficas (paso en metros según la latitud)
    lat_c = (BBOX[1] + BBOX[3]) / 2
    dx = t[0] * 111320 * math.cos(math.radians(lat_c))
    dy = -t[4] * 110574
    gy, gx = np.gradient(z, dy, dx)          # filas hacia el sur, columnas hacia el este
    pendiente = np.degrees(np.arctan(np.hypot(gx, gy)))
    # Aspecto: dirección hacia la que mira la ladera (0 = norte). Cuesta abajo = −gradiente.
    aspecto = (np.degrees(np.arctan2(-gx, gy)) + 360) % 360
    return z, pendiente, aspecto, t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=Path("/tmp/copernicus"))
    args = ap.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)

    tipo = hrl(CAPAS["tipo"], args.cache)          # 0 no bosque, 1 frondosas, 2 coníferas
    dens = hrl(CAPAS["densidad"], args.cache)      # 0-100 %
    prad = hrl(CAPAS["pradera"], args.cache)       # 0/1
    z, pend, asp, t = dem(args.cache)

    anillos = _poligonos("BURGOS")
    celdas = []
    lat = BBOX[1] + PASO / 2
    while lat < BBOX[3]:
        lon = BBOX[0] + PASO / 2
        while lon < BBOX[2]:
            if any(_dentro(lon, lat, a) for a in anillos):
                # ventana HRL (fila 0 = norte)
                c0 = int(round((lon - PASO / 2 - BBOX[0]) / RES)); c1 = c0 + int(round(PASO / RES))
                f0 = int(round((BBOX[3] - (lat + PASO / 2)) / RES)); f1 = f0 + int(round(PASO / RES))
                tp, de, pr = tipo[f0:f1, c0:c1], dens[f0:f1, c0:c1], prad[f0:f1, c0:c1]
                n = tp.size
                bosque = tp > 0
                # ventana DEM
                dc0 = int((lon - PASO / 2 - t[2]) / t[0]); dc1 = int((lon + PASO / 2 - t[2]) / t[0])
                df0 = int((t[5] - (lat + PASO / 2)) / -t[4]); df1 = int((t[5] - (lat - PASO / 2)) / -t[4])
                zz, pp, aa = z[df0:df1, dc0:dc1], pend[df0:df1, dc0:dc1], asp[df0:df1, dc0:dc1]
                norte = ((aa >= 315) | (aa <= 45)) & (pp > 5)
                celdas.append([
                    round(lat, 3), round(lon, 3),
                    round(float((tp == 2).sum()) / n, 3),
                    round(float((tp == 1).sum()) / n, 3),
                    round(float((pr == 1).sum()) / n, 3),
                    round(float(de[bosque].mean())) if bosque.any() else 0,
                    round(float(zz.mean())),
                    round(float(pp.mean()), 1),
                    round(float(norte.mean()), 3),
                ])
            lon += PASO
        lat += PASO

    salida = {
        "provincia": "BURGOS", "paso_grados": PASO,
        "campos": ["lat", "lon", "conifera", "frondosa", "pradera", "densidad", "altitud", "pendiente", "umbria"],
        "celdas": celdas,
        "fuentes": [
            "Copernicus Land Monitoring Service: HRL Forest Type 2018, Tree Cover Density 2018, Grassland 2018 (EEA)",
            "Copernicus DEM GLO-90 (ESA / Airbus), vía AWS Open Data",
        ],
    }
    destino = RAIZ / "static" / "habitat_burgos.json"
    destino.write_text(json.dumps(salida, separators=(",", ":")))
    tot = np.array([c[2:5] for c in celdas])
    print(f"{len(celdas)} subceldas -> {destino} ({destino.stat().st_size // 1024} KB); "
          f"medias conífera {tot[:, 0].mean():.3f}, frondosa {tot[:, 1].mean():.3f}, pradera {tot[:, 2].mean():.3f}")


if __name__ == "__main__":
    main()
