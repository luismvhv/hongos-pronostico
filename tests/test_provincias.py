"""Las 9 provincias de Castilla y León: contornos, mallas y normalización de nombres."""
import json

import pytest

from app import mapa, provincias

# Celdas de 0,1° con el centro dentro del contorno (medido el 21-nov-2026)
CELDAS = {"AVILA": 83, "BURGOS": 159, "LEON": 172, "PALENCIA": 88, "SALAMANCA": 130,
          "SEGOVIA": 74, "SORIA": 107, "VALLADOLID": 90, "ZAMORA": 116}


@pytest.mark.parametrize("clave", list(provincias.PROVINCIAS))
def test_contorno_y_malla(clave):
    g = json.loads(provincias.contorno(clave).read_text())
    assert g["features"][0]["properties"]["clave"] == clave
    assert len(mapa.malla(clave)) == CELDAS[clave]


def test_contorno_conjunto():
    g = json.loads((provincias.STATIC / "provincias" / "CYL.geojson").read_text())
    assert {f["properties"]["clave"] for f in g["features"]} == set(provincias.PROVINCIAS)


def test_normalizar():
    assert provincias.normalizar("León") == "LEON"
    assert provincias.normalizar(" ávila ") == "AVILA"
    assert provincias.normalizar("Madrid") is None
    assert provincias.normalizar("") is None


def test_listado_marca_habitat_disponible():
    l = {p["clave"]: p for p in provincias.listado()}
    assert l["BURGOS"]["habitat"] is True
