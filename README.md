# Terremotos en Chile, 2000–2026

¿Dónde tiembla más en Chile, qué tan fuerte, a qué profundidad y qué pasa después de un gran terremoto? Este proyecto responde esas preguntas con el catálogo completo del **Centro Sismológico Nacional (CSN)** desde el año 2000: unos 157.000 registros obtenidos con web scraping, guardados en SQLite y analizados con Python. También muestra cuánto cambió el propio catálogo en ese tiempo.

El resultado es una nota interactiva, con gráficos y explicación de cada hallazgo, publicada en mi portafolio.

- **Nota interactiva:** _(enlace al portafolio, próximamente)_
- **Dataset en Kaggle:** _(próximamente)_

> Es un proyecto que vengo desarrollando desde 2024. La primera versión partió de un dataset público de Kaggle; esta la rehice desde cero, con los datos obtenidos directamente del CSN y un tratamiento explícito de sus limitaciones.

## Hallazgos principales

- **El norte tiene más actividad de fondo.** Con todas las magnitudes, el Norte Grande concentra la mitad del catálogo, pero esa cifra exagera: allí la red detecta más sismos pequeños. Con sismos de magnitud 4 o más, y sin las secuencias de los grandes terremotos, el Norte Grande registra ~1,7 veces más sismos por grado de latitud que la zona central o el Norte Chico.
- **En el norte también tiembla más profundo.** La profundidad típica en el Norte Grande es de 106 km, y el 76% de sus sismos ocurre a más de 70 km, dentro de la placa de Nazca que se hunde bajo el continente. Mientras más lejos de la fosa, más profundo el sismo.
- **Tres terremotos dominan el período:** Maule 2010 (8,8), Illapel 2015 (8,4) e Iquique 2014 (8,2). Iquique tuvo una intensa secuencia previa: 105 sismos de magnitud 4 o más en el mes anterior, cuando lo normal eran 2 o 3.
- **El catálogo cambió más que la Tierra.** Antes de 2008 casi no registra el norte, desde 2019 casi no publica sismos bajo magnitud 2,5, la proporción de magnitudes medidas en Mw pasó de ~0% a 30–50%, y en 2026 el CSN adoptó el método Mlv. Con esos cambios, los datos no muestran una tendencia concluyente en la actividad.

## Cómo está hecho

```
sismologia.cl ──► scraper (requests + BeautifulSoup) ──► SQLite ──► análisis (pandas, shapely) ──► JSON ──► gráficos (React + Recharts)
```

1. **Scraping.** El CSN publica una página por día. El scraper recorre ~9.800 días, extrae cada sismo y lo guarda en SQLite. Es reanudable: cada día se guarda en una sola transacción junto con su registro de avance, así que si se corta sigue donde quedó, sin duplicar datos. Distingue los días sin sismos de las páginas sin la tabla esperada, y hace pausas entre peticiones para no sobrecargar el sitio.
2. **Limpieza y control de calidad.**
   - Se filtran los sismos lejanos (Asia, Oceanía) y los que ocurren en tierra de países vecinos, con las fronteras de Natural Earth.
   - Se eliminan los casi duplicados.
   - Se documentan los huecos de la fuente y los cambios de red, de escala y de método.
3. **Análisis.**
   - Distribución por zona y latitud, y valor b de Gutenberg-Richter.
   - Profundidad, y distancia a la fosa con el modelo de placas PB2002.
   - Secuencias de réplicas de los grandes terremotos, con dos referencias de actividad normal e intervalos de Poisson.
   - Prueba de tendencia de Mann-Kendall.
4. **Exportación.** Cada sección genera un JSON resumido que consumen los gráficos de la nota.

## Estructura

```
scraper/
  scrape_catalogo.py   Descarga el catálogo diario del CSN a SQLite
analisis/
  datos.py             Carga, filtros (región, países, duplicados), zonas y período de análisis
  estadistica.py       Magnitud de completitud, valor b y prueba de Mann-Kendall
  placas.py            Distancia de cada sismo al límite de placas más cercano (PB2002)
  secuencias.py        Secuencias de réplicas de los grandes terremotos
  exportar.py          Calcula cada sección y exporta los JSON
tests/                 Pruebas de las funciones principales (pytest)
consultas.sql          Consultas de exploración con CTE y funciones de ventana
data/
  sismos.db            Base SQLite (no se incluye en el repo: se regenera con el scraper)
  pb2002/              Límites de placas tectónicas (Bird, 2003)
  fronteras/           Países de Natural Earth (región de Chile)
export/                Resultados resumidos (JSON) para los gráficos
```

La base `sismos.db` tiene dos tablas:

| Tabla | Contenido |
|---|---|
| `sismos` | Un registro por sismo: fecha local y UTC, lugar de referencia, latitud, longitud, profundidad, magnitud y tipo de magnitud. `informe_url` es el identificador único del CSN. |
| `dias_scrapeados` | Control de avance del scraper: día, cantidad de sismos y estado (`ok`, `sin_pagina`, `sin_tabla`). |

## Cómo reproducirlo

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (en macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt

python scraper/scrape_catalogo.py --pausa 5     # descarga 2000 → ayer (~12 horas)
python analisis/exportar.py                     # genera export/*.json

pip install -r requirements-dev.txt
python -m pytest                                # pruebas
```

El scraper acepta un rango de fechas (`--desde 2025-01-01 --hasta 2025-12-31`) y, si se interrumpe, al volver a ejecutarlo sigue desde el último día guardado. Para probar el análisis sin esperar la descarga completa, basta con bajar uno o dos años.

## Decisiones de análisis

- **Período.** El catálogo completo (desde 2000) se usa para mostrar cómo cambió el registro. El resto del análisis parte en el primer año desde el cual el Norte Grande registra siempre al menos el 75% de su nivel reciente de sismos de magnitud 4 o más. Con los datos actuales ese año es 2008, y se calcula automáticamente en `datos.py`. Las comparaciones en el tiempo terminan en 2025, antes del cambio de método del CSN.
- **Comparaciones entre zonas y años.** Solo con sismos de magnitud 4 o más. La Antártica y el Paso Drake se dejan fuera de las comparaciones de tasa: el catálogo solo los registra alrededor de grandes secuencias.
- **Territorio.**
  - Se excluyen los epicentros en tierra de Argentina, Bolivia, Perú y otros países vecinos (Natural Earth, 1:50 millones), y los del mar frente a Perú (al norte de 18,35°S).
  - Las zonas son seis franjas de latitud (del Norte Grande a la Antártica y el Paso Drake), más una categoría oceánica.
- **Grandes terremotos.**
  - **Selección:** se eligen automáticamente los tres más fuertes del territorio analizado.
  - **Radio:** la mitad del largo típico de ruptura (Wells y Coppersmith, 1994) más 50 km, centrado en las réplicas del primer mes.
  - **Qué se cuenta:** sismos de magnitud 4 o más y hasta 70 km de profundidad.
  - **Actividad normal:** con dos referencias, el año previo sin el último mes y la mediana de largo plazo sin secuencias.
- **Distancias a la fosa.** Proyección centrada en el meridiano 70°O; el error es menor a 1 km en el 90% de los casos, según una comparación con haversine.

## Limitaciones conocidas

- **Días vacíos:** en el sitio del CSN, las páginas del 31 de diciembre de 2001 a 2019 y la del 18 de enero de 2009 aparecen sin sismos.
- **Réplicas incompletas:** en los días posteriores a un gran terremoto, sobre todo el del Maule, el catálogo no registró todas las réplicas. Esas cifras son un piso.
- **Magnitudes:** se usan tal como las publica el CSN, que combina distintas escalas (Ml, Mlv, Mw, entre otras). Eso afecta las comparaciones de largo plazo.
- **Completitud:** el método de máxima curvatura no distingue la capacidad de detección de la red del piso de publicación de magnitud 2,5.

## Fuentes

- **Datos sísmicos:** Centro Sismológico Nacional, Universidad de Chile. <https://www.sismologia.cl>
- **Límites de placas:** Bird, P. (2003). *An updated digital model of plate boundaries.* Geochemistry, Geophysics, Geosystems, 4(3), 1027. <https://doi.org/10.1029/2001GC000252>. Versión GeoJSON de Hugo Ahlenius (Nordpil), bajo licencia [ODC-By](https://opendatacommons.org/licenses/by/1-0/): <https://github.com/fraxen/tectonicplates>
- **Fronteras:** Natural Earth, dominio público. <https://www.naturalearthdata.com>
- **Largo de ruptura:** Wells, D. y Coppersmith, K. (1994). *New empirical relationships among magnitude, rupture length, rupture width, rupture area, and surface displacement.* BSSA, 84(4), 974–1002. <https://doi.org/10.1785/BSSA0840040974>
- **Ley de Gutenberg-Richter:** Gutenberg, B. y Richter, C. F. (1944). *Frequency of earthquakes in California.* BSSA, 34(4), 185–188. <https://doi.org/10.1785/BSSA0340040185>
- **Secuencia previa de Iquique 2014:**
  - Ruiz, S. y otros (2014), *Science*, 345(6201), 1165–1169. <https://doi.org/10.1126/science.1256074>
  - Schurr, B. y otros (2014), *Nature*, 512, 299–302. <https://doi.org/10.1038/nature13681>
- **Profundidad de los sismos:** USGS Earthquake Hazards Program.

## Autor

**Diego Riquelme**, Data Analyst · [GitHub](https://github.com/rrdiegoisaac)
