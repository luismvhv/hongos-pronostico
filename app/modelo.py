"""Modelo de favorabilidad climática v0 por especie (0-100).

NO es una probabilidad calibrada: es un índice de lo favorable que ha sido el tiempo reciente
para que una especie fructifique. No sabe si en la celda hay bosque, el árbol huésped
o el suelo adecuados (eso es la Fase 2). Ver NOTAS.md §5b para la revisión bibliográfica.

Estructura (factores limitantes, multiplicativos):
    índice = 100 · fenología · agua · temperatura · heladas · [golpe de calor]
cada factor en [0, 1].

Respaldado por la literatura (ver NOTAS §5b):
- La lluvia de finales de verano y otoño es el principal motor de la producción
  (Alday et al. 2017 Fungal Ecol.; Taye et al. 2016 Fungal Ecol.; Martínez de Aragón et al. 2007).
- Efecto retardado de la lluvia: ~1 mes a escala mensual (Karavani et al. 2018 Agric. For. Meteorol.);
  ventana óptima de 26 días para B. edulis (preprint bioRxiv 2025, sin revisión por pares).
- El balance hídrico (lluvia − evapotranspiración) explica mejor que la lluvia sola
  (Ágreda et al. 2015 Glob. Change Biol.; Martínez de Aragón et al. 2007, citado en segunda mano).
- La humedad del suelo del mismo mes importa (Karavani et al. 2018).
- B. edulis: máximo con temperatura media ≈ 13 °C en los 20 días previos (bioRxiv 2025);
  subidas bruscas de tmax lo inhiben (Salerni et al. 2023, Ital. J. Mycol.).
- Temperaturas altas acortan la temporada de micorrícicos (Pinar Grande, Soria, 29 años).

SUPUESTOS (no respaldados con números en la literatura revisada; a calibrar en Fase 3):
- Umbrales exactos de lluvia (salvo los ~50 l/m² del níscalo, que vienen de partes de Micocyl),
  de humedad del suelo y de balance hídrico.
- Pesos de los subfactores de agua (0,5 / 0,25 / 0,25).
- Rangos térmicos de todas las especies salvo B. edulis y el níscalo.
- Penalización por heladas y ventanas fenológicas (orientativas, de partes regionales).
"""
import json
import math
from datetime import date, timedelta
from pathlib import Path

# --- Perfiles por especie ---------------------------------------------------------------
# fenologia: peso por mes (1-12); se interpola entre meses. CALIBRADO con GBIF (nov-2026): reparto
#   mensual real de 68-522 hallazgos por especie en Castilla y León ampliada, 2000-2026, normalizado
#   al mes máximo; meses con < 2 % de hallazgos a 0 (scripts/gbif_validacion.py, NOTAS §5g).
#   Sesgo: hay más observadores en otoño, lo que exagera algo los meses otoñales.
# lluvia: ventana con retardo [lag_ini, lag_fin] días antes de hoy y mm "objetivo" (f≈0,9).
# temp: trapecio (a, b, c, d) sobre la temperatura media de los últimos `dias_t` días.
# helada: penalización por día con tmin ≤ 0 °C (leve) y ≤ −3 °C (fuerte) en los últimos 10 días.
ESPECIES = {
    "lactarius_deliciosus": {
        "nombre": "Níscalo (Lactarius deliciosus)",
        "grupo": "micorrícico (pino)",
        "fenologia": {1: 0.06, 9: 0.08, 10: 0.77, 11: 1.0, 12: 0.52},
        "lluvia": {"lag_ini": 5, "lag_fin": 30, "objetivo_mm": 50},
        "temp": (3, 8, 14, 20), "dias_t": 20,
        "helada": {"leve": 0.10, "fuerte": 0.25},
        "fuentes": "Micocyl (partes 2021, 2024): >50 l/m² dispara nuevos níscalos; máximas 12-20 °C y "
                   "mínimas > 5 °C ideales. Taye et al. 2016: la lluvia otoñal es el principal predictor.",
    },
    "boletus_edulis": {
        "nombre": "Boleto (Boletus edulis)",
        "grupo": "micorrícico (pino, haya, roble)",
        "fenologia": {6: 0.04, 7: 0.04, 9: 0.35, 10: 1.0, 11: 0.49, 12: 0.06},
        "lluvia": {"lag_ini": 5, "lag_fin": 26, "objetivo_mm": 50},
        "temp": (7, 11, 16, 21), "dias_t": 20,
        "helada": {"leve": 0.25, "fuerte": 0.50},
        "calor": True,
        "fuentes": "bioRxiv 2025 (10 años): óptimo ≈ 13 °C de media en 20 días y lluvia en 26 días. "
                   "Salerni et al. 2023: subidas bruscas de tmax lo inhiben. Termófilo; se corta con heladas.",
    },
    "amanita_caesarea": {
        "nombre": "Oronja (Amanita caesarea)",
        "grupo": "micorrícico (quercíneas, castaño)",
        "fenologia": {6: 0.33, 7: 0.21, 8: 0.08, 9: 1.0, 10: 0.93, 11: 0.21},
        "lluvia": {"lag_ini": 5, "lag_fin": 26, "objetivo_mm": 40},
        "temp": (12, 16, 22, 27), "dias_t": 20,
        "helada": {"leve": 0.40, "fuerte": 0.80},
        "fuentes": "Termófila (fuentes divulgativas). Sin estudio cuantitativo encontrado: rangos SUPUESTOS.",
    },
    "pleurotus_eryngii": {
        "nombre": "Seta de cardo (Pleurotus eryngii)",
        "grupo": "saprótrofo/parásito débil (raíces de Eryngium)",
        "fenologia": {3: 0.07, 4: 0.23, 5: 0.32, 6: 0.06, 9: 0.12, 10: 0.57, 11: 1.0, 12: 0.32},
        "lluvia": {"lag_ini": 3, "lag_fin": 21, "objetivo_mm": 35},
        "temp": (5, 9, 16, 22), "dias_t": 14,
        "helada": {"leve": 0.10, "fuerte": 0.25},
        "fuentes": "Aparece 2-3 semanas tras lluvias importantes (divulgación); citada en Burgos y Soria "
                   "en partes de Micocyl (oct-2024). Rangos térmicos SUPUESTOS.",
    },
    "tricholoma_terreum": {
        "nombre": "Negrilla (Tricholoma terreum)",
        "grupo": "micorrícico (pino)",
        "fenologia": {1: 0.18, 10: 0.45, 11: 1.0, 12: 0.57},
        "lluvia": {"lag_ini": 5, "lag_fin": 30, "objetivo_mm": 40},
        "temp": (1, 5, 11, 16), "dias_t": 20,
        "helada": {"leve": 0.03, "fuerte": 0.10},
        "fuentes": "Especie tardía y tolerante al frío (Micocyl oct-2024: especies tardías aparecen cuando "
                   "el níscalo ya fructifica). Umbrales SUPUESTOS.",
    },
    "cantharellus_lutescens": {
        "nombre": "Angula de monte (Cantharellus lutescens)",
        "grupo": "micorrícico (pino)",
        "fenologia": {1: 0.21, 2: 0.12, 8: 0.12, 9: 0.21, 10: 0.58, 11: 1.0, 12: 0.5},
        "lluvia": {"lag_ini": 5, "lag_fin": 30, "objetivo_mm": 45},
        "temp": (1, 5, 11, 16), "dias_t": 20,
        "helada": {"leve": 0.05, "fuerte": 0.15},
        "fuentes": "Fructifica de finales de otoño a principios de invierno en coníferas (enciclopedias "
                   "micológicas). Pariente C. tubaeformis deja de crecer tras la primera helada fuerte. "
                   "Umbrales SUPUESTOS.",
    },
    "marasmius_oreades": {
        "nombre": "Senderuela (Marasmius oreades)",
        "grupo": "saprótrofo de pradera",
        "fenologia": {4: 0.35, 5: 0.71, 6: 0.22, 9: 0.24, 10: 0.57, 11: 1.0, 12: 0.16},
        "lluvia": {"lag_ini": 2, "lag_fin": 14, "objetivo_mm": 25},
        "temp": (7, 11, 20, 25), "dias_t": 14,
        "helada": {"leve": 0.15, "fuerte": 0.35},
        "fuentes": "Saprótrofo de pastos, reacciona rápido a la lluvia. Sin estudio cuantitativo de "
                   "fructificación encontrado: todo SUPUESTO.",
    },
}

PESOS_AGUA = {"lluvia": 0.5, "suelo": 0.25, "balance": 0.25}  # SUPUESTO


def trapecio(x: float, a: float, b: float, c: float, d: float) -> float:
    if x is None:
        return 0.0
    if x <= a or x >= d:
        return 0.0
    if b <= x <= c:
        return 1.0
    return (x - a) / (b - a) if x < b else (d - x) / (d - c)


def fenologia(perfil: dict, dia: date) -> float:
    """Peso del mes, interpolado linealmente hacia el mes vecino según el día."""
    pesos = perfil["fenologia"]
    m = dia.month
    actual = pesos.get(m, 0.0)
    if dia.day >= 15:
        vecino = pesos.get(m % 12 + 1, 0.0)
        t = (dia.day - 15) / 30
    else:
        vecino = pesos.get((m - 2) % 12 + 1, 0.0)
        t = (15 - dia.day) / 30
    return round(actual * (1 - t) + vecino * t, 3)


def _media(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def indicadores(valores: list[dict]) -> dict:
    """Indicadores comunes a todas las especies a partir de la serie diaria (la última fila = ayer)."""
    v = valores
    n = len(v)

    def ventana(desde_atras: int, hasta_atras: int, k: str):
        # días [hoy - hasta_atras, hoy - desde_atras]; la fila n-1 es ayer (= 1 día atrás)
        ini = max(0, n - hasta_atras)
        fin = max(0, n - desde_atras + 1)
        return [x.get(k) for x in v[ini:fin]]

    prec = lambda a, b: sum(x for x in ventana(a, b, "prec") if x is not None)
    tmin10 = [x for x in ventana(1, 10, "tmin") if x is not None]
    suelo = _media([_media([x.get("suelo_0_7"), x.get("suelo_7_28")]) for x in v[-7:]])
    balance30 = sum((x.get("prec") or 0) - (x.get("et0") or 0) for x in v[-30:])
    tmax = [x.get("tmax") for x in v]
    salto_tmax = None
    if n >= 21 and all(t is not None for t in tmax[-21:]):
        salto_tmax = max(tmax[-7:]) - _media(tmax[-21:-7])
    return {
        "prec": prec,  # función: lluvia acumulada en una ventana con retardo
        "tmed": lambda dias: _media(ventana(1, dias, "tmed")),
        "lluvia_7": round(prec(1, 7), 1),
        "lluvia_30": round(prec(1, 30), 1),
        "heladas_10": sum(t <= 0 for t in tmin10),
        "heladas_fuertes_10": sum(t <= -3 for t in tmin10),
        "tmin_10": round(min(tmin10), 1) if tmin10 else None,
        "suelo_7d": None if suelo is None else round(suelo, 3),
        "balance_30": round(balance30, 1),
        "salto_tmax": None if salto_tmax is None else round(salto_tmax, 1),
    }


def puntuar(perfil: dict, ind: dict, hoy: date) -> dict:
    """Índice 0-100 de una especie y el desglose de factores (para explicar el resultado)."""
    ll = perfil["lluvia"]
    p = ind["prec"](ll["lag_ini"], ll["lag_fin"])
    # Logística con umbral (la lluvia actúa como "disparador"): 0,5 al 55 % del objetivo,
    # 0,9 al alcanzarlo, ≈0,15 con un 20 %. Forma SUPUESTA; el objetivo del níscalo, de Micocyl.
    obj = ll["objetivo_mm"]
    f_lluvia = 1 / (1 + math.exp(-(4.88 / obj) * (p - 0.55 * obj)))
    f_suelo = trapecio(ind["suelo_7d"], 0.08, 0.20, 0.40, 0.50)      # m³/m³ — SUPUESTO
    f_balance = min(1.0, max(0.0, (ind["balance_30"] + 60) / 70))    # −60 mm → 0; +10 mm → 1 — SUPUESTO
    f_agua = (PESOS_AGUA["lluvia"] * f_lluvia + PESOS_AGUA["suelo"] * f_suelo
              + PESOS_AGUA["balance"] * f_balance)

    tmed = ind["tmed"](perfil["dias_t"])
    f_temp = trapecio(tmed, *perfil["temp"])

    h = perfil["helada"]
    f_helada = max(0.0, 1 - h["leve"] * (ind["heladas_10"] - ind["heladas_fuertes_10"])
                   - h["fuerte"] * ind["heladas_fuertes_10"])

    f_calor = 1.0
    if perfil.get("calor") and ind["salto_tmax"] is not None and ind["salto_tmax"] > 6:
        f_calor = 0.7  # Salerni et al. 2023 (umbral de 6 °C SUPUESTO)

    f_fen = fenologia(perfil, hoy)
    indice = 100 * f_fen * f_agua * f_temp * f_helada * f_calor

    factores = {"fenologia": f_fen, "agua": f_agua, "temperatura": f_temp, "heladas": f_helada}
    if perfil.get("calor"):
        factores["calor"] = f_calor
    limitante = min(factores, key=factores.get)
    return {
        "indice": round(indice),
        "limitante": limitante,
        "factores": {k: round(x, 2) for k, x in factores.items()},
        "detalle": {"lluvia_ventana_mm": round(p, 1), "ventana": f"{ll['lag_ini']}-{ll['lag_fin']} d",
                    "tmed": None if tmed is None else round(tmed, 1)},
    }


def puntuar_todas(valores: list[dict], hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    ind = indicadores(valores)
    comunes = {k: x for k, x in ind.items() if not callable(x)}
    return {"indicadores": comunes,
            "especies": {k: puntuar(p, ind, hoy) for k, p in ESPECIES.items()}}


# --- Fuentes (se muestran en el mapa, sección "Cómo se calcula") ----------------------------
# tipo: "articulo" (revisado por pares), "preprint" (sin revisar), "parte" (parte micológico
# oficial), "tesis" (trabajo académico no publicado en revista), "divulgacion" (no científica). Solo se han leído resúmenes, no textos completos.
FUENTES = {
    "alday2017fe": {
        "cita": "Alday et al. (2017). Record breaking mushroom yields in Spain. Fungal Ecology.",
        "url": "https://doi.org/10.1016/j.funeco.2017.01.004", "tipo": "articulo",
        "aporta": "Los años récord de setas los dispara la lluvia de finales de verano y principio de otoño, más que la temperatura.",
    },
    "alday2017sr": {
        "cita": "Alday et al. (2017). Pinares de P. sylvestris en un gradiente de altitud, 8 años. Scientific Reports.",
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5382911", "tipo": "articulo",
        "aporta": "La lluvia de finales de verano y otoño explica la variación; pesa más el año que el sitio.",
    },
    "taye2016": {
        "cita": "Taye et al. (2016). Meteorological conditions and site characteristics driving edible mushroom production in Pinus pinaster forests of Central Spain. Fungal Ecology 23:30-41.",
        "url": "https://doi.org/10.1016/j.funeco.2016.05.008", "tipo": "articulo",
        "aporta": "La aparición del níscalo depende sobre todo de la lluvia de otoño (17 años de datos).",
    },
    "karavani2018": {
        "cita": "Karavani et al. (2018). Effect of climatic and soil moisture conditions on mushroom productivity in Mediterranean pine stands. Agricultural and Forest Meteorology 248:432-440.",
        "url": "https://medfor.eu/sites/default/files/editor/karavani_et_al_final.pdf", "tipo": "articulo",
        "aporta": "Cuenta la humedad del suelo del mismo mes; la lluvia actúa con ~1 mes de retraso.",
    },
    "agreda2015": {
        "cita": "Ágreda et al. (2015). Increased evapotranspiration demand in a Mediterranean climate might cause a decline in fungal yields under global warming. Global Change Biology 21:3499-3510.",
        "url": "https://doi.org/10.1111/gcb.12960", "tipo": "articulo",
        "aporta": "El balance hídrico (lluvia menos evaporación) importa más que la lluvia sola.",
    },
    "martinezdearagon2007": {
        "cita": "Martínez de Aragón et al. (2007). Productivity of ectomycorrhizal and edible saprotrophic fungi in pine forests of the pre-Pyrenees. Forest Ecology and Management.",
        "url": "https://doi.org/10.1016/j.foreco.2007.06.040", "tipo": "articulo",
        "aporta": "Lluvia menos evapotranspiración de septiembre-octubre explica la producción anual (citado en segunda mano).",
    },
    "pinargrande": {
        "cita": "Pinar Grande (Soria), serie de 29 años: Climate change-induced shifts in Mediterranean fungal fruiting phenology and productivity (tesis de máster, VCU, 2025).",
        "url": "https://core.ac.uk/outputs/662020453", "tipo": "tesis",
        "aporta": "Más lluvia en julio-septiembre alarga la temporada; el calor la acorta en los micorrícicos.",
    },
    "biorxiv2025": {
        "cita": "Predicting porcini: a decade of sporocarp monitoring reveals the meteorological triggers of Boletus edulis fruiting (2025). bioRxiv, preprint.",
        "url": "https://www.biorxiv.org/content/10.64898/2025.12.12.693895.full.pdf", "tipo": "preprint",
        "aporta": "Boleto: máximo con unos 13 °C de media en los 20 días previos y más setas cuanta más lluvia en 26 días.",
    },
    "salerni2023": {
        "cita": "Salerni, Paoli y Perini (2023). Italian Journal of Mycology.",
        "url": "https://doaj.org/article/8b44d1d6b39e4739ab56842f048e3336", "tipo": "articulo",
        "aporta": "Las subidas bruscas de la temperatura máxima frenan al boleto.",
    },
    "micocyl2024": {
        "cita": "Micocyl, parte micológico de Castilla y León (28-oct-2024).",
        "url": "https://micocyl.es/sites/default/files/editor/parte_mico_20241028.pdf", "tipo": "parte",
        "aporta": "Rangos térmicos ideales para el níscalo; seta de cardo citada en Burgos y Soria; especies tardías tolerantes al frío.",
    },
    "micocyl2021": {
        "cita": "Micocyl, parte micológico de Castilla y León (4-nov-2021).",
        "url": "https://www.micocyl.es/sites/default/files/editor/parte_mico_20211104.pdf", "tipo": "parte",
        "aporta": "Lluvias de más de 50 l/m² como disparador de nuevas salidas de níscalo.",
    },
    "monaco_lutescens": {
        "cita": "Monaco Nature Encyclopedia: Cantharellus lutescens.",
        "url": "https://monaconatureencyclopedia.com/cantharellus-lutescens/?lang=en", "tipo": "divulgacion",
        "aporta": "Fructifica de finales de otoño a principios de invierno, sobre todo en coníferas.",
    },
    "copernicus_hrl": {
        "cita": "Copernicus Land Monitoring Service: High Resolution Layers Forest Type, Tree Cover Density y Grassland 2018 (10 m). EEA.",
        "url": "https://land.copernicus.eu/en/products/high-resolution-layer-forests-and-tree-cover", "tipo": "datos",
        "aporta": "Dónde hay bosque de coníferas, de frondosas y praderas, con 10 m de detalle.",
    },
    "gbif": {
        "cita": "GBIF.org: registros de presencia de las 7 especies en Castilla y León ampliada, 2000-2026 "
                "(Observation.org, iNaturalist, ARAN-Fungi, SIM-Fungal, MA-Fungi, JCYL-Fungi y otros). "
                "Licencias CC BY-NC 4.0, CC BY 4.0 y CC0.",
        "url": "https://www.gbif.org/", "tipo": "datos",
        "aporta": "2.400 hallazgos reales con fecha y lugar: validan el hábitat y el clima y calibran la temporada.",
    },
    "copernicus_dem": {
        "cita": "Copernicus DEM GLO-90 (ESA / Airbus), vía AWS Open Data.",
        "url": "https://registry.opendata.aws/copernicus-dem/", "tipo": "datos",
        "aporta": "Altitud, pendiente y orientación de las laderas (umbrías).",
    },
}

# --- Hábitat (Fase 2, capa de Copernicus precalculada en static/habitat_burgos.json) ----------
# El factor de hábitat de una subcelda (≈ 1,7 × 2,2 km) es la fracción de su superficie que
# ocupa el hábitat de la especie, saturando en `saturacion` (p. ej. con saturación 0,3, si el 30 % de la subcelda es pinar,
# el níscalo tiene hábitat pleno). La asociación especie ↔ hábitat está bien establecida en la
# micología de campo y se ha VALIDADO con GBIF (AUC 0,57-0,80 frente a hallazgos de otras setas).
# Elegidos con GBIF entre pocas alternativas: boleto "frondosas + ½ coníferas"; saturación por especie
# = la de mayor AUC, salvo ganancia < 0,01, en cuyo caso la que deja menos hallazgos sin hábitat.
# Limitación: Copernicus solo distingue coníferas y frondosas, no la especie de árbol
# (en Burgos las coníferas son casi todas pinos; las frondosas, robles, quejigos, encinas y hayas).
HABITAT = {
    "lactarius_deliciosus": {"capas": {"conifera": 1.0}, "saturacion": 0.3,
                             "texto": "Pinares (micorrícico de pinos)."},
    "boletus_edulis": {"capas": {"frondosa": 1.0, "conifera": 0.5}, "saturacion": 0.5,
                       "texto": "Sobre todo hayedos, robledales y castañares; también pinares "
                                "(los hallazgos de GBIF están más asociados a frondosas)."},
    "amanita_caesarea": {"capas": {"frondosa": 1.0}, "saturacion": 0.5,
                         "texto": "Bosques de frondosas: robles, encinas, castaños."},
    "pleurotus_eryngii": {"capas": {"pradera": 1.0}, "saturacion": 0.3,
                          "texto": "Pastos y eriales con cardo corredor (Eryngium campestre). "
                                   "Copernicus no ve los márgenes de cultivo: puede infravalorarse."},
    "tricholoma_terreum": {"capas": {"conifera": 1.0}, "saturacion": 0.2,
                           "texto": "Pinares."},
    "cantharellus_lutescens": {"capas": {"conifera": 1.0}, "saturacion": 0.2,
                               "texto": "Bosques de coníferas, sobre musgo."},
    "marasmius_oreades": {"capas": {"pradera": 1.0}, "saturacion": 0.3,
                          "texto": "Praderas y pastos (corros de brujas)."},
}


def habitat(especie: str, sub: dict) -> float:
    """Factor de hábitat 0-1 de una subcelda (dict con conifera, frondosa, pradera)."""
    h = HABITAT[especie]
    frac = sum(peso * (sub.get(capa) or 0) for capa, peso in h["capas"].items())
    return round(min(1.0, frac / h["saturacion"]), 3)

FUENTES_ESPECIE = {
    "lactarius_deliciosus": {
        "fuentes": ["micocyl2021", "micocyl2024", "taye2016"],
        "supuestos": "La forma de la curva de lluvia, los pesos del agua y la penalización por heladas (no hay umbral de helada publicado).",
    },
    "boletus_edulis": {
        "fuentes": ["biorxiv2025", "salerni2023", "pinargrande"],
        "supuestos": "El umbral de 6 °C del golpe de calor, la penalización por heladas y la cantidad de lluvia objetivo.",
    },
    "amanita_caesarea": {
        "fuentes": [],
        "supuestos": "Casi todo: no se ha encontrado ningún estudio con cifras. Solo se sabe que es termófila (fuentes divulgativas).",
    },
    "pleurotus_eryngii": {
        "fuentes": ["micocyl2024"],
        "supuestos": "Rangos térmicos y ventana de lluvia (2-3 semanas, según divulgación); no hay estudio cuantitativo.",
    },
    "tricholoma_terreum": {
        "fuentes": ["micocyl2024"],
        "supuestos": "Rangos térmicos y tolerancia a heladas: solo se sabe que es tardía y aguanta el frío.",
    },
    "cantharellus_lutescens": {
        "fuentes": ["monaco_lutescens"],
        "supuestos": "Rangos térmicos y tolerancia a heladas; no hay estudio cuantitativo.",
    },
    "marasmius_oreades": {
        "fuentes": [],
        "supuestos": "Todo el perfil: no se ha encontrado ningún estudio sobre su fructificación.",
    },
}

# Respaldan el factor agua y el papel del calor para todas las especies
FUENTES_GENERALES = ["alday2017fe", "alday2017sr", "karavani2018", "agreda2015", "martinezdearagon2007", "pinargrande"]

METODO = [
    "Datos: observaciones de las estaciones AEMET de Burgos y el modelo meteorológico de Open-Meteo "
    "(ECMWF IFS, unos 9 km) en una malla de 159 celdas de unos 8 × 11 km.",
    "Cerca de cada estación se corrige el modelo con lo que midió AEMET (lluvia y temperaturas); "
    "lejos de ellas solo se usa el modelo y la confianza baja.",
    "Para cada especie se puntúan de 0 a 1 cinco factores: época del año, agua (lluvia de las últimas "
    "semanas con retraso, humedad del suelo y lluvia menos evaporación), temperatura media reciente, "
    "heladas de los últimos 10 días y, en el boleto, golpes de calor.",
    "El índice es 100 × el producto de los factores: basta con que uno falle (por ejemplo, sin agua) "
    "para que el resultado baje mucho.",
    "Hábitat (Copernicus): en una malla fina de unos 2 km se mira qué parte del terreno es pinar, "
    "bosque de frondosas o pradera, y se multiplica por el clima de su celda. Una zona sin el árbol "
    "de la especie queda a 0 aunque el tiempo sea perfecto. Se puede ver también solo el clima.",
    "Validación con 2.400 hallazgos reales (GBIF): el hábitat tiene señal en las 7 especies; la "
    "temporada se ha ajustado a los meses reales; el efecto del tiempo reciente solo se ha demostrado "
    "en algunas especies (se indica junto al selector).",
    "No es una probabilidad calibrada: no distingue la especie de árbol (solo coníferas o frondosas), "
    "ni el suelo, ni la edad del bosque.",
]


_VALIDACION = {"datos": None}


def _validacion() -> dict:
    """Resumen de static/validacion_gbif.json (generado por scripts/gbif_validacion.py)."""
    if _VALIDACION["datos"] is None:
        ruta = Path(__file__).resolve().parent.parent / "static" / "validacion_gbif.json"
        _VALIDACION["datos"] = json.loads(ruta.read_text()) if ruta.exists() else {}
    return _VALIDACION["datos"]


def validacion_especie(sp: str) -> dict | None:
    v = _validacion()
    if not v:
        return None
    h, c, f = v["habitat"][sp], v["clima"][sp], v["fenologia"][sp]
    auc = h["auc_vs_otras_setas"]
    nivel_h = "buena" if auc >= 0.65 else "moderada" if auc >= 0.6 else "débil"
    gana, p = c["gana_hallazgo_pct"], c["p_signos"]
    if p is not None and p < 0.05 and gana > 55:
        nivel_c = "demostrada"
    elif p is not None and p < 0.1 and gana > 55:
        nivel_c = "indicios"
    else:
        nivel_c = "no demostrada"
    return {
        "habitat": {"nivel": nivel_h, "auc": auc, "n": h["n"], "pct_sin_habitat": h["pct_hallazgos_sin_habitat"],
                    "pct_territorio_sin_habitat": h["pct_territorio_sin_habitat"]},
        "clima": {"nivel": nivel_c, "gana_pct": gana, "p": p, "n_hallazgos": c["n_hallazgos"], "n_pares": c["n_pares"]},
        "temporada": {"n": f["n"]},
        "fecha": v["fecha"],
    }


def catalogo() -> dict:
    especies = []
    for k, p in ESPECIES.items():
        fe = FUENTES_ESPECIE.get(k, {})
        especies.append({"id": k, "nombre": p["nombre"], "grupo": p["grupo"], "resumen": p["fuentes"],
                         "fuentes": fe.get("fuentes", []), "supuestos": fe.get("supuestos"),
                         "habitat": HABITAT[k], "validacion": validacion_especie(k)})
    return {"especies": especies, "fuentes": FUENTES, "metodo": METODO, "fuentes_generales": FUENTES_GENERALES,
            "fuentes_habitat": ["copernicus_hrl", "copernicus_dem"], "fuentes_validacion": ["gbif"]}
