"""Descarga registros de GBIF de las especies del modelo (se ejecuta a mano, no en Render).

Región: "Castilla y León ampliada" (lat 40-43,3, lon −7,1 a −1,7), España, años 2000-2026,
con coordenadas y sin problemas geoespaciales marcados por GBIF.
Salida: JSON con un registro por fila y los campos necesarios para validar
(coordenadas, incertidumbre, fecha, origen, licencia).

API pública sin clave: https://api.gbif.org/v1/occurrence/search (máx. 300 por página).
Cita obligatoria: cada registro conserva su `datasetKey` y licencia (CC0, CC BY o CC BY-NC).

Uso: python scripts/gbif_descarga.py /ruta/salida.json
"""
import json
import sys
import time
import urllib.parse
import urllib.request

ESPECIES = {  # id del modelo -> taxonKey de GBIF (comprobado con /species/match, nov-2026)
    "lactarius_deliciosus": 5248629,
    "boletus_edulis": 5954958,
    "amanita_caesarea": 5240269,
    "pleurotus_eryngii": 9075265,
    "tricholoma_terreum": 5241808,
    "cantharellus_lutescens": 8871787,  # sinónimo; GBIF lo resuelve a su nombre aceptado
    "marasmius_oreades": 2537250,
}
FILTROS = {
    "country": "ES", "hasCoordinate": "true", "hasGeospatialIssue": "false",
    "decimalLatitude": "40,43.3", "decimalLongitude": "-7.1,-1.7", "year": "2000,2026",
}
CAMPOS = ["key", "decimalLatitude", "decimalLongitude", "coordinateUncertaintyInMeters", "eventDate",
          "year", "month", "day", "basisOfRecord", "datasetKey", "datasetName", "institutionCode",
          "license", "issues", "occurrenceStatus"]


def pedir(params):
    url = "https://api.gbif.org/v1/occurrence/search?" + urllib.parse.urlencode(params)
    for i in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except Exception:
            time.sleep(2 ** i)
    raise RuntimeError("GBIF no responde: " + url)


def main(salida):
    filas = []
    for sp, key in ESPECIES.items():
        offset, n = 0, 0
        while True:
            d = pedir({**FILTROS, "taxonKey": key, "limit": 300, "offset": offset})
            for r in d["results"]:
                if r.get("occurrenceStatus", "PRESENT") != "PRESENT":
                    continue  # registros de ausencia
                filas.append({"especie": sp, **{c: r.get(c) for c in CAMPOS}})
                n += 1
            offset += 300
            if d.get("endOfRecords") or offset >= d["count"]:
                break
        print(f"{sp}: {n} registros")
    with open(salida, "w") as f:
        json.dump(filas, f)
    print(f"total {len(filas)} -> {salida}")


if __name__ == "__main__":
    main(sys.argv[1])
