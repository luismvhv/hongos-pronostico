"""Malla, fusión AEMET + Open-Meteo, validación y agregación de la lluvia 07-07 UTC (sin red)."""
from datetime import date

import pytest

from app import comparar, mapa, openmeteo, validacion


def test_malla_burgos_estable():
    celdas = mapa.malla("BURGOS")
    assert len(celdas) == 159
    for lat, lon in celdas:
        assert 41.4 < lat < 43.3 and -4.4 < lon < -2.4


def test_dentro_de_un_cuadrado():
    cuadrado = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    assert mapa._dentro(0.5, 0.5, cuadrado)
    assert not mapa._dentro(1.5, 0.5, cuadrado)


def test_huecos_de_los_poligonos():
    exterior = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]
    hueco = [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]
    assert mapa.dentro_provincia(3, 3, [[exterior, hueco]])
    assert not mapa.dentro_provincia(1.5, 1.5, [[exterior, hueco]])   # enclave de otra provincia


def test_confianza_segun_distancia():
    est = {"confianza": "alta"}
    assert mapa._confianza(est, 10) == "alta"
    assert mapa._confianza(est, 25) == "media"
    assert mapa._confianza(est, 40) == "baja"
    assert mapa._confianza(None, None) == "baja"


def test_fusion_corrige_sesgo_y_mezcla_lluvia():
    om = [{"fecha": "2026-11-01", "tmin": 2.0, "tmax": 10.0, "tmed": 6.0, "prec": 10.0}]
    est = {"temperatura": {"tmin": {"sesgo": 1.0}, "tmax": {"sesgo": -2.0}, "tmed": {"sesgo": 0.0}},
           "aemet": [{"fecha": "2026-11-01", "prec": 0.0}]}
    r = mapa.fusionar(om, est, 1.0)[0]
    assert r["tmin"] == 1.0 and r["tmax"] == 12.0      # se resta el sesgo de Open-Meteo
    assert r["prec"] == 0.0                           # junto a la estación manda AEMET
    assert mapa.fusionar(om, est, 0.0) == om          # lejos, Open-Meteo sin tocar


def test_lluvia_07a07_utc():
    # 1 mm cada hora el 1-nov; la ventana del 1-nov va de 07 UTC del 1 a 06 UTC del 2
    serie = {f"2026-11-01T{h:02d}:00": 1.0 for h in range(24)}
    serie.update({f"2026-11-02T{h:02d}:00": 0.0 for h in range(24)})
    r = openmeteo.sumar_07a07(serie, date(2026, 11, 1), date(2026, 11, 1))
    assert r["2026-11-01"] == 17.0                    # horas 07-23 del día 1
    r2 = openmeteo.sumar_07a07(serie, date(2026, 11, 2), date(2026, 11, 2))
    assert r2["2026-11-02"] is None                   # faltan horas del día 3


def test_metricas_de_validacion():
    aemet = [{"fecha": f"2026-10-{d:02d}", "tmax": 15.0, "tmin": 5.0, "tmed": 10.0, "prec": 5.0 if d % 3 == 0 else 0.0}
             for d in range(1, 31)]
    om = [{"fecha": a["fecha"], "tmax": 14.0, "tmin": 6.0, "tmed": 10.0} for a in aemet]
    prec = {a["fecha"]: a["prec"] for a in aemet}
    m = validacion.metricas(aemet, om, prec)
    assert m["temperatura"]["tmax"]["sesgo"] == -1.0
    assert m["lluvia"]["acierto"] == 1.0
    assert m["confianza"] == "alta"


def test_resumen_con_cobertura():
    r = comparar.resumir([{"fecha": "2026-11-01", "prec": 2.0, "tmin": -1.0, "tmed": 4.0, "sol": None}], 10)
    assert r["cobertura_prec"] == pytest.approx(0.1)
    assert r["heladas"] == 1
    assert r["aviso"]
