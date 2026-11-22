"""Modelo de favorabilidad: forma de las funciones y comportamiento ante casos conocidos."""
from datetime import date, timedelta

import pytest

from app import modelo


def serie(dias=45, prec=0.0, tmed=10.0, tmin=5.0, tmax=15.0, suelo=0.25, et0=1.0, fin=date(2024, 10, 27)):
    """Serie diaria sintética que termina en `fin` (ayer respecto a `hoy`)."""
    return [{"fecha": (fin - timedelta(days=dias - 1 - i)).isoformat(), "prec": prec, "tmed": tmed, "tmin": tmin,
             "tmax": tmax, "suelo_0_7": suelo, "suelo_7_28": suelo, "et0": et0} for i in range(dias)]


def test_trapecio():
    assert modelo.trapecio(None, 0, 1, 2, 3) == 0.0
    assert modelo.trapecio(1.5, 0, 1, 2, 3) == 1.0
    assert modelo.trapecio(0.5, 0, 1, 2, 3) == pytest.approx(0.5)
    assert modelo.trapecio(2.5, 0, 1, 2, 3) == pytest.approx(0.5)
    assert modelo.trapecio(5, 0, 1, 2, 3) == 0.0


def test_fenologia_en_rango_y_maximo_en_temporada():
    for perfil in modelo.ESPECIES.values():
        for m in range(1, 13):
            assert 0.0 <= modelo.fenologia(perfil, date(2025, m, 15)) <= 1.0
    # Níscalo: máximo real en noviembre (calibrado con GBIF); julio fuera de temporada
    nisc = modelo.ESPECIES["lactarius_deliciosus"]
    assert modelo.fenologia(nisc, date(2025, 11, 15)) == 1.0
    assert modelo.fenologia(nisc, date(2025, 7, 15)) == 0.0


def test_indice_entre_0_y_100_para_todas_las_especies():
    for prec in (0.0, 2.0, 10.0):
        r = modelo.puntuar_todas(serie(prec=prec), date(2024, 10, 28))
        for sp, e in r["especies"].items():
            assert 0 <= e["indice"] <= 100, sp
            assert e["limitante"] in e["factores"]


def test_mas_lluvia_no_empeora_el_indice():
    hoy = date(2024, 10, 28)
    seco = modelo.puntuar_todas(serie(prec=0.0, suelo=0.08, et0=2.0), hoy)["especies"]
    humedo = modelo.puntuar_todas(serie(prec=4.0, suelo=0.30, et0=1.0), hoy)["especies"]
    for sp in modelo.ESPECIES:
        assert humedo[sp]["indice"] >= seco[sp]["indice"], sp
    assert seco["lactarius_deliciosus"]["limitante"] == "agua"


def test_heladas_penalizan_al_boleto():
    hoy = date(2024, 10, 28)
    sin = modelo.puntuar_todas(serie(prec=3.0, tmin=4.0), hoy)["especies"]["boletus_edulis"]
    con = modelo.puntuar_todas(serie(prec=3.0, tmin=-4.0), hoy)["especies"]["boletus_edulis"]
    assert con["factores"]["heladas"] < sin["factores"]["heladas"]
    assert con["indice"] <= sin["indice"]


def test_ventana_de_lluvia_con_retardo():
    # Lluvia solo el último día: no cuenta para el níscalo (ventana 5-30 días)
    v = serie(prec=0.0)
    v[-1]["prec"] = 80.0
    ind = modelo.indicadores(v)
    assert ind["prec"](5, 30) == 0.0
    assert ind["prec"](1, 7) == 80.0


def test_habitat():
    assert modelo.habitat("lactarius_deliciosus", {"conifera": 0.0}) == 0.0
    assert modelo.habitat("lactarius_deliciosus", {"conifera": 0.9}) == 1.0
    assert 0 < modelo.habitat("boletus_edulis", {"frondosa": 0.1, "conifera": 0.1}) < 1
    for sp in modelo.ESPECIES:
        assert sp in modelo.HABITAT


def test_catalogo_coherente():
    c = modelo.catalogo()
    assert {e["id"] for e in c["especies"]} == set(modelo.ESPECIES)
    for e in c["especies"]:
        for f in e["fuentes"]:
            assert f in c["fuentes"], f
    for f in c["fuentes_generales"] + c["fuentes_habitat"] + c["fuentes_validacion"]:
        assert f in c["fuentes"], f


def test_especies_ampliadas_completas():
    from app.catalogo_especies import CONFUSIONES, NUEVAS
    assert len(modelo.ESPECIES) == 31
    for sp in modelo.ESPECIES:
        p = modelo.ESPECIES[sp]
        assert p["fenologia"] and max(p["fenologia"].values()) == 1.0, sp   # temporada normalizada
        assert sp in modelo.HABITAT and sp in CONFUSIONES, sp
        assert modelo.validacion_especie(sp) is not None, sp
    for sp in NUEVAS:
        assert modelo.validacion_especie(sp)["clima"]["nivel"] == "sin evaluar"
    assert "tricholoma_equestre" not in modelo.ESPECIES        # tóxica: excluida a propósito


def test_habitat_sin_filtro_y_temporadas_de_primavera():
    from datetime import date
    assert modelo.habitat("macrolepiota_procera", {"conifera": 0, "frondosa": 0, "pradera": 0}) == 1.0
    assert modelo.fenologia(modelo.ESPECIES["morchella_esculenta"], date(2026, 4, 15)) == 1.0
    assert modelo.fenologia(modelo.ESPECIES["morchella_esculenta"], date(2026, 11, 15)) == 0.0
    assert modelo.fenologia(modelo.ESPECIES["hygrophorus_marzuolus"], date(2026, 3, 15)) == 1.0
