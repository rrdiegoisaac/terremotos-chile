-- Consultas de exploración sobre data/sismos.db (SQLite 3.25 o superior, por las funciones de ventana).
-- Se pueden ejecutar en DB Browser for SQLite, DBeaver o con: sqlite3 data/sismos.db < consultas.sql


-- 1. Sismos de magnitud 4 o más por año, y variación respecto del año anterior (LAG)
WITH anual AS (
    SELECT strftime('%Y', fecha_utc) AS anio,
           COUNT(*)                   AS sismos_m4
    FROM sismos
    WHERE magnitud >= 4
    GROUP BY anio
)
SELECT anio,
       sismos_m4,
       sismos_m4 - LAG(sismos_m4) OVER (ORDER BY anio) AS cambio_vs_anio_anterior
FROM anual
ORDER BY anio;


-- 2. Los tres sismos más fuertes de cada año (ROW_NUMBER por partición)
WITH ranking AS (
    SELECT strftime('%Y', fecha_utc) AS anio,
           fecha_utc,
           magnitud,
           lugar,
           ROW_NUMBER() OVER (PARTITION BY strftime('%Y', fecha_utc) ORDER BY magnitud DESC) AS puesto
    FROM sismos
)
SELECT anio, puesto, fecha_utc, magnitud, lugar
FROM ranking
WHERE puesto <= 3
ORDER BY anio, puesto;


-- 3. Los diez días con más sismos registrados (todas las magnitudes)
SELECT date(fecha_utc) AS dia,
       COUNT(*)        AS sismos,
       MAX(magnitud)   AS magnitud_maxima
FROM sismos
GROUP BY dia
ORDER BY sismos DESC
LIMIT 10;


-- 4. Qué escala de magnitud usa el CSN en los sismos M4+, por año (% sobre el total del año)
WITH por_tipo AS (
    SELECT strftime('%Y', fecha_utc) AS anio,
           tipo_magnitud,
           COUNT(*)                   AS sismos
    FROM sismos
    WHERE magnitud >= 4
    GROUP BY anio, tipo_magnitud
)
SELECT anio,
       tipo_magnitud,
       sismos,
       ROUND(100.0 * sismos / SUM(sismos) OVER (PARTITION BY anio), 1) AS pct_del_anio
FROM por_tipo
ORDER BY anio, sismos DESC;


-- 5. Promedio móvil de 12 meses de los sismos M4+ por mes (ventana con marco de filas)
WITH mensual AS (
    SELECT strftime('%Y-%m', fecha_utc) AS mes,
           COUNT(*)                      AS sismos_m4
    FROM sismos
    WHERE magnitud >= 4
    GROUP BY mes
)
SELECT mes,
       sismos_m4,
       ROUND(AVG(sismos_m4) OVER (ORDER BY mes ROWS BETWEEN 11 PRECEDING AND CURRENT ROW), 1) AS promedio_12_meses
FROM mensual
ORDER BY mes;


-- 6. Días descargados sin sismos (para detectar huecos de la fuente)
SELECT dia, estado
FROM dias_scrapeados
WHERE n_sismos = 0 AND dia >= '2008-01-01'
ORDER BY dia;
