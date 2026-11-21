"""Peculiaridades de AEMET ya resueltas (NOTAS §4): que no vuelvan a romperse."""
from app.aemet import _dms_to_decimal, _to_float


def test_coordenadas_ddmmss_en_latitud_y_longitud():
    # Burgos Aeropuerto: 422125N / 033713W (la longitud también es DDMMSS, no DDDMMSS)
    assert abs(_dms_to_decimal("422125N") - 42.3569) < 1e-3
    assert abs(_dms_to_decimal("033713W") - (-3.6203)) < 1e-3


def test_coordenadas_invalidas():
    assert _dms_to_decimal(None) is None
    assert _dms_to_decimal("") is None
    assert _dms_to_decimal("xxN") is None


def test_numeros_con_coma_e_inapreciable():
    assert _to_float("12,5") == 12.5
    assert _to_float("Ip") == 0.0          # precipitación inapreciable
    assert _to_float("") is None
    assert _to_float(None) is None
    assert _to_float("Acum") is None       # textos no numéricos
    assert _to_float(3) == 3.0
