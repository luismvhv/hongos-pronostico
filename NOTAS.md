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
static/
  index.html   # mapa Leaflet (ahora solo pinta estaciones)
requirements.txt  .env.example  .gitignore  NOTAS.md
```

### Endpoints
| Ruta | Estado | Qué hace |
|---|---|---|
| `GET /` | ✅ funciona | Mapa Leaflet con las estaciones de CyL |
| `GET /api/estaciones?provincias=BURGOS,SORIA` | ✅ verificado | Inventario AEMET con lat/lon decimales |
| `GET /api/diarios/{indicativo}?dias=30` | ✅ verificado | Valores diarios: tmed, tmin, tmax, prec, hr, sol |
| `GET /api/comparar?provincias=BURGOS&dias=21` | ⚠️ subido, **sin verificar** | Por estación: lluvia acumulada, días con lluvia, heladas (tmin ≤ 0), tmed media, sol medio; ordenado por lluvia |

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

Burgos tiene 14 estaciones climatológicas en el inventario (indicativos: 2106B, 2117D, 2285B,
2290Y, 2298, 2302N, 2311Y, 2331 [Burgos Aeropuerto], 9012E, 9027X, 9031C, 9051, 9069C, 9111).

Dato real observado (Burgos Aeropuerto, 7 oct – 3 nov 2026): solo ~4.6 mm de lluvia en 30 días,
heladas el 24/10, 31/10 y 1/11 (mín. -2.9 °C), mucho sol. Coherente con una campaña pobre.

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

## 6. Hoja de ruta acordada (por fases)

### Fase 1 — Piloto Burgos (EN CURSO)
1. ✅ Cliente AEMET + estaciones + diarios.
2. ⚠️ Verificar `/api/comparar` en Render.
3. ⏭️ **Integrar Open-Meteo Historical Weather API** (`archive-api.open-meteo.com`, sin clave,
   reanálisis ERA5/ERA5-Land ~10 km): temperatura, precipitación, **humedad relativa**,
   **humedad del suelo** (`soil_moisture_*`), quizá ET0. Confirmar nombres de parámetros
   y condiciones de uso contra su documentación antes de codificar.
4. ⏭️ **Validación AEMET vs Open-Meteo** en las 14 estaciones de Burgos (mismas fechas y coords):
   - Temperatura: MAE y sesgo. Umbral provisional: MAE < 2 °C → confianza alta.
   - Lluvia: acierto llovió/no llovió y ratio de acumulados. Umbral provisional: acierto > 75 %.
   - Si se supera un umbral → confianza media/baja y **mensaje visible** en el mapa
     ("el modelo diverge de AEMET en esta zona; la estimación es menos fiable").
   - Ponderación: cerca de una estación AEMET pesa más el dato real; lejos, Open-Meteo
     con menor confianza. Umbrales provisionales: ajustar con datos reales.
5. ⏭️ **Modelo de favorabilidad v0** por especie (reglas de la literatura): lluvia acumulada en
   ventanas (7/14/21/30 días), días sin helada, tmin/tmax en rango, humedad del suelo, sol.
   Salida 0-100 %.
6. ⏭️ **Mapa de calor de Burgos**: malla de puntos sobre la provincia, puntuación por punto,
   capa coloreada en Leaflet, selector de especie, leyenda y aviso de confianza.

### Fase 2 — Capas de terreno
- **SoilGrids** (ISRIC, `rest.isric.org`): textura, pH, materia orgánica, retención de agua.
- **Cobertura forestal** de OSM vía Overpass (`landuse=forest`, `natural=wood`, `leaf_type`)
  para descartar celdas sin bosque y asociar especie ↔ tipo de bosque (pinar ↔ níscalo, etc.).
  Alternativa: Copernicus Land Monitoring. Altitud/orientación: Copernicus DEM / SRTM.

### Fase 3 — Calibración
- Partes micológicos oficiales (micocyl.es, Montes de Soria, etc.) para calibrar y validar.
- Extender a toda Castilla y León y luego a la península.

## 7. Forma de trabajar con Luis
- Responder en español, explicar paso a paso, ser claro sobre qué es riguroso y qué es aproximación.
- Prefiere avanzar rápido y que Claude cierre el ciclo de feedback por sí mismo
  (probar en local, subir, verificar la URL de Render) en vez de pedirle capturas.
- Commits pequeños y descriptivos; push a `main` dispara el despliegue en Render.
- No pedir ni escribir claves en el chat. Recordar que la clave AEMET pegada en la
  conversación anterior debe revocarse (el usuario debería generar una nueva).
