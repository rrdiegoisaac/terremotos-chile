"""Carga de datos, filtros y clasificación por zona, compartida por todo el análisis."""

import json
import sqlite3
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import shapely

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
DB = RAIZ_PROYECTO / "data" / "sismos.db"
PAISES_GEOJSON = RAIZ_PROYECTO / "data" / "fronteras" / "paises_50m.geojson"


# Zonas de norte a sur. Límites de latitud aproximados a las macrozonas de Chile:
# Norte Grande: Arica a Antofagasta · Norte Chico: Atacama y Coquimbo
# Centro: Valparaíso a Biobío · Sur: Araucanía a Los Lagos · Austral: Aysén y Magallanes
ZONAS = [
    ("Norte Grande", -26.0, 0.0),
    ("Norte Chico", -32.2, -26.0),
    ("Centro", -38.5, -32.2),
    ("Sur", -44.0, -38.5),
    ("Austral", -56.0, -44.0),
    ("Antártica y Drake", -90.0, -56.0),
]
ORDEN_ZONAS = [z[0] for z in ZONAS] + ["Oceánico"]

# Recuadro regional (lat_min, lat_max, lon_min, lon_max): deja fuera los grandes sismos
# lejanos (Asia, Oceanía) que el catálogo incluía en sus primeros años
RECUADRO_REGIONAL = (-66.0, -17.0, -120.0, -40.0)

# Sismos cuyo epicentro cae en tierra de estos países se excluyen (se dejan Chile,
# el mar y la Antártica). Fronteras de Natural Earth, escala 1:50 millones.
PAISES_EXCLUIDOS = {"Argentina", "Bolivia", "Peru", "Brazil", "Paraguay", "Uruguay", "Falkland Is."}
# En el mar, el límite con Perú: los sismos costa afuera al norte de este paralelo están en aguas peruanas
LAT_LIMITE_MARITIMO_PERU = -18.35

# Casi duplicados: el mismo sismo publicado dos veces con informes distintos
DUPLICADO_SEGUNDOS = 5
DUPLICADO_GRADOS = 0.1
DUPLICADO_MAGNITUD = 0.3

# Sismos más al oeste que esto están lejos de la fosa (Juan Fernández, Pascua, dorsales)
LONGITUD_OCEANICA = -78.0


def clasificar_zona(latitud: float, longitud: float) -> str:
    if longitud < LONGITUD_OCEANICA:
        return "Oceánico"
    for nombre, lat_min, lat_max in ZONAS:
        if lat_min < latitud <= lat_max:
            return nombre
    return "Antártica y Drake"


@lru_cache(maxsize=1)
def _poligonos() -> tuple:
    """(Chile, países excluidos) como geometrías de shapely, preparadas para consultas rápidas."""
    datos = json.loads(PAISES_GEOJSON.read_text(encoding="utf-8"))
    chile, otros = [], []
    for f in datos["features"]:
        geom = shapely.geometry.shape(f["geometry"])
        if f["properties"]["nombre"] == "Chile":
            chile.append(geom)
        elif f["properties"]["nombre"] in PAISES_EXCLUIDOS:
            otros.append(geom)
    chile, otros = shapely.union_all(chile), shapely.union_all(otros)
    shapely.prepare(chile)
    shapely.prepare(otros)
    return chile, otros


def en_territorio_analizado(latitud: pd.Series, longitud: pd.Series) -> pd.Series:
    """True si el epicentro está en Chile, en el mar frente a Chile o en la Antártica."""
    chile, otros = _poligonos()
    x, y = longitud.to_numpy(), latitud.to_numpy()
    en_otro_pais = shapely.contains_xy(otros, x, y)
    en_chile = shapely.contains_xy(chile, x, y)
    mar_peruano = ~en_chile & (y > LAT_LIMITE_MARITIMO_PERU)
    return pd.Series(~en_otro_pais & ~mar_peruano, index=latitud.index)


def quitar_casi_duplicados(df: pd.DataFrame) -> pd.DataFrame:
    """Elimina el segundo de dos registros consecutivos que son el mismo sismo."""
    df = df.sort_values("fecha_utc")
    segundos = df.fecha_utc.diff().dt.total_seconds()
    cerca = (df.latitud.diff().abs() < DUPLICADO_GRADOS) & (df.longitud.diff().abs() < DUPLICADO_GRADOS)
    parecido = df.magnitud.diff().abs() < DUPLICADO_MAGNITUD
    duplicado = (segundos <= DUPLICADO_SEGUNDOS) & cerca & parecido
    return df[~duplicado]


@lru_cache(maxsize=4)
def _leer_cache(desde: str, hasta: str) -> pd.DataFrame:
    with sqlite3.connect(DB) as conn:
        df = pd.read_sql(
            "SELECT * FROM sismos WHERE dia_catalogo BETWEEN ? AND ? ORDER BY fecha_utc",
            conn,
            params=(desde, hasta),
            parse_dates=["fecha_utc", "fecha_local"],
        )
    df = quitar_casi_duplicados(df)
    lat_min, lat_max, lon_min, lon_max = RECUADRO_REGIONAL
    en_region = df.latitud.between(lat_min, lat_max) & df.longitud.between(lon_min, lon_max)
    df = df[en_region]
    df = df[en_territorio_analizado(df.latitud, df.longitud)].reset_index(drop=True)
    df["zona"] = pd.Categorical(
        [clasificar_zona(lat, lon) for lat, lon in zip(df.latitud, df.longitud)],
        categories=ORDEN_ZONAS,
        ordered=True,
    )
    return df


def _leer(desde: str, hasta: str) -> pd.DataFrame:
    # Copia, para que quien la modifique no altere la versión guardada en caché
    return _leer_cache(desde, hasta).copy()


def periodo_continuo() -> tuple[str, str]:
    """Tramo más reciente de días descargados sin huecos (AAAA-MM-DD, AAAA-MM-DD).

    Permite que el análisis crezca solo a medida que se descargan más años.
    """
    with sqlite3.connect(DB) as conn:
        dias = pd.to_datetime(
            pd.read_sql("SELECT dia FROM dias_scrapeados WHERE estado = 'ok' ORDER BY dia", conn).dia
        )
    corte = dias.diff().dt.days.gt(1)
    inicio = dias[corte].iloc[-1] if corte.any() else dias.iloc[0]
    return inicio.strftime("%Y-%m-%d"), dias.iloc[-1].strftime("%Y-%m-%d")


# Catálogo completo descargado (tramo continuo). Crece solo al descargar más años.
DESDE_CATALOGO, HASTA = periodo_continuo()

# Criterio de cobertura estable: el Norte Grande (la zona más activa) debe registrar al
# menos este porcentaje de su nivel reciente de sismos de magnitud >= 4 por año
PCT_COBERTURA_ESTABLE = 75
ANIOS_NIVEL_RECIENTE = 10


def inicio_red_estable() -> int:
    """Primer año desde el cual la red registra el norte de forma estable.

    En los primeros años del catálogo el CSN casi no tenía estaciones en el norte:
    faltan incluso sismos grandes. Se calcula la tasa anual de sismos de magnitud
    >= 4 en el Norte Grande y se busca el primer año desde el cual todos los años
    superan el PCT_COBERTURA_ESTABLE % de la mediana de los últimos años completos.
    """
    df = _leer(DESDE_CATALOGO, HASTA)
    fin = pd.Timestamp(HASTA)
    norte = df[(df.zona == "Norte Grande") & (df.magnitud >= 4)]
    tasas = {}
    for anio in range(pd.Timestamp(DESDE_CATALOGO).year, fin.year + 1):
        dias = (min(fin, pd.Timestamp(f"{anio}-12-31")) - max(pd.Timestamp(DESDE_CATALOGO), pd.Timestamp(f"{anio}-01-01"))).days + 1
        tasas[anio] = (norte.fecha_utc.dt.year == anio).sum() / dias * 365.25
    completos = [a for a in tasas if a < fin.year]
    nivel = np.median([tasas[a] for a in completos[-ANIOS_NIVEL_RECIENTE:]])
    anios = sorted(tasas)
    for i, anio in enumerate(anios):
        if all(tasas[a] >= nivel * PCT_COBERTURA_ESTABLE / 100 for a in anios[i:]):
            return anio
    return anios[-1]


# Período de análisis: desde que la red cubre el país de forma estable
DESDE = f"{inicio_red_estable()}-01-01"

# Las comparaciones en el tiempo terminan antes del cambio de método de magnitud del CSN
# (Ml → Mlv), que se generaliza desde fines de enero de 2026
FIN_COMPARACION_TEMPORAL = "2025-12-31"


def cargar_sismos(desde: str = DESDE, hasta: str = HASTA) -> pd.DataFrame:
    return _leer(desde, hasta)
