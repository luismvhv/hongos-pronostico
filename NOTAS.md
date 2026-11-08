# NOTAS — Estado del proyecto `hongos-pronostico`

Documento de traspaso entre sesiones. Léelo entero antes de tocar código.
Idioma de trabajo con el usuario (Luis): **español**.

## 1. Objetivo

Aplicación web que estima la **probabilidad / favorabilidad de fructificación de setas**
a partir de datos meteorológicos y la muestra en un **mapa coloreado tipo mapa de calor**
(verde → rojo). Cobertura: península ibérica, con **mayor precisión en Castilla y León**.
Zona prioritaria del usuario: **provincia de Burgos**.

Especies de interés: *Lactarius deliciosus* (níscalo), *Boletus edulis* (y boletos afines),
*Amanita* (p. ej. *A. caesarea*), y otras de otoño en CyL: *Pleurotus eryngii* (seta de cardo),
*Tricholoma terreum* (negrilla), *Cantharellus lutescens / tubaeformis*, *Marasmius oreades*.
El usuario quiere elegir la especie y ver un % aproximado por zona.

Principio clave: el resultado es una **estimación de favorabilidad climática**, no una
garantía de que haya setas (bosque, suelo, orientación y altitud también cuentan).
El mapa debe **mostrar la confianza** del resultado, no esconderla.

## 2. Stack y despliegue

- Backend: **Python + FastAPI** (`app/`). La clave de AEMET nunca llega al navegador.
- Frontend: **HTML + JS + Leaflet** con teselas de OpenStreetMap (`static/index.html`).
- Repositorio: `github.com/luismvhv/hongos-pronostico` (rama `main`).
- Despliegue: **Render**, plan gratuito, auto-deploy al hacer push a `main`.
  - URL: https://hongos-pronostico.onrender.com
  - Build: `pip install -r requirements.txt`
  - Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
  - Variable de entorno en Render: `AEMET_API_KEY` (la pone el usuario; NO va al repo).
  - El plan gratuito se duerme con inactividad: la primera petición puede tardar ~50 s.
- En local: copiar `.env.example` a `.env` con `AEMET_API_KEY=...` (`.env` está en `.gitignore`).

### Red de la sesión de Claude
La sesión debe correr en el entorno cloud **"Hongos Pronostico"** con acceso **Custom** a:
`hongos-pronostico.onrender.com`, `opendata.aemet.es`, `archive-api.open-meteo.com`,
`api.open-meteo.com`, `rest.isric.org`, `overpass-api.de` (+ lista por defecto de package managers).
Primera tarea de la sesión nueva: **comprobar conectividad** a esos dominios con `curl`.
Si alguno da 403, avisar al usuario (no intentar esquivar el proxy).

Clave de AEMET para probar desde la sesión: lo ideal es que el usuario la guarde como
**network secret** del entorno (host `opendata.aemet.es`, cabecera `api_key`, sin prefijo),
así Claude nunca la ve. Si no existe ese secret, las pruebas contra AEMET se hacen vía Render.
Nunca escribir la clave en ficheros del repo ni en el chat.

## 3. Estructura actual

```
app/
  main.py      # rutas FastAPI
  aemet.py     # cliente AEMET OpenData
  comparar.py  # resumen comparativo por estación
  openmeteo.py # cliente Open-Meteo Historical (diarios + lluvia 07-07 UTC)
  validacion.py # AEMET vs Open-Meteo: métricas y confianza
  modelo.py    # índice de favorabilidad v0 por especie
  mapa.py      # malla de Burgos, fusión AEMET + Open-Meteo, confianza por celda
  progreso.py  # estado del cálculo para la pantalla de carga
static/
  index.html   # mapa de calor Leaflet (selector de especie, leyenda, confianza)
  burgos.geojson # contorno provincial (IGN vía es-atlas)
requirements.txt  .env.example  .gitignore  NOTAS.md
```

### Endpoints
| Ruta | Estado | Qué hace |
|---|---|---|
| `GET /` | ✅ | Mapa de calor de Burgos por especie |
| `GET /api/mapa/progreso` | ✅ | Fase y avance del cálculo en curso (pantalla de carga) |
| `GET /api/mapa?provincia=BURGOS` | ✅ | Celdas con índice por especie, indicadores, confianza y aviso |
| `GET /api/estaciones?provincias=BURGOS,SORIA` | ✅ verificado | Inventario AEMET con lat/lon decimales |
| `GET /api/diarios/{indicativo}?dias=30` | ✅ verificado | Valores diarios: tmed, tmin, tmax, prec, hr, sol |
| `GET /api/comparar?provincias=BURGOS&dias=21` | ✅ verificado en Render (nov-2026) | Por estación: lluvia acumulada, días con lluvia, heladas (tmin ≤ 0), tmed media, sol medio, **cobertura** (días con dato, último dato, aviso si < 80 %); ordenado por lluvia |
| `GET /api/validacion?provincias=BURGOS&dias=90` | ✅ verificado en Render | Métricas AEMET vs Open-Meteo y confianza por estación |
| `GET /api/openmeteo?lat=&lon=&dias=` | ✅ verificado | Serie diaria Open-Meteo: tmed/tmax/tmin, prec, hr, humedad del suelo 0-7 y 7-28 cm, ET0 |

## 4. Peculiaridades de AEMET OpenData ya resueltas (no repetir errores)

1. **URL base**: `https://opendata.aemet.es/opendata/api/...` (NO `/opendataapi`, da 404).
2. **Flujo en dos pasos**: la petición devuelve JSON con `estado` y `datos`; `datos` es otra URL
   con el contenido real.
3. **Codificación**: el contenido de `datos` viene en **ISO-8859-1**, no UTF-8
   (falla con byte `0xd3`). Se decodifica con fallback a latin-1.
4. **Coordenadas**: formato `DDMMSS` + hemisferio **tanto en latitud como en longitud**
   (`033713W` = 3°37'13" W = -3.62). La longitud NO lleva 3 dígitos de grados.
5. Números con **coma decimal**; precipitación `Ip` = inapreciable → 0.0.
6. **Retraso de publicación**: los diarios llegan con ~2-3 días de retraso.
7. `hr` (humedad relativa) llega **vacía** en el endpoint de diarios; `sol` (horas) sí llega.
8. Peticiones de diarios en bloques de 30 días (`CHUNK_DAYS`), por prudencia.
9. Estación sin datos en el periodo → `estado: 404` "No hay datos que satisfagan esos criterios"
   (p. ej. 9027X Sargentes de la Lora en oct-nov 2026). Se informa por estación, no tumba la petición.
10. Cobertura irregular: Aranda (2117D) solo tenía 7 de 21 días. Por eso `/api/comparar` devuelve
    `cobertura_prec` y un aviso; una suma de lluvia sin cobertura engaña.
11. No hay network secret de AEMET en el entorno (nov-2026): sin clave, AEMET responde 200 con
    cuerpo vacío. Las pruebas contra AEMET se hacen vía Render.

Burgos tiene 14 estaciones climatológicas en el inventario (indicativos: 2106B, 2117D, 2285B,
2290Y, 2298, 2302N, 2311Y, 2331 [Burgos Aeropuerto], 9012E, 9027X, 9031C, 9051, 9069C, 9111).

Dato real observado (Burgos Aeropuerto, 7 oct – 3 nov 2026): solo ~4.6 mm de lluvia en 30 días,
heladas el 24/10, 31/10 y 1/11 (mín. -2.9 °C), mucho sol. Coherente con una campaña pobre.

## 4b. Open-Meteo Historical (`app/openmeteo.py`) — comprobado nov-2026

- Endpoint: `https://archive-api.open-meteo.com/v1/archive`, sin clave.
- La web de documentación (`open-meteo.com`) **no está en la lista de red** de la sesión:
  los nombres se confirmaron **probándolos contra la API** y las condiciones por búsqueda web.
- Variables diarias válidas (probadas): `temperature_2m_mean/max/min`, `precipitation_sum`,
  `rain_sum`, `relative_humidity_2m_mean`, `soil_moisture_0_to_7cm_mean`,
  `soil_moisture_7_to_28cm_mean`, `soil_moisture_28_to_100cm_mean`,
  `et0_fao_evapotranspiration`, `dew_point_2m_mean`, `sunshine_duration` (s).
  - `soil_moisture_0_to_10cm_mean` existe pero devuelve `null` aquí (es de otros modelos).
  - `sunshine_duration` da valores irreales en noviembre (36 000 s = 10 h): **no usar**.
- Modelos: `best_match` = **ECMWF IFS (~9 km)** y llega **hasta ayer**. `era5`/`era5_land`
  llevan **~6 días de retraso** (null en los últimos días). Se usa `best_match`.
- Varias coordenadas en una petición (`latitude=a,b&longitude=c,d`) → devuelve una lista.
  Parámetro `elevation` corrige temperatura por altitud (se pasa la de la estación).
- Condiciones: gratis **solo uso no comercial**, < 10 000 llamadas/día, 5 000/h, 600/min;
  licencia **CC BY 4.0** → atribución visible "Weather data by Open-Meteo.com".
  Cada coordenada cuenta como llamada; >2 semanas o >10 variables cuentan como fracciones extra.
  Por eso: lotes de 50 puntos y caché en memoria de 6 h.
- El proxy de la sesión de Claude **corta conexiones** a veces (reset): el cliente reintenta.
- Endpoint propio: `GET /api/openmeteo?lat=..&lon=..&dias=30&elevacion=..`.

## 4c. Validación AEMET vs Open-Meteo (`app/validacion.py`, `GET /api/validacion`)

- **Alineación de la lluvia (comprobada)**: la `prec` diaria de AEMET del día D es el
  acumulado de **07 UTC de D a 07 UTC de D+1**. Con 14 estaciones × 90 días: r = 0,79 con esa
  ventana, 0,71 con el día civil y 0,04 con la ventana desplazada un día. Se pide la lluvia
  horaria de Open-Meteo en GMT y se suma 07→07 (`openmeteo.precip_07a07`).
- Métricas: MAE/sesgo de tmax, tmin, tmed (Open-Meteo con `elevation` = altitud estación);
  lluvia: acierto sí/no con umbral **1 mm**, POD, falsas alarmas, ratio de acumulados.
- Reglas de confianza (provisionales): MAE medio T < 2 °C; acierto > 75 %; ratio en [0,7, 1,4];
  ≥ 30 días comparables. Todo OK → **alta**; falla 1 → **media**; fallan ≥ 2 → **baja**.
- **Resultado 9 ago – 6 nov 2026 (Burgos)**: 13 estaciones válidas → 10 alta, 3 media, 0 baja.
  - Media: 2298 Palacios de la Sierra (MAE T 2,01), 2311Y Villamayor (Open-Meteo ×2,1 de lluvia),
    9069C Miranda de Ebro (×1,7 de lluvia). 9027X Sargentes: sin datos AEMET.
  - **Sesgo sistemático**: Open-Meteo subestima tmax (≈ −1,4 °C) y sobreestima tmin (≈ +1 °C;
    Aranda +2,2 °C por inversión térmica de valle) → **detecta menos heladas de las reales**.
    Por eso el mapa corrige el sesgo de tmin/tmax cerca de estaciones.
  - El acierto sí/no está inflado por el periodo seco (la mayoría de días "no llueve" en ambos);
    mirar también POD (0,71-1,0) y el ratio de acumulados.
- Rendimiento AEMET en Render: 14 estaciones × 3 bloques = 42 peticiones → aparecían **429**
  (límite por minuto) y **500** esporádicos en las URL `datos`. Solución: reintentos con espera
  (`_get_reintentos`), concurrencia 2, caché de diarios 6 h y de la validación 12 h (solo si no
  hubo fallos transitorios). Primera llamada en frío ≈ 100 s; después, instantánea.

## 5. Base de conocimiento micológica (resumen)

- La fructificación de micorrícicos (níscalo, boleto) depende en gran parte de humedad y
  temperatura (partes de Micocyl citan ~60 % meteorología, ~40 % otros factores: árbol, suelo).
- **Lluvia**: hace falta una lluvia importante (en partes de CyL se cita >50 l/m² como disparador
  de nuevos níscalos); efecto **retardado** (≈1-3 semanas). Lluvia continua y suelo encharcado
  también perjudica. Las lluvias de finales de verano/principio de otoño pesan mucho.
- **Temperatura**: ideal máximas 12-20 °C y mínimas > 5 °C (parte Micocyl oct-2024).
  *Boletus edulis* es termófilo: decae con el descenso térmico y se corta con las heladas.
  El níscalo tolera más frío; en CyL se recoge hasta bien entrado diciembre.
  Subidas bruscas de temperatura máxima inhiben *B. edulis* (Salerni et al., 2023).
- **Heladas**: fuertes o tempranas terminan la temporada.
- Hay ventanas fenológicas por especie (boleto antes que níscalo).
- Fuentes usadas: partes micológicos de micocyl.es (2021, 2024), Diario de León (campaña 2025),
  bioRxiv 10.64898/2025.12.12.693895 (disparadores meteorológicos de *B. edulis*, 10 años de datos),
  Italian Journal of Mycology 2023 (Salerni, Paoli, Perini).
- Pendiente: revisión bibliográfica más rigurosa para fijar pesos y retardos por especie.

## 5b. Revisión bibliográfica para el modelo v0 (nov-2026) y diseño (`app/modelo.py`)

Búsqueda web (sin acceso a texto completo: los hallazgos vienen de resúmenes; verificar en Fase 3).

| Fuente | Qué aporta | Uso en v0 |
|---|---|---|
| Alday et al. 2017, *Fungal Ecology* (doi 10.1016/j.funeco.2017.01.004), "Record breaking mushroom yields in Spain" | Picos de 2006 y 2014 (+270 %, +210 %) disparados por la **lluvia de finales de verano–principio de otoño**, más que por la temperatura | La lluvia es el factor principal |
| Alday et al. 2017, *Sci. Rep.* (PMC5382911), gradiente altitudinal *P. sylvestris* | La lluvia de finales de verano–otoño explica la variación; el año pesa más que el sitio | Ídem |
| Taye et al. 2016, *Fungal Ecology* 23:30-41 (doi 10.1016/j.funeco.2016.05.008), *P. pinaster*, Centro de España, 17 años | Ocurrencia de *Lactarius* gr. *deliciosus* explicada sobre todo por la **lluvia otoñal**; suelo ácido +, suelo arenoso −, rodales viejos − | Lluvia; suelo para Fase 2 |
| Karavani et al. 2018, *Agric. For. Meteorol.* 248:432-440, *P. pinaster*, NE España | Producción ligada a tiempo y **humedad del suelo del mismo mes**, salvo la **lluvia, con 1 mes de retraso** | Ventanas de lluvia con retardo; factor suelo |
| Ágreda et al. 2015, *Glob. Change Biol.* 21:3499-3510 (doi 10.1111/gcb.12960), 15 años | Los modelos de **balance hídrico** (lluvia − ET) predicen distinto que los de lluvia sola; la demanda evaporativa reduce la producción | Factor balance P − ET0 |
| Martínez de Aragón et al. 2007, *For. Ecol. Manage.* (doi 10.1016/j.foreco.2007.06.040), Solsonès | Según un trabajo que lo cita: P − ET de **septiembre-octubre** explica la producción anual | Ídem (cita de segunda mano) |
| Pinar Grande (Soria), serie de 29 años (tesis VCU 2025; y trabajo 1995-2013) | Lluvia jul-sep → temporadas más largas y más producción; **calor** → temporada micorrícica más corta; descenso de *B. edulis* y *Lactarius* con menos lluvia jul-sep | Penalizar calor/sequía |
| bioRxiv 10.64898/2025.12.12.693895 (preprint, **sin revisión por pares**), *B. edulis*, hayedos de Europa central, 10 años | Máximo con **T media ≈ 13 °C en 20 días**; producción crece con la **lluvia acumulada en 26 días** | Perfil térmico y ventana de *B. edulis* |
| Salerni, Paoli, Perini 2023, *Ital. J. Mycol.* | **Subidas bruscas de tmax** inhiben *B. edulis* (21 días tras el evento) | Factor "golpe de calor" |
| Partes de Micocyl (2021, oct-2024) | Níscalo: lluvia > 50 l/m² como disparador; máximas 12-20 °C y mínimas > 5 °C; *P. eryngii* citado en Burgos y Soria en oct-2024 | Objetivo de lluvia y rango del níscalo |

**Sin respaldo cuantitativo encontrado** (perfiles SUPUESTOS, marcados así en el código):
*Amanita caesarea* (solo "termófila"; análogo *A. ponderosa*, Daza et al. 2007: lluvia de final de
verano), *Pleurotus eryngii* (divulgación: 2-3 semanas tras lluvias), *Tricholoma terreum* y
*Cantharellus lutescens* (tardías, tolerantes al frío), *Marasmius oreades* (pradera, rápida).
Tampoco hay umbral publicado de helada para el níscalo.

**Diseño v0** — índice = 100 · fenología · agua · temperatura · heladas [· calor (*B. edulis*)]:
- Multiplicativo: cada factor puede limitar (si no hay agua, no hay setas aunque la T sea ideal).
- Agua = 0,5·lluvia (logística con umbral sobre la ventana con retardo; 0,9 al llegar al objetivo)
  + 0,25·humedad del suelo 0-28 cm (7 días) + 0,25·balance P − ET0 (30 días). **Pesos supuestos**.
- Temperatura: trapecio sobre la T media de 14-20 días por especie.
- Heladas: penalización por día con tmin ≤ 0 / ≤ −3 °C en 10 días, según tolerancia de la especie.
- Fenología: peso mensual orientativo para Burgos (supuesto a partir de partes regionales).
- Es un **índice de favorabilidad climática, no una probabilidad calibrada**.
- Contraste rápido (Burgos Aeropuerto): 28-oct-2024 → níscalo 100 (otoño muy lluvioso, 136 mm/30 d);
  7-nov-2026 → níscalo 19 (11,6 mm/30 d, balance −53 mm). Coherente, pero **no es validación**:
  falta calibrar con partes reales (Fase 3).
- Endpoints: `GET /api/especies`, `GET /api/favorabilidad?lat=&lon=` (punto suelto, sin AEMET).

## 5c. Mapa de calor de Burgos (`app/mapa.py`, `GET /api/mapa`, `static/index.html`)

- Malla de **0,1°** (≈ 8 × 11 km, del orden de ECMWF IFS ~9 km): **159 celdas** cuyo centro cae
  dentro del contorno IGN de Burgos (`static/burgos.geojson`, del paquete npm `es-atlas`, MIT;
  incluye el enclave de Treviño). Overpass no respondía desde la sesión (reset), por eso se usó npm.
- Fusión con la estación AEMET validada más cercana, peso k = exp(−d/20 km) (**supuesto**):
  lluvia diaria k·AEMET + (1−k)·Open-Meteo; temperaturas corregidas por el sesgo de la estación.
- Confianza por celda: nivel de la estación más cercana; baja un nivel a 15-35 km; > 35 km → baja.
  Resultado nov-2026: 62 alta, 76 media, 21 baja.
- Frontend: selector de especie (se recuerda en localStorage), leyenda, aviso de confianza,
  ventana emergente por celda con el factor limitante y los indicadores, estaciones con su validación.
- **Color**: NOTAS pedía "verde → rojo", pero rojo-verde es ilegible con daltonismo (deuteranopía).
  Se usa la rampa secuencial **YlGn** de ColorBrewer (amarillo pálido → verde oscuro, 5 clases de 20):
  "verde = favorable" se mantiene y la luminosidad es monótona. Confianza baja = **trama rayada**,
  media = borde discontinuo (no depende solo del color).
- Rendimiento: ~17 s con la validación ya en caché; ~2 min en frío. Al arrancar el servicio se
  precalcula en segundo plano (`startup`). Caché de 6 h. ~500 "llamadas" Open-Meteo por cálculo.
- Pruebas desde la sesión: `unpkg.com` y las teselas de OSM **no están permitidas** en la red de la
  sesión; en Playwright se sirven Leaflet desde npm y un fondo liso (solo para la prueba local).
- Primer resultado (7-nov-2026): níscalo con media 19/100 en la provincia (limitado por el agua),
  máximos ~60 en Las Merindades (norte, más lluvia); la Demanda alta sale a 0 por heladas.

## 5d. Experiencia de usuario (nov-2026)

- **Panel plegable** (botón "Plegar"/"Leyenda", `aria-expanded`): título y selector de especie siempre
  visibles; plegado muestra una mini-rampa de color. El estado se recuerda en localStorage;
  por defecto plegado en móvil (≤ 600 px) y desplegado en escritorio.
- **"Cómo se calcula y fuentes"** (`<details>` dentro del panel): método en 5 pasos, fuentes
  **específicas** de la especie elegida y fuentes **generales** (factor agua/calor), cada una con
  etiqueta de tipo (Artículo, Preprint, Tesis, Parte micológico, Divulgación), enlace y qué aporta,
  y un recuadro de **Supuestos**. Datos en `modelo.FUENTES`, `FUENTES_ESPECIE`, `FUENTES_GENERALES`,
  `METODO`, servidos por `GET /api/especies`. Oronja y senderuela no tienen fuente específica:
  se dice explícitamente.
- **Pantalla de carga**: solo aparece si `/api/mapa` tarda > 0,7 s. Nube SVG con lluvia, relámpago
  periódico (tocar la nube lanza un rayo), seta que crece con el progreso, mensajes rotativos.
  **Progreso real**: `app/progreso.py` + `GET /api/mapa/progreso` (fase, hecho/total: inventario,
  estaciones AEMET n de 14, Open-Meteo, modelo). Si el progreso no responde, se asume que Render
  está despertando y se dice. Respeta `prefers-reduced-motion`.
- `mapa.calcular` usa un **candado**: el precálculo de arranque y las visitas no calculan a la vez
  (antes podían duplicar las ~42 peticiones a AEMET y provocar 429).

## 5e. Fase 2 — Hábitat con Copernicus (nov-2026)

### Qué ofrece Copernicus gratis y qué se ha usado
| Producto | Resolución | Acceso comprobado | ¿Usado? |
|---|---|---|---|
| **HRL Forest Type 2018** (0 no bosque, 1 frondosas, 2 coníferas) | 10 m | ImageServer EEA sin login (`image.discomap.eea.europa.eu/.../GioLandPublic/HRL_ForestType_2018`) | ✅ |
| **HRL Tree Cover Density 2018** (0-100 %) | 10 m | Ídem (`HRL_TreeCoverDensity_2018`) | ✅ (informativo) |
| **HRL Grassland 2018** (0/1) | 10 m | Ídem (`HRL_Grassland_2018`) | ✅ |
| **Copernicus DEM GLO-90** | 90 m | COG en AWS (`copernicus-dem-90m.s3.amazonaws.com`, ya accesible) | ✅ altitud, pendiente, umbría (informativo) |
| CORINE Land Cover 2018 | 100 m | MapServer EEA (`copernicus.discomap.eea.europa.eu`) | No: el HRL ya da bosque/pradera con más detalle |
| HRL Small Woody Features, Water & Wetness, Imperviousness | 5-10 m | ImageServer EEA | No (posibles: setos/riberas) |
| NDVI 300 m, LAI, FAPAR (CLMS vegetación) | 300 m, 10 días | Copernicus Data Space: **requiere cuenta y token** | No — ver siguiente paso |
| Soil Water Index / humedad superficial (CLMS) | 1 km, diario | CDSE / VITO: requiere cuenta | No (Open-Meteo ya da humedad del suelo) |

- **Interés del NDVI**: Olano et al. 2020, *Agric. For. Meteorol.* 288-289:108015 (Soria, *P. pinaster* y
  *P. sylvestris*, 22-24 años): el **NDVI del año anterior** fue el mejor predictor individual de la producción
  (r = 0,41-0,6) y la humedad del suelo por satélite igualó a la lluvia; clima + teledetección R² aj. ≈ 0,63.
  Es el candidato más prometedor para mejorar el modelo, pero necesita cuenta en Copernicus Data Space
  (o calcularlo con Sentinel-2 desde AWS, más trabajo).
- **Mapa Forestal de España** (MITECO, `wms.mapama.gob.es`): distingue especies de árbol (P. sylvestris,
  pinaster, nigra, Quercus, haya), que Copernicus no. Host añadido a la red, pero el servidor **no envía el
  certificado intermedio** (FNMT "AC Componentes Informáticos") → error TLS. No se desactiva la verificación;
  arreglo limpio: permitir `www.cert.fnmt.es` para descargar el intermedio, o usar las descargas MFE50 por provincia.
- Red: se añadieron al entorno `image.discomap.eea.europa.eu`, `copernicus.discomap.eea.europa.eu` y
  `wms.mapama.gob.es` (aprobado por Luis). `land.copernicus.eu` y `dataspace.copernicus.eu` siguen sin permitir.
- **Open-Meteo**: el 7-nov la IP de salida de la sesión de Claude devolvió "Daily API request limit exceeded"
  (la IP del proxy es compartida). Render no estaba afectado. Para pruebas locales, reutilizar la caché.

### Cómo se calcula
- `scripts/habitat_burgos.py` (se ejecuta a mano con rasterio/numpy en un venv; no va a Render) descarga los
  HRL a 0,001° (~100 m, vecino más próximo) y el DEM, y genera `static/habitat_burgos.json` (180 KB, 3 916
  subceldas de **0,02°** ≈ 1,7 × 2,2 km con: conífera, frondosa, pradera, densidad, altitud, pendiente, umbría).
- Comprobaciones: pinar de Canicosa 47 % coníferas; Arauzo 37 %; Montes Obarenes 68 % frondosas y 51 % umbría;
  Valle de Mena 58 % pradera; Ribera del Duero y Tierra de Campos casi sin bosque. Medias provinciales:
  coníferas 9 %, frondosas 17 %, pradera 14 %.
- Modelo v1: **índice = clima (celda de 8 × 11 km) × hábitat (subcelda de 2 km)**. Hábitat = fracción del
  hábitat de la especie / 0,3, máx. 1 (`modelo.HABITAT`; saturación del 30 % **supuesta**):
  níscalo, negrilla, angula → coníferas; boleto → coníferas + frondosas; oronja → frondosas;
  seta de cardo y senderuela → pradera (la seta de cardo puede infravalorarse: Copernicus no ve márgenes de cultivo).
- Altitud, pendiente, umbría y densidad **no puntúan todavía** (no hay cifras en la literatura revisada);
  se muestran en la ventana de detalle.
- Frontend: botón "Clima + hábitat / Solo clima" (se recuerda), subceldas dibujadas con canvas (repintado
  < 0,1 s), las subceldas sin hábitat quedan transparentes, la confianza del clima va en una capa encima.
  El cálculo clima × hábitat se hace en el navegador con los parámetros de `/api/especies` (una sola fuente).

- **502 de Render en frío**: justo tras un despliegue, mientras se recalcula (~1,5 min), el proxy de Render
  responde `502 upstream request timeout` a `/api/mapa`. El frontend reintenta cada 5 s (hasta 8 veces)
  ante 502/503/504 o corte de red, manteniendo la pantalla de carga. Verificado en Render: 2 502 reales → carga OK.

## 5f. Botón "Cómo llegar" (nov-2026)
- En la ventana de cada celda/subcelda: Google Maps, Apple Mapas, Waze; en Android también `geo:`
  (selector de apps del sistema); "Copiar coordenadas" (Wikiloc, OsmAnd…). Origen = ubicación actual
  (lo pone la app de navegación; la web no pide permiso de ubicación). Destino = **punto tocado**.
- Se inyecta en `popupopen` y se fija el nodo con `popup.setContent(nodo)`: llamar a `popup.update()`
  con contenido-función regenera el HTML y borra lo inyectado (error real encontrado).
- En móvil, `maxHeight` y `autoPanPadding` según el hueco que deja el panel inferior.
- Prueba: el HTML local se sirve en Playwright sobre los datos reales de Render (la sesión no puede
  calcular en local cuando se agota el cupo diario de Open-Meteo de su IP compartida).

## 5g. Validación con hallazgos reales de GBIF (nov-2026) — Fase 3a ✅

**Datos.** `scripts/gbif_descarga.py`: API `api.gbif.org/v1/occurrence/search` (sin clave), España,
lat 40-43,3 / lon −7,1 a −1,7 ("CyL ampliada"), 2000-2026, con coordenadas y sin problemas geoespaciales.
**2.408 registros** (níscalo 478, boleto 456, oronja 182, seta de cardo 338, negrilla 300, angula 76,
senderuela 578). Origen: Observation.org 1.145, iNaturalist 970, ARAN-Fungi 173, SIM-Fungal 30,
MA-Fungi 26, JCYL-Fungi (Junta CyL) 28… Licencias: CC BY-NC 2.318, CC BY 85, CC0 5 → uso no comercial con
cita. **En el repo solo se guardan agregados** (`static/validacion_gbif.json`), nunca los registros.
taxonKeys: 5248629, 5954958, 5240269, 9075265, 5241808, 8871787 (C. lutescens, sinónimo), 2537250.
Para una cita formal con DOI habría que generar una descarga con cuenta de GBIF (pendiente).

**Método** (`scripts/gbif_validacion.py`, se ejecuta a mano con rasterio/numpy):
1. *Hábitat*: factor de hábitat en una ventana de 0,02° alrededor de cada hallazgo (incertidumbre ≤ 1 km,
   1.089 hallazgos) frente a (a) puntos al azar en tierra española de la región y (b) hallazgos de las
   otras 6 especies (*target-group background*, corrige el sesgo de "dónde busca la gente"). AUC.
   HRL Forest Type y Grassland 2018 descargados para toda la región (5.400 × 3.300 px a 0,001°).
2. *Temporada*: reparto mensual de los hallazgos frente a los pesos mensuales del modelo.
3. *Clima*: 50 hallazgos con fecha por especie; índice climático (solo Open-Meteo) el día del hallazgo
   frente al **mismo día y lugar de otros 2 años** (época y sitio iguales: solo cambia el tiempo).
   % de pares que gana el hallazgo y prueba de signos. ~1.000 series de 45 días de Open-Meteo.

**Resultados.**
| Especie | AUC hábitat vs otras setas | Hallazgos sin hábitat (territorio) | Clima: gana el hallazgo | p |
|---|---|---|---|---|
| Níscalo | 0,75 | 11 % (55 %) | 59 % | 0,09 (indicios) |
| Boleto | 0,69 | 2 % (26 %) | 55 % | 0,30 |
| Oronja | 0,67 | 4 % (31 %) | **74 %** | < 0,001 |
| Seta de cardo | 0,64 | 2 % (8 %) | 52 % | 0,74 |
| Negrilla | 0,57 | 14 % (51 %) | 53 % | 0,60 |
| Angula | 0,64 (n = 34) | 9 % (51 %) | 47 % | 0,53 |
| Senderuela | 0,71 | 1 % (8 %) | **66 %** | 0,003 |

- **Hábitat**: señal en las 7 especies. Níscalo: 2,6 × más coníferas que los hallazgos de otras setas.
  Boleto: más ligado a frondosas (× 1,7) que a coníferas (× 1,1). Negrilla: apenas prefiere el pinar.
- **Temporada** (desajustes corregidos): oronja con máximo en agosto en el modelo → real 3 % en agosto,
  máximo sep-oct y 12 % en junio; níscalo: septiembre solo 3 %, máximo en noviembre; angula y negrilla
  desde octubre; senderuela con salida otoñal que llega a diciembre.
- **Clima**: efecto demostrado en oronja y senderuela (el agua es el factor con señal); indicios en el
  níscalo (temperatura y heladas tienen señal, la lluvia poca); **sin señal** en boleto, seta de cardo,
  negrilla y angula.

**Cambios aplicados (solo los respaldados por los datos):**
- `ESPECIES[*]["fenologia"]` = reparto mensual real normalizado al mes máximo (meses < 2 % a 0).
  Sesgo: más observadores en otoño. El solapamiento real/modelo pasa a 0,95-0,99 (en la misma muestra).
- `HABITAT`: boleto "frondosas + ½ coníferas"; saturación por especie (regla: mayor AUC; si la ganancia
  < 0,01, la que deja menos hallazgos sin hábitat): níscalo, seta de cardo y senderuela 0,3; boleto y
  oronja 0,5; negrilla y angula 0,2.
- **Clima: sin cambios.** Se exploraron ventanas de lluvia, objetivos y rangos térmicos eligiendo en
  una mitad de los hallazgos y comprobando en la otra: ninguna mejora se sostuvo fuera de la muestra.
- La app muestra junto al selector "Comprobado con hallazgos reales: hábitat … · efecto del tiempo …"
  (icono + texto) y, si el efecto del tiempo no está demostrado, aconseja usar el mapa para el dónde y el
  cuándo. Detalle en "Cómo se calcula y fuentes" → "Validación con hallazgos reales (GBIF)".

**Limitaciones y siguientes pasos de validación:** datos de solo presencia y sesgados (accesibilidad,
fines de semana); la fecha es la de observación, no la de inicio de la salida; 50 hallazgos por especie
para el clima es poco (ampliar a todos los registros con fecha costaría ~5 000 llamadas a Open-Meteo:
repartir en varios días). Con más muestra se podría recalibrar el clima por especie.
Problema técnico: el proxy de la sesión corta conexiones si se abren cientos seguidas → reutilizar un
único `httpx.AsyncClient` (`openmeteo.diarios(..., client=)`).

## 6. Hoja de ruta acordada (por fases)

### Fase 1 — Piloto Burgos ✅ (§4-§5d)
Clientes AEMET y Open-Meteo, validación AEMET vs Open-Meteo, modelo v0, mapa de calor, UX.

### Fase 2 — Hábitat ✅ (§5e)
Copernicus HRL (coníferas/frondosas/praderas) + DEM en submalla de 2 km; botón "Cómo llegar" (§5f).
Pendiente de Fase 2, menor: SoilGrids, Mapa Forestal de España (ver Fase 3d).

### Fase 3 — Fiabilidad: validar contra la realidad (SIGUIENTE, análisis nov-2026)

**Diagnóstico.** El modelo tiene una base meteorológica contrastada (AEMET vs Open-Meteo) y un hábitat
razonable, pero **nunca se ha comparado con setas reales**: todos los pesos, umbrales y ventanas
fenológicas son literatura + supuestos. Mientras no se valide, añadir más capas (o más provincias)
multiplica una salida sin calibrar. Por eso la prioridad es conseguir "verdad terreno", no más predictores.

Orden propuesto (de más a menos valor/esfuerzo):

**3a. Observaciones reales de GBIF — ✅ HECHO (§5g).** GBIF agrega registros de presencia con fecha y
coordenadas (iNaturalist, Sociedad Micológica Ibérica, Flora Mycologica Iberica, herbarios). Licencias
CC0 / CC BY / CC BY-NC por registro. API pública sin clave (`api.gbif.org`, **falta añadir el host**).
*L. deliciosus* tiene taxonKey 5248629; *B. edulis* tiene decenas de miles de registros en Europa.
- Validar el **hábitat**: ¿caen los registros de cada especie en subceldas con hábitat alto? (AUC, o
  % de registros con factor ≥ 0,5 frente al % de superficie con ese factor).
- Calibrar la **fenología**: meses reales de los registros en CyL y norte de España → sustituir las
  ventanas mensuales supuestas.
- Validar el **clima**: para cada registro con fecha, calcular el índice climático de ese día con
  Open-Meteo Historical (hay datos desde 1940) y compararlo con días/lugares sin registro (fondo).
  Ojo: datos de solo presencia y sesgados hacia zonas visitadas y fines de semana; sirve para ordenar
  y calibrar, no como probabilidad absoluta.
- Esfuerzo: medio. Coste en Open-Meteo: moderado (agrupar por celda y fecha; cachear).

**3b. Retrovalidación con los partes de Micocyl (prioridad 2).** Los partes (PDF semanales/quincenales
en micocyl.es, desde ~2018) describen por provincia si la campaña va bien o mal y traen gráficos de
producción de parcelas. Extraer a mano o semiautomáticamente una serie ordinal por provincia y semana
(mala / regular / buena) y comparar con el índice medio de Burgos y Soria recalculado para esas fechas.
Permite ajustar el objetivo de lluvia, los retardos y la penalización por heladas. Las series de
parcelas de la Junta no son públicas: valdría la pena **pedírselas a Micocyl** (Martínez Peña, CESEFOR).
Host necesario: `www.micocyl.es` / `micocyl.es`.

**3c. Pronóstico real a 7-15 días (prioridad 3, mejora de uso).** Hoy el mapa describe el pasado
(datos hasta ayer). La API de previsión de Open-Meteo (`api.open-meteo.com`, ya permitida) da hasta
16 días (ECMWF IFS hasta 15) con humedad del suelo. Con ella: "si llueve lo previsto, el níscalo
mejorará en la semana del…". Debe mostrarse con menor confianza que lo observado. Esfuerzo bajo-medio.

**3d. Nuevos predictores (prioridad 4, tras validar).**
- **NDVI del año anterior** (Olano et al. 2020: mejor predictor individual, r = 0,41-0,6). CLMS NDVI
  300 m en Copernicus Data Space (requiere cuenta → network secret) o Sentinel-2 vía AWS.
- **Mapa Forestal de España** (especie de árbol: *P. sylvestris* / *pinaster* / *nigra*, *Quercus*,
  haya). Requiere permitir `www.cert.fnmt.es` (certificado intermedio) o las descargas MFE50.
- **SoilGrids pH** (`rest.isric.org`, ya permitido): Taye et al. 2016 halló más níscalo en suelos ácidos.
- Altitud y umbría ya están calculadas; activarlas como factor solo si 3a/3b muestran efecto.

**3e. Escalar a otras provincias (después de 3a-3b).** Ver §6.1.

### 6.1 Selector de provincias / regiones (diseño, pendiente)
- Pantalla inicial con el mapa de CyL (o de España) y las provincias disponibles; se elige una antes de
  pedir nada a AEMET ni a Open-Meteo. Recordar la última elección; `?provincia=SORIA` en la URL.
- Backend ya parametrizado por provincia en casi todo (`mapa.CONTORNOS`, `validacion.validar`); falta:
  contornos de cada provincia (es-atlas los tiene todos), `scripts/habitat_<prov>.py` generalizado,
  caché y candado por provincia, precálculo en arranque solo de la última pedida.
- Coste: cada provincia ≈ 150-250 celdas (≈ 500-800 "llamadas" Open-Meteo) + 10-20 estaciones AEMET
  (≈ 40-60 peticiones). Con el plan gratuito de Render y el límite de 10 000 llamadas/día de
  Open-Meteo, caben varias provincias al día, pero no las 9 de CyL recalculándose cada 6 h.

### 6.2 Propuesta (nov-2026): GBIF completo, Micocyl y todas las setas recolectables de Burgos

**GBIF con cuenta.** La cuenta NO da más registros que la API pública (las coordenadas ocultadas por
iNaturalist siguen ocultas): da **descargas masivas asíncronas sin límite** y un **DOI** para citar.
Dos vías: (a) Luis hace la descarga en gbif.org con los filtros indicados y pega en el chat el enlace o
el DOI (no es secreto); el zip es público (`api.gbif.org/v1/occurrence/download/request/<clave>.zip`,
puede redirigir a otro host que habría que permitir). (b) Usuario/contraseña de GBIF como network secret
(Basic) para `api.gbif.org` con `request_credential`; Claude lanza `POST /v1/occurrence/download/request`
con un predicado. Región: Fungi (taxonKey 5), ES, lat 40-43,3, lon −7,1 a −1,7, 2000-2026, con
coordenadas y sin problemas geoespaciales → **161 055 registros, ~2 000 especies** (26 557 en Burgos).

**Micocyl.** No hay API ni cuenta: los partes son PDF públicos en `micocyl.es` / `www.micocyl.es`
(hay que permitir esos hosts). Plan: listar y descargar los partes, extraer texto (pdftotext),
codificar a mano o semiautomáticamente una serie ordinal por provincia y quincena (mala/regular/buena)
y compararla con el índice recalculado. Las series de producción de parcelas no son públicas: pedirlas
por correo a Micocyl/Cesefor. Además, IDECyL publica gratis "Micología CyL: zonas reguladas"
(shapefile de acotados y parques micológicos, `idecyl.jcyl.es`): útil para avisar en el mapa de dónde
hace falta permiso.

**Todas las setas recolectables.** Especies comestibles con ≥ 70 registros en CyL ampliada (2000-2026),
por temporada según el reparto mensual real de GBIF:
- Final de invierno: *Hygrophorus marzuolus* (feb-abr, 90; Burgos 19), *Flammulina velutipes* (nov-feb).
- Primavera: *Morchella esculenta* (abr 71 %), *Calocybe gambosa* (abr-may, 175; Burgos 50),
  *Marasmius oreades*, *Pleurotus eryngii*, *Coprinus comatus*, *Boletus pinophilus* (may-jun y otoño).
- Verano: *Boletus reticulatus* (may-jul), *B. aereus*, *Russula virescens*, *R. cyanoxantha*,
  *Cantharellus cibarius* (jun-jul y otoño), *Amanita caesarea* (jun y sep-oct).
- Otoño: *Macrolepiota procera* (989), *Lactarius deliciosus*, *Boletus edulis*, *Suillus luteus*,
  *Agaricus campestris*, *Hydnum repandum*, *Craterellus cornucopioides*, *Pleurotus ostreatus*.
- Otoño tardío-invierno: *Lepista nuda*, *Tricholoma terreum*, *T. portentosum*, *Clitocybe geotropa*,
  *Hygrophorus russula*, *Craterellus lutescens*, *C. tubaeformis*, *Lepista personata/panaeola*.
- Excluir: *Tricholoma equestre* (tóxica, rabdomiólisis; no comercializable). Pocas observaciones:
  *Lactarius sanguifluus*, *Hygrophorus latitabundus*, trufas, *Terfezia*.
Diseño: perfiles generados a partir de los datos (temporada = meses de GBIF; hábitat = asociación
medida con Copernicus), clima por **grupo funcional** (micorrícico de pino, de frondosas, saprótrofo de
pradera, de madera, primaveral) para tener muestra suficiente, y **aviso de confusiones peligrosas**
por especie (p. ej. champiñón ↔ *Amanita* blancas mortales, perretxiko ↔ *Entoloma sinuatum* e
*Inocybe*, senderuela ↔ *Clitocybe* blancas, colmenilla ↔ *Gyromitra*, rebozuelo ↔ *Omphalotus*,
parasol ↔ *Lepiota* pequeñas). La app nunca debe servir para identificar setas.

## 7. Forma de trabajar con Luis
- Responder en español, explicar paso a paso, ser claro sobre qué es riguroso y qué es aproximación.
- Prefiere avanzar rápido y que Claude cierre el ciclo de feedback por sí mismo
  (probar en local, subir, verificar la URL de Render) en vez de pedirle capturas.
- Commits pequeños y descriptivos; push a `main` dispara el despliegue en Render.
- No pedir ni escribir claves en el chat. Recordar que la clave AEMET pegada en la
  conversación anterior debe revocarse (el usuario debería generar una nueva).
