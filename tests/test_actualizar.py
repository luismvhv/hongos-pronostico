"""Cálculo por lotes (scripts/actualizar.py) sin red: AEMET en bloque, resumen y coste Open-Meteo."""
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import actualizar  # noqa: E402

from app import aemet, mapa, modelo, openmeteo  # noqa: E402


def test_aemet_en_bloque_agrupa_cyl_y_trocea_en_15_dias(monkeypatch):
    llamadas = []

    async def falso(ini, fin):
        llamadas.append((ini, fin))
        assert (fin - ini).days < actualizar.BLOQUE_AEMET
        if fin >= date.today() - timedelta(days=3):
            raise aemet.SinDatos("aún sin publicar")
        return [{"indicativo": "2331", "provincia": "BURGOS", "fecha": ini.isoformat(), "prec": 1.0},
                {"indicativo": "3195", "provincia": "MADRID", "fecha": ini.isoformat(), "prec": 0.0}]

    monkeypatch.setenv("AEMET_API_KEY", "x")
    monkeypatch.setattr(aemet, "daily_all", falso)
    series, info = asyncio.run(actualizar.aemet_en_bloque(60))
    assert info["peticiones"] == len(llamadas) == 4
    assert set(series) == {"2331"}                 # Madrid se descarta
    assert info["ok"] and info["errores"] == []    # un bloque sin publicar no es un error


def test_aemet_sin_clave(monkeypatch):
    monkeypatch.delenv("AEMET_API_KEY", raising=False)
    series, info = asyncio.run(actualizar.aemet_en_bloque(60))
    assert series is None and not info["ok"]


def test_resumen_provincia():
    celdas = []
    for lat, lon in mapa.malla("SEGOVIA"):
        celdas.append({"lat": lat, "lon": lon, "confianza": "alta",
                       "especies": {sp: {"indice": 40} for sp in modelo.ESPECIES}})
    r = actualizar.resumen_provincia({"celdas": celdas}, "SEGOVIA")
    nisc = r["especies"]["lactarius_deliciosus"]
    assert r["celdas"] == 74 and r["confianza"]["alta"] == 74
    assert nisc["clima_medio"] == 40
    assert 0 < nisc["con_habitat_medio"] <= 40     # clima × hábitat, solo donde hay hábitat
    assert 0 < nisc["pct_superficie_con_habitat"] < 100


def test_coste_open_meteo():
    p = {"latitude": ",".join(["41"] * 10), "start_date": "2026-10-01", "end_date": "2026-10-14", "daily": "a,b"}
    assert openmeteo.coste(p) == 10                # 10 puntos, 14 días, < 10 variables
    p["end_date"] = "2026-10-28"
    assert openmeteo.coste(p) == 20                # 28 días cuentan doble
