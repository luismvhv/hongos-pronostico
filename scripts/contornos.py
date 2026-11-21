"""Genera static/provincias/<CLAVE>.geojson y CYL.geojson desde el paquete npm es-atlas (IGN, MIT).

Se ejecuta a mano. Requiere Node y es-atlas + topojson-client:
  mkdir -p /tmp/esatlas && cd /tmp/esatlas && npm pack es-atlas && tar xzf es-atlas-*.tgz \\
    && npm i topojson-client@3.1.0
  python scripts/contornos.py /tmp/esatlas
Coordenadas redondeadas a 4 decimales (~10 m), suficiente para la malla de 0,02°.
"""
import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from app.provincias import PROVINCIAS, STATIC  # noqa: E402

JS = """
const topo = require(process.argv[1] + '/node_modules/topojson-client');
const t = JSON.parse(require('fs').readFileSync(process.argv[1] + '/package/es/municipalities.json'));
process.stdout.write(JSON.stringify(topo.feature(t, t.objects.provinces)));
"""


def redondear(x):
    return [redondear(i) for i in x] if isinstance(x[0], list) else [round(x[0], 4), round(x[1], 4)]


def main(esatlas: str):
    fc = json.loads(subprocess.run(["node", "-e", JS, esatlas], capture_output=True, check=True, text=True).stdout)
    por_ine = {f["id"]: f for f in fc["features"]}
    destino = STATIC / "provincias"
    destino.mkdir(exist_ok=True)
    todas = []
    for clave, p in PROVINCIAS.items():
        f = por_ine[p["ine"]]
        feat = {"type": "Feature",
                "properties": {"clave": clave, "nombre": p["nombre"], "ine": p["ine"], "fuente": "IGN vía es-atlas (MIT)"},
                "geometry": {**f["geometry"], "coordinates": redondear(f["geometry"]["coordinates"])}}
        (destino / f"{clave}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [feat]},
                                                             separators=(",", ":")))
        todas.append(feat)
    (destino / "CYL.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": todas}, separators=(",", ":")))
    print(f"{len(todas)} provincias -> {destino}")


if __name__ == "__main__":
    main(sys.argv[1])
