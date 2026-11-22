"""Especies recolectables añadidas en la ampliación (nov-2026) y confusiones peligrosas de todas.

Criterio de inclusión: comestible, recolectada en Castilla y León y con ≥ 70 registros en GBIF en
"CyL ampliada" (lat 40-43,3; lon −7,1 a −1,7; 2000-2026). Excluida Tricholoma equestre (tóxica:
rabdomiólisis; no comercializable en España aunque tenga muchos registros).

Qué es dato y qué es supuesto en las especies nuevas:
- Temporada y hábitat: DATO. Se calculan con sus hallazgos de GBIF y las capas de Copernicus
  (scripts/perfiles_gbif.py → app/perfiles_gbif.json), igual que se validó con las 7 primeras.
- Clima (rango térmico, ventana y objetivo de lluvia, tolerancia a heladas): SUPUESTO por grupo
  funcional, a partir de las especies ya estudiadas y de su ecología general. Pendiente de calibrar
  con Open-Meteo en los días de los hallazgos (como se hizo con las 7 primeras).
"""

# Plantillas climáticas por grupo funcional (SUPUESTOS; misma estructura que modelo.ESPECIES)
GRUPOS = {
    "termofilo": {
        "texto": "micorrícico termófilo (boletos de verano, rúsulas, rebozuelo)",
        "lluvia": {"lag_ini": 5, "lag_fin": 26, "objetivo_mm": 45},
        "temp": (10, 14, 20, 25), "dias_t": 20, "helada": {"leve": 0.30, "fuerte": 0.60},
    },
    "otonal_conifera": {
        "texto": "micorrícico otoñal de pinar",
        "lluvia": {"lag_ini": 5, "lag_fin": 30, "objetivo_mm": 50},
        "temp": (3, 8, 14, 20), "dias_t": 20, "helada": {"leve": 0.10, "fuerte": 0.25},
    },
    "tardio": {
        "texto": "micorrícico tardío, tolerante al frío",
        "lluvia": {"lag_ini": 5, "lag_fin": 30, "objetivo_mm": 40},
        "temp": (1, 5, 11, 16), "dias_t": 20, "helada": {"leve": 0.04, "fuerte": 0.12},
    },
    "hojarasca": {
        "texto": "saprótrofo de hojarasca y humus (otoño)",
        "lluvia": {"lag_ini": 3, "lag_fin": 21, "objetivo_mm": 35},
        "temp": (3, 7, 14, 19), "dias_t": 14, "helada": {"leve": 0.08, "fuerte": 0.20},
    },
    "pradera": {
        "texto": "saprótrofo de pradera, responde rápido a la lluvia",
        "lluvia": {"lag_ini": 2, "lag_fin": 14, "objetivo_mm": 25},
        "temp": (6, 10, 18, 23), "dias_t": 14, "helada": {"leve": 0.15, "fuerte": 0.35},
    },
    "madera": {
        "texto": "lignícola de otoño e invierno (sobre madera de frondosas)",
        "lluvia": {"lag_ini": 3, "lag_fin": 21, "objetivo_mm": 30},
        "temp": (0, 4, 12, 18), "dias_t": 14, "helada": {"leve": 0.02, "fuerte": 0.05},
    },
    "primavera": {
        "texto": "primaveral",
        "lluvia": {"lag_ini": 5, "lag_fin": 30, "objetivo_mm": 40},
        "temp": (6, 9, 15, 20), "dias_t": 14, "helada": {"leve": 0.10, "fuerte": 0.25},
    },
}

# id -> datos. temp propio solo donde la especie se aparta claramente de su grupo (SUPUESTO).
NUEVAS = {
    "macrolepiota_procera": {"nombre": "Parasol (Macrolepiota procera)", "taxon": 8914748, "grupo": "hojarasca",
                             "temp": (5, 9, 17, 22)},
    "coprinus_comatus": {"nombre": "Barbuda (Coprinus comatus)", "taxon": 7987658, "grupo": "pradera"},
    "lepista_nuda": {"nombre": "Pie violeta (Lepista nuda)", "taxon": 5242048, "grupo": "hojarasca"},
    "boletus_reticulatus": {"nombre": "Boleto de verano (Boletus reticulatus)", "taxon": 5954691, "grupo": "termofilo"},
    "hydnum_repandum": {"nombre": "Lengua de vaca (Hydnum repandum)", "taxon": 2554716, "grupo": "tardio"},
    "russula_cyanoxantha": {"nombre": "Carbonera (Russula cyanoxantha)", "taxon": 2551542, "grupo": "termofilo"},
    "suillus_luteus": {"nombre": "Babosa (Suillus luteus)", "taxon": 7777157, "grupo": "otonal_conifera"},
    "pleurotus_ostreatus": {"nombre": "Seta de ostra (Pleurotus ostreatus)", "taxon": 2526530, "grupo": "madera"},
    "boletus_aereus": {"nombre": "Boleto negro (Boletus aereus)", "taxon": 8733688, "grupo": "termofilo"},
    "agaricus_campestris": {"nombre": "Champiñón silvestre (Agaricus campestris)", "taxon": 5243458, "grupo": "pradera"},
    "cantharellus_cibarius": {"nombre": "Rebozuelo (Cantharellus cibarius)", "taxon": 5249504, "grupo": "termofilo"},
    "calocybe_gambosa": {"nombre": "Perretxiko (Calocybe gambosa)", "taxon": 8936224, "grupo": "primavera",
                         "temp": (7, 10, 16, 21)},
    "craterellus_cornucopioides": {"nombre": "Trompeta de los muertos (Craterellus cornucopioides)",
                                   "taxon": 2554662, "grupo": "tardio", "temp": (4, 8, 14, 19)},
    "clitocybe_geotropa": {"nombre": "Platera (Infundibulicybe geotropa)", "taxon": 9186073, "grupo": "hojarasca"},
    "morchella_esculenta": {"nombre": "Colmenilla (Morchella esculenta)", "taxon": 2594602, "grupo": "primavera",
                            "temp": (5, 8, 14, 19)},
    "boletus_pinophilus": {"nombre": "Boleto pinícola (Boletus pinophilus)", "taxon": 5954949, "grupo": "termofilo",
                           "temp": (8, 12, 18, 23)},
    "hygrophorus_russula": {"nombre": "Hygrophorus russula", "taxon": 2538807, "grupo": "tardio"},
    "russula_virescens": {"nombre": "Gorro verde (Russula virescens)", "taxon": 2551423, "grupo": "termofilo"},
    "tricholoma_portentosum": {"nombre": "Capuchina (Tricholoma portentosum)", "taxon": 5241860, "grupo": "tardio"},
    "lepista_personata": {"nombre": "Pie azul (Lepista personata)", "taxon": 5242070, "grupo": "hojarasca"},
    "flammulina_velutipes": {"nombre": "Aguja de invierno (Flammulina velutipes)", "taxon": 3341441, "grupo": "madera"},
    "hygrophorus_marzuolus": {"nombre": "Marzuelo (Hygrophorus marzuolus)", "taxon": 7244099, "grupo": "primavera",
                              "temp": (0, 3, 9, 13), "helada": {"leve": 0.02, "fuerte": 0.06}},
    "craterellus_tubaeformis": {"nombre": "Angula gris (Craterellus tubaeformis)", "taxon": 2554536, "grupo": "tardio"},
    "lepista_panaeola": {"nombre": "Lepista panaeola", "taxon": 5242063, "grupo": "hojarasca"},
}

# Confusiones peligrosas (información general de micología; no sustituye a la identificación experta)
CONFUSIONES = {
    "lactarius_deliciosus": "Lactarius torminosus y otros Lactarius de látex blanco (tóxicos).",
    "boletus_edulis": "Rubroboletus satanas (poros rojos, tóxico) y Tylopilus felleus (muy amargo).",
    "amanita_caesarea": "Amanita muscaria (roja con escamas blancas y láminas blancas, tóxica).",
    "pleurotus_eryngii": "Pocas confusiones peligrosas; comprobar siempre la especie.",
    "tricholoma_terreum": "Tricholoma pardinum (tóxica) y otros Tricholoma grises.",
    "cantharellus_lutescens": "Pocas confusiones peligrosas; comprobar siempre la especie.",
    "marasmius_oreades": "Clitocybe blancas de pradera (C. dealbata, C. rivulosa), muy tóxicas.",
    "macrolepiota_procera": "Lepiota pequeñas (algunas mortales) y Chlorophyllum (tóxicas).",
    "coprinus_comatus": "Coprinopsis atramentaria (tóxica con alcohol). Solo ejemplares jóvenes y blancos.",
    "lepista_nuda": "Cortinarius violáceos (algunos muy tóxicos).",
    "boletus_reticulatus": "Rubroboletus satanas (poros rojos, tóxico) y Tylopilus felleus (muy amargo).",
    "hydnum_repandum": "Pocas confusiones peligrosas (Sarcodon amargos).",
    "russula_cyanoxantha": "Amanita phalloides (mortal; tiene anillo y volva en la base).",
    "suillus_luteus": "Pocas confusiones peligrosas; retirar la cutícula (laxante).",
    "pleurotus_ostreatus": "Omphalotus olearius (tóxica, anaranjada, sobre tocones).",
    "boletus_aereus": "Rubroboletus satanas (poros rojos, tóxico) y Tylopilus felleus (muy amargo).",
    "agaricus_campestris": "Amanitas blancas MORTALES (A. phalloides blanca, A. verna, A. virosa) y "
                           "Agaricus xanthodermus (tóxico, amarillea al roce).",
    "cantharellus_cibarius": "Omphalotus olearius (tóxica) e Hygrophoropsis aurantiaca.",
    "calocybe_gambosa": "Entoloma sinuatum (tóxica) e Inocybe erubescens (mortal).",
    "craterellus_cornucopioides": "Pocas confusiones peligrosas; comprobar siempre la especie.",
    "clitocybe_geotropa": "Clitocybe tóxicas y Entoloma sinuatum.",
    "morchella_esculenta": "Gyromitra esculenta (mortal). Las colmenillas son tóxicas crudas: cocinarlas siempre.",
    "boletus_pinophilus": "Rubroboletus satanas (poros rojos, tóxico) y Tylopilus felleus (muy amargo).",
    "hygrophorus_russula": "Pocas confusiones peligrosas; comprobar siempre la especie.",
    "russula_virescens": "Amanita phalloides (mortal; verdosa, con anillo y volva en la base).",
    "tricholoma_portentosum": "Tricholoma pardinum (tóxica) y Tricholoma equestre (tóxica).",
    "lepista_personata": "Clitocybe blancas y Entoloma tóxicos.",
    "flammulina_velutipes": "Galerina marginata (MORTAL; crece en la misma madera).",
    "hygrophorus_marzuolus": "Pocas confusiones peligrosas; comprobar siempre la especie.",
    "craterellus_tubaeformis": "Pocas confusiones peligrosas; comprobar siempre la especie.",
    "lepista_panaeola": "Clitocybe blancas y Entoloma tóxicos.",
}
