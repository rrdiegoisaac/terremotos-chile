"""
Cruce de los sismos con los límites de placas del modelo PB2002 (Bird, 2003).

Cada sismo se asigna al límite de placas oceánico más cercano a su epicentro.
No se usa "la placa donde cae el epicentro" porque en una zona de subducción
el epicentro queda sobre la placa continental aunque el sismo ocurra dentro de
la placa oceánica que se hunde.
"""

import json

import numpy as np
import pandas as pd
import shapely

from datos import RAIZ_PROYECTO

LIMITES_GEOJSON = RAIZ_PROYECTO / "data" / "pb2002" / "PB2002_boundaries.json"
KM_POR_GRADO = 111.2

# Grupos de límites relevantes para Chile, según el par de placas (códigos PB2002)
GRUPOS = {
    "Nazca bajo Sudamericana": [{"NZ", "SA"}, {"NZ", "AP"}],
    "Antártica bajo Sudamericana": [{"AN", "SA"}],
    "Dorsal de Chile": [{"AN", "NZ"}],
    "Scotia y Shetland": [{"SC", "AN"}, {"SL", "AN"}, {"SC", "SL"}, {"SC", "SA"}],
    "Dorsales del Pacífico": [{"PA", "AN"}, {"NZ", "PA"}, {"EA", "PA"}, {"EA", "NZ"}, {"JZ", "PA"}, {"JZ", "AN"}, {"JZ", "NZ"}],
}
ORDEN_GRUPOS = list(GRUPOS)

# Recuadro de interés (lon, lat): Chile, el Pacífico cercano y el Paso Drake
RECUADRO = (-120.0, -66.0, -40.0, -10.0)


# Meridiano central de la proyección: pasa por Chile, donde la distorsión es mínima
MERIDIANO_CENTRAL = -70.0


def _proyectar(lon, lat):
    """Proyección sinusoidal centrada en Chile: x e y quedan en grados 'de distancia', comparables entre sí.

    Centrarla en el meridiano 70°O (y no en Greenwich) evita el sesgo de distancia
    que aparece lejos del meridiano central.
    """
    return (np.asarray(lon) - MERIDIANO_CENTRAL) * np.cos(np.radians(lat)), np.asarray(lat)


def cargar_limites() -> list[dict]:
    """Líneas de límites de placas dentro del recuadro, con su grupo."""
    datos = json.loads(LIMITES_GEOJSON.read_text(encoding="utf-8"))
    lon_min, lat_min, lon_max, lat_max = RECUADRO
    limites = []
    for f in datos["features"]:
        par = {f["properties"]["PlateA"], f["properties"]["PlateB"]}
        grupo = next((g for g, pares in GRUPOS.items() if par in pares), None)
        if grupo is None:
            continue
        coords = np.array(f["geometry"]["coordinates"])
        dentro = (coords[:, 0] >= lon_min) & (coords[:, 0] <= lon_max) & (coords[:, 1] >= lat_min) & (coords[:, 1] <= lat_max)
        if not dentro.any():
            continue
        limites.append({
            "nombre": f["properties"]["Name"],
            "grupo": grupo,
            "subduccion": f["properties"]["Type"] == "subduction",
            "coords": coords,
        })
    return limites


def asignar_limite(df: pd.DataFrame, limites: list[dict]) -> pd.DataFrame:
    """Agrega a cada sismo su grupo de límite más cercano y la distancia en km."""
    x, y = _proyectar(df.longitud.values, df.latitud.values)
    puntos = shapely.points(x, y)

    distancias = {}
    for grupo in ORDEN_GRUPOS:
        lineas = [shapely.LineString(np.column_stack(_proyectar(l["coords"][:, 0], l["coords"][:, 1])))
                  for l in limites if l["grupo"] == grupo]
        if lineas:
            distancias[grupo] = shapely.distance(puntos, shapely.MultiLineString(lineas)) * KM_POR_GRADO

    tabla = pd.DataFrame(distancias, index=df.index)
    df["limite"] = pd.Categorical(tabla.idxmin(axis=1), categories=ORDEN_GRUPOS, ordered=True)
    df["dist_limite_km"] = tabla.min(axis=1).round(1)
    return df


def latitud_punto_triple(limites: list[dict]) -> float:
    """Extremo sur del límite Nazca–Sudamericana: donde empieza a hundirse la placa Antártica."""
    lats = [l["coords"][:, 1].min() for l in limites if l["grupo"] == "Nazca bajo Sudamericana"]
    return round(float(min(lats)), 1)
