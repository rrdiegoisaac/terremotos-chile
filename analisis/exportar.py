"""
Calcula los resultados de cada sección de la nota y los exporta como JSON
resumidos en export/, listos para los gráficos del portafolio.

Uso:
    python analisis/exportar.py
"""

import json

import numpy as np
import pandas as pd

from datos import (
    DESDE,
    DESDE_CATALOGO,
    FIN_COMPARACION_TEMPORAL,
    HASTA,
    ORDEN_ZONAS,
    PCT_COBERTURA_ESTABLE,
    RAIZ_PROYECTO,
    RECUADRO_REGIONAL,
    ZONAS,
    cargar_sismos,
)
from estadistica import magnitud_de_completitud, mann_kendall, valor_b
from placas import ORDEN_GRUPOS, asignar_limite, cargar_limites, latitud_punto_triple
from secuencias import (
    DIAS_EXCLUIDOS_ANTES,
    DIAS_LINEA_BASE,
    MAGNITUD_SECUENCIAS,
    PROFUNDIDAD_MAX_KM,
    analizar_secuencia,
    elegir_terremotos,
    marcar_secuencias,
    radio_km,
)

EXPORT = RAIZ_PROYECTO / "export"

UMBRAL = 4.0  # magnitud para comparar zonas y años (ver nota metodológica)
UMBRAL_ALTO = 4.5  # segundo umbral, para comprobar que las conclusiones no dependen del primero
INTERMEDIO_KM = 70  # sismos más profundos que esto: "profundidad intermedia"
MAX_PUNTOS_CORTE = 3000
# La Antártica y el Paso Drake solo aparecen en el catálogo alrededor de grandes secuencias:
# su tasa no es comparable con la del resto del país
ZONAS_COBERTURA_EPISODICA = {"Antártica y Drake"}


def guardar(nombre: str, datos: dict) -> None:
    EXPORT.mkdir(exist_ok=True)
    ruta = EXPORT / nombre
    ruta.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  {ruta.relative_to(RAIZ_PROYECTO)}  ({ruta.stat().st_size / 1024:.0f} KB)")


def anios_periodo(desde: str = DESDE, hasta: str = HASTA) -> float:
    return ((pd.Timestamp(hasta) - pd.Timestamp(desde)).days + 1) / 365.25


def extension_latitud(zona: str) -> float | None:
    """Grados de latitud que abarca la zona dentro del recuadro analizado (para normalizar el conteo)."""
    lat_min_recuadro, _, _, _ = RECUADRO_REGIONAL
    for nombre, lat_min, lat_max in ZONAS:
        if nombre == zona:
            lat_min = max(lat_min, lat_min_recuadro)
            lat_max = min(lat_max, -17.5)  # extremo norte de Chile
            return round(lat_max - lat_min, 1)
    return None


def pct(parte, total) -> float:
    return round(float(parte) / float(total) * 100, 1) if total else 0.0


# --- ¿Dónde tiembla más? ---------------------------------------------------------

def seccion_donde_tiembla(df: pd.DataFrame) -> dict:
    anios = anios_periodo()
    m4 = df[df.magnitud >= UMBRAL]

    por_zona = []
    for zona in ORDEN_ZONAS:
        sub = df[df.zona == zona]
        if sub.empty:
            continue
        sub_m4 = sub[sub.magnitud >= UMBRAL]
        grados = extension_latitud(zona)
        comparable = zona not in ZONAS_COBERTURA_EPISODICA and grados is not None
        por_zona.append({
            "zona": zona,
            "comparable": comparable,
            "sismos": len(sub),
            "pct": pct(len(sub), len(df)),
            "sismos_m4": len(sub_m4),
            "pct_m4": pct(len(sub_m4), len(m4)),
            "m4_sin_secuencias": int((~sub_m4.en_secuencia).sum()),
            "grados_latitud": grados,
            "m4_por_grado_anual": round(len(sub_m4) / grados / anios, 1) if comparable else None,
            "m4_sin_secuencias_por_grado_anual": round((~sub_m4.en_secuencia).sum() / grados / anios, 1) if comparable else None,
            "magnitud": {
                "mediana": round(sub.magnitud.median(), 2),
                "p95": round(sub.magnitud.quantile(0.95), 2),
                "max": sub.magnitud.max(),
            },
        })

    # Conteo por franja de 1° de latitud (sin la zona oceánica), todas las magnitudes y M>=4
    costa = df[df.zona != "Oceánico"]
    franja = np.floor(costa.latitud).astype(int)
    conteo = franja.value_counts()
    conteo_m4 = franja[costa.magnitud >= UMBRAL].value_counts()
    por_latitud = [
        {"latitud": int(lat), "sismos": int(conteo.get(lat, 0)), "sismos_m4": int(conteo_m4.get(lat, 0))}
        for lat in range(-18, -67, -1)
    ]
    franja_20_24 = sum(f["sismos_m4"] for f in por_latitud if -24 <= f["latitud"] <= -21)

    # Grilla de 0,5° para el mapa (centro de cada celda)
    celdas = (
        costa.assign(lat=np.floor(costa.latitud * 2) / 2 + 0.25, lon=np.floor(costa.longitud * 2) / 2 + 0.25)
        .groupby(["lat", "lon"])
        .agg(sismos=("magnitud", "size"), mag_max=("magnitud", "max"))
        .reset_index()
    )

    # Participación del Norte Grande por año: todas las magnitudes vs M>=4
    hasta_fin = df[df.fecha_utc <= FIN_COMPARACION_TEMPORAL]
    anual = []
    for anio, sub in hasta_fin.groupby(hasta_fin.fecha_utc.dt.year):
        sub_m4 = sub[sub.magnitud >= UMBRAL]
        anual.append({
            "anio": int(anio),
            "pct_todos": pct((sub.zona == "Norte Grande").sum(), len(sub)),
            "pct_m4": pct((sub_m4.zona == "Norte Grande").sum(), len(sub_m4)),
        })

    m4_sin = m4[~m4.en_secuencia]
    zonas = {z["zona"]: z for z in por_zona}
    return {
        "periodo": {"desde": DESDE, "hasta": HASTA},
        "anios": round(anios, 1),
        "total_sismos": len(df),
        "total_m4": len(m4),
        "resumen": {
            "pct_norte_grande_m4": zonas["Norte Grande"]["pct_m4"],
            "pct_norte_grande_m4_sin_secuencias": pct((m4_sin.zona == "Norte Grande").sum(), len(m4_sin)),
            "pct_franja_20_24_m4": pct(franja_20_24, len(m4)),
            "norte_grande_vs_centro": round(zonas["Norte Grande"]["m4_por_grado_anual"] / zonas["Centro"]["m4_por_grado_anual"], 2),
            "norte_grande_vs_norte_chico": round(zonas["Norte Grande"]["m4_por_grado_anual"] / zonas["Norte Chico"]["m4_por_grado_anual"], 2),
            "sin_secuencias_norte_grande_vs_centro": round(zonas["Norte Grande"]["m4_sin_secuencias_por_grado_anual"] / zonas["Centro"]["m4_sin_secuencias_por_grado_anual"], 2),
            "sin_secuencias_norte_grande_vs_norte_chico": round(zonas["Norte Grande"]["m4_sin_secuencias_por_grado_anual"] / zonas["Norte Chico"]["m4_sin_secuencias_por_grado_anual"], 2),
        },
        "pct_norte_grande_anual": anual,
        "por_zona": por_zona,
        "por_latitud": por_latitud,
        "mapa_celdas": celdas.to_dict(orient="records"),
    }


# --- ¿Qué tan fuertes? -----------------------------------------------------------

MAGNITUD_FUERTE = 6.0
# Dos períodos para comparar la distribución de magnitudes: antes y después de que el
# CSN empezara a usar la magnitud momento (Mw) de forma habitual en los sismos M>=4
PERIODO_ESCALA_A = (2008, 2014)
PERIODO_ESCALA_B = (2016, 2025)
# Indicador de detección por zona: % de sismos bajo magnitud 3, con la red reciente
PERIODO_DETECCION = (2019, 2025)


def seccion_magnitudes(df: pd.DataFrame) -> dict:
    anios = anios_periodo()
    anio = df.fecha_utc.dt.year

    acumulados = [{"umbral": u, "sismos": int((df.magnitud >= u).sum())} for u in [4, 5, 6, 7]]

    fuertes = df[df.magnitud >= MAGNITUD_FUERTE].sort_values("magnitud", ascending=False)
    lista_fuertes = [
        {
            "fecha": r.fecha_utc.strftime("%Y-%m-%d"),
            "magnitud": r.magnitud,
            "profundidad_km": r.profundidad_km,
            "lat": r.latitud,
            "lon": r.longitud,
            "lugar": r.lugar,
            "zona": r.zona,
        }
        for r in fuertes.itertuples()
    ]
    fuertes_ng = fuertes[fuertes.zona == "Norte Grande"]

    # Histograma no acumulado (tramos de 0,1) en sismos por año, para dos períodos
    def por_tramo(desde_anio, hasta_anio):
        sub = df[(anio >= desde_anio) & (anio <= hasta_anio)]
        n_anios = hasta_anio - desde_anio + 1
        return ((sub.magnitud * 10).round() / 10).value_counts() / n_anios, sub

    tramo_a, sub_a = por_tramo(*PERIODO_ESCALA_A)
    tramo_b, sub_b = por_tramo(*PERIODO_ESCALA_B)
    histograma = []
    for m in np.round(np.arange(2.5, 8.9, 0.1), 1):
        fila = {"magnitud": float(m)}
        for clave, tramo in (("a", tramo_a), ("b", tramo_b)):
            valor = tramo.get(m, 0)
            fila[clave] = round(float(valor), 2) if valor else None  # sin barra en escala log
        histograma.append(fila)

    # Escala de magnitud por año entre los sismos M>=4
    escala = []
    for a, sub in df[(df.magnitud >= UMBRAL) & (df.fecha_utc <= FIN_COMPARACION_TEMPORAL)].groupby(anio):
        escala.append({
            "anio": int(a),
            "pct_mw": pct(sub.tipo_magnitud.str.startswith("Mw").sum(), len(sub)),
            "razon_m5_m4": round((sub.magnitud >= 5).sum() / len(sub), 3),
        })

    # Detección por zona con la red reciente: % de sismos bajo magnitud 3
    reciente = df[(anio >= PERIODO_DETECCION[0]) & (anio <= PERIODO_DETECCION[1])]
    deteccion = [
        {"zona": z, "sismos": int((reciente.zona == z).sum()), "pct_bajo_3": pct(((reciente.zona == z) & (reciente.magnitud < 3)).sum(), (reciente.zona == z).sum())}
        for z in ORDEN_ZONAS
        if z not in ZONAS_COBERTURA_EPISODICA and (reciente.zona == z).sum() >= 100
    ]

    return {
        "umbral_fuerte": MAGNITUD_FUERTE,
        "sismos_fuertes": len(fuertes),
        "fuertes_por_anio": round(len(fuertes) / anios, 1),
        "fuertes_por_zona": [{"zona": z, "sismos": int((fuertes.zona == z).sum())} for z in ORDEN_ZONAS],
        "fuertes_norte_grande_intermedios": int((fuertes_ng.profundidad_km > INTERMEDIO_KM).sum()),
        "fuertes_norte_grande": len(fuertes_ng),
        "fuertes": lista_fuertes,
        "acumulados": acumulados,
        "histograma": histograma,
        "periodos_escala": {"a": list(PERIODO_ESCALA_A), "b": list(PERIODO_ESCALA_B)},
        "valor_b": {
            "a": round(valor_b(sub_a.magnitud, UMBRAL), 2),
            "b": round(valor_b(sub_b.magnitud, UMBRAL), 2),
            "magnitud_minima": UMBRAL,
        },
        "escala_por_anio": escala,
        "deteccion_por_zona": deteccion,
        "periodo_deteccion": list(PERIODO_DETECCION),
    }


# --- ¿A qué profundidad tiembla? ---------------------------------------------------

CORTES = [
    # Franjas de latitud para el corte profundidad vs longitud
    ("Norte (21,5°–23,5°S)", -23.5, -21.5),
    ("Centro (32°–34°S)", -34.0, -32.0),
    ("Sur (38,5°–41°S)", -41.0, -38.5),
]
MIN_SISMOS_TRAMO = 30  # tramos de distancia con menos sismos no se grafican
MIN_SISMOS_MEDIANA_CORTE = 100  # la mediana de los cortes solo se dibuja en tramos con suficientes sismos


def seccion_profundidad(df: pd.DataFrame) -> dict:
    por_zona = []
    for zona in ORDEN_ZONAS:
        sub = df[df.zona == zona]
        if sub.empty:
            continue
        por_zona.append({
            "zona": zona,
            "sismos": len(sub),
            "mediana_km": round(sub.profundidad_km.median(), 1),
            "p90_km": round(sub.profundidad_km.quantile(0.9), 1),
            "max_km": sub.profundidad_km.max(),
            "pct_intermedios": pct((sub.profundidad_km > INTERMEDIO_KM).sum(), len(sub)),
            # 10 km exactos suele ser una profundidad fijada cuando no se puede calcular
            "pct_prof_fija_10km": pct((sub.profundidad_km == 10).sum(), len(sub)),
        })

    cortes = []
    for nombre, lat_min, lat_max in CORTES:
        sub = df[df.latitud.between(lat_min, lat_max) & (df.zona != "Oceánico")]
        # Muestra aleatoria para que el gráfico siga siendo liviano; las cifras usan todos los sismos
        muestra = sub.sample(n=min(len(sub), MAX_PUNTOS_CORTE), random_state=42)
        # Profundidad mediana por tramo de 0,5° de longitud, con todos los sismos
        tramo = np.floor(sub.longitud * 2) / 2 + 0.25
        mediana = sub.groupby(tramo).profundidad_km.agg(["count", "median"])
        cortes.append({
            "nombre": nombre,
            "sismos": len(sub),
            "puntos_mostrados": len(muestra),
            "prof_max_km": sub.profundidad_km.max(),
            "pct_hasta_70km": pct((sub.profundidad_km <= INTERMEDIO_KM).sum(), len(sub)),
            "mediana_por_longitud": [
                {"lon": float(lon), "prof": float(fila["median"])}
                for lon, fila in mediana.iterrows()
                if fila["count"] >= MIN_SISMOS_MEDIANA_CORTE
            ],
            "puntos": [{"lon": round(r.longitud, 2), "prof": r.profundidad_km, "mag": r.magnitud} for r in muestra.itertuples()],
        })

    # Profundidad típica según distancia al límite Nazca–Sudamericana (la fosa)
    nazca = df[df.limite == "Nazca bajo Sudamericana"]
    grupo = np.where(nazca.zona == "Norte Grande", "norte_grande", "resto")
    tramo = (nazca.dist_limite_km // 50 * 50).astype(int)
    tabla = nazca.groupby([tramo, grupo]).profundidad_km.agg(["count", "median"])
    profundidad_vs_distancia = []
    for desde in sorted(tramo.unique()):
        fila = {"desde_km": int(desde), "etiqueta": f"{desde}–{desde + 50}"}
        for g in ["norte_grande", "resto"]:
            if (desde, g) in tabla.index and tabla.loc[(desde, g), "count"] >= MIN_SISMOS_TRAMO:
                fila[g] = float(tabla.loc[(desde, g), "median"])
                fila[f"{g}_n"] = int(tabla.loc[(desde, g), "count"])
        if "norte_grande" in fila or "resto" in fila:
            profundidad_vs_distancia.append(fila)

    return {
        "umbral_intermedio_km": INTERMEDIO_KM,
        "por_zona": por_zona,
        "cortes": cortes,
        "profundidad_vs_distancia": profundidad_vs_distancia,
    }


# --- Límites de placas ---------------------------------------------------------------

# Recuadro de las líneas de límites que se dibujan en el mapa (lon, lat)
MAPA_LIMITES = (-82.0, -63.0, -54.0, -14.0)


def seccion_placas(df: pd.DataFrame, limites: list[dict]) -> dict:
    anios = anios_periodo()

    por_limite = []
    for grupo in ORDEN_GRUPOS:
        sub = df[df.limite == grupo]
        por_limite.append({
            "limite": grupo,
            "sismos": len(sub),
            "pct": pct(len(sub), len(df)),
            "sismos_m6": int((sub.magnitud >= 6).sum()),
            "prof_mediana_km": float(sub.profundidad_km.median()) if len(sub) else None,
            "mag_max": float(sub.magnitud.max()) if len(sub) else None,
        })

    # Sismos M>=4 por grado de latitud al año a cada lado del punto triple,
    # sin las secuencias de grandes terremotos (el Maule y Melinka caen en el tramo norte)
    lat_triple = latitud_punto_triple(limites)
    base = df[(df.magnitud >= UMBRAL) & (df.zona != "Oceánico") & ~df.en_secuencia]
    ancho = -38.0 - lat_triple  # mismo largo a cada lado del punto triple
    tramos = {"norte": (-38.0, lat_triple), "sur": (lat_triple, round(lat_triple - ancho, 1))}
    densidad = {}
    for lado, (lat_n, lat_s) in tramos.items():
        n = int(((base.latitud <= lat_n) & (base.latitud > lat_s)).sum())
        densidad[lado] = {"lat_desde": lat_n, "lat_hasta": lat_s, "sismos_m4": n, "por_grado_anual": round(n / abs(lat_n - lat_s) / anios, 2)}

    lon_min, lat_min, lon_max, lat_max = MAPA_LIMITES
    lineas = []
    for l in limites:
        c = l["coords"]
        dentro = (c[:, 0] >= lon_min) & (c[:, 0] <= lon_max) & (c[:, 1] >= lat_min) & (c[:, 1] <= lat_max)
        if dentro.sum() >= 2:
            lineas.append({
                "grupo": l["grupo"],
                "subduccion": l["subduccion"],
                "puntos": [{"lon": round(lon, 2), "lat": round(lat, 2)} for lon, lat in c[dentro]],
            })

    return {
        "punto_triple_lat": lat_triple,
        "por_limite": por_limite,
        "densidad_punto_triple": densidad,
        "lineas": lineas,
    }


# --- ¿Tiembla más que antes? --------------------------------------------------------

def seccion_tiempo(df: pd.DataFrame) -> dict:
    """Años completos desde el inicio de la red estable hasta antes del cambio de método de 2026."""
    df = df[df.fecha_utc <= FIN_COMPARACION_TEMPORAL]
    anio = df.fecha_utc.dt.year

    anual = []
    for a, sub in df.groupby(anio):
        m4, m45 = sub[sub.magnitud >= UMBRAL], sub[sub.magnitud >= UMBRAL_ALTO]
        mayor = sub.loc[sub.magnitud.idxmax()]
        anual.append({
            "anio": int(a),
            "m4": len(m4),
            "m4_secuencias": int(m4.en_secuencia.sum()),
            "m4_resto": int((~m4.en_secuencia).sum()),
            "m45": len(m45),
            "m45_resto": int((~m45.en_secuencia).sum()),
            "mayor_magnitud": float(mayor.magnitud),
            "mayor_lugar": mayor.lugar,
        })

    resto_m4 = [a["m4_resto"] for a in anual]
    resto_m45 = [a["m45_resto"] for a in anual]
    return {
        "periodo": {"desde": DESDE, "hasta": FIN_COMPARACION_TEMPORAL},
        "umbral": UMBRAL,
        "umbral_alto": UMBRAL_ALTO,
        "anual": anual,
        "resumen": {
            "anios": len(anual),
            "mediana_m4": float(np.median([a["m4"] for a in anual])),
            "mediana_m4_resto": float(np.median(resto_m4)),
            "min_m4_resto": min(resto_m4),
            "max_m4_resto": max(resto_m4),
        },
        "tendencia": {"m4_resto": mann_kendall(resto_m4), "m45_resto": mann_kendall(resto_m45)},
    }


# --- Los grandes terremotos -----------------------------------------------------------

def seccion_grandes_terremotos(df: pd.DataFrame, grandes: list, secuencias: list) -> dict:
    return {
        "umbral": UMBRAL,
        "profundidad_max_km": PROFUNDIDAD_MAX_KM,
        "dias_linea_base": DIAS_LINEA_BASE,
        "dias_excluidos_antes": DIAS_EXCLUIDOS_ANTES,
        "terremotos": [analizar_secuencia(df, t, UMBRAL, FIN_COMPARACION_TEMPORAL) for t in grandes],
        "secuencias_marcadas": [
            {
                "fecha": t.fecha_utc.strftime("%Y-%m-%d"),
                "magnitud": float(t.magnitud),
                "lugar": t.lugar,
                "radio_km": radio_km(t.magnitud),
            }
            for t in secuencias
        ],
        "magnitud_secuencias": MAGNITUD_SECUENCIAS,
    }


# --- Cómo cambió la medición -----------------------------------------------------------

TRAMOS_MAGNITUD = [(2.5, 3.0, "2,5–3"), (3.0, 3.5, "3–3,5"), (3.5, 4.0, "3,5–4"), (4.0, 99, "4 o más")]
ZOOM_DESDE = "2024-01"
ANTES_MLV = ("2025-01", "2025-12")  # un año completo medido con Ml
DESPUES_MLV = ("2026-03", None)  # desde que Mlv es el método habitual (más del 85% de los sismos)


def cambio_de_metodo(catalogo: pd.DataFrame) -> dict:
    """Recibe el catálogo completo (desde 2000), no solo el período de análisis."""
    anio = catalogo.fecha_utc.dt.year
    inicio, fin = catalogo.fecha_utc.min().normalize(), catalogo.fecha_utc.max().normalize()

    por_anio = []
    for a, sub in catalogo.groupby(anio):
        dias = (min(fin, pd.Timestamp(f"{a}-12-31")) - max(inicio, pd.Timestamp(f"{a}-01-01"))).days + 1
        sub_m4 = sub[sub.magnitud >= UMBRAL]
        por_anio.append({
            "anio": int(a),
            "dias": dias,
            "parcial": dias < 365,
            "sismos": len(sub),
            "magnitud_completitud": magnitud_de_completitud(sub.magnitud),
            "pct_bajo_2_5": pct((sub.magnitud < 2.5).sum(), len(sub)),
            "pct_norte_grande": pct((sub.zona == "Norte Grande").sum(), len(sub)),
            "pct_norte_grande_m4": pct((sub_m4.zona == "Norte Grande").sum(), len(sub_m4)),
            "norte_grande_m5": int(((sub.zona == "Norte Grande") & (sub.magnitud >= 5)).sum()),
        })

    # Zoom mensual alrededor del cambio de método, por tramo de magnitud
    mes = catalogo.fecha_utc.dt.to_period("M")
    ultimo_completo = fin.to_period("M") - (0 if (fin + pd.Timedelta(days=1)).day == 1 else 1)
    zoom = []
    for periodo in pd.period_range(ZOOM_DESDE, ultimo_completo, freq="M"):
        sub = catalogo[mes == periodo]
        fila = {"mes": str(periodo), "pct_mlv": pct((sub.tipo_magnitud == "Mlv").sum(), len(sub))}
        for bajo, alto, etiqueta in TRAMOS_MAGNITUD:
            fila[etiqueta] = int(((sub.magnitud >= bajo) & (sub.magnitud < alto)).sum())
        zoom.append(fila)

    def promedio_mensual(desde, hasta):
        filas = [z for z in zoom if z["mes"] >= desde and (hasta is None or z["mes"] <= hasta)]
        return {t[2]: round(np.mean([f[t[2]] for f in filas])) for t in TRAMOS_MAGNITUD}, len(filas)

    antes, meses_antes = promedio_mensual(*ANTES_MLV)
    despues, meses_despues = promedio_mensual(*DESPUES_MLV)
    mlv = catalogo[catalogo.tipo_magnitud == "Mlv"]
    anio_detectado = [a for a in por_anio if not a["parcial"]]

    return {
        "periodo_catalogo": {"desde": DESDE_CATALOGO, "hasta": HASTA},
        "inicio_red_estable": int(DESDE[:4]),
        "criterio_red_estable": f"primer año desde el cual el Norte Grande registra siempre al menos el {PCT_COBERTURA_ESTABLE}% de su nivel reciente de sismos de magnitud 4 o más",
        "por_anio": por_anio,
        "primer_anio_piso_2_5": next((a["anio"] for a in anio_detectado if a["pct_bajo_2_5"] < 1), None),
        "zoom": zoom,
        "tramos": [t[2] for t in TRAMOS_MAGNITUD],
        "mlv": {
            "primer_registro": mlv.fecha_utc.min().strftime("%Y-%m-%d") if len(mlv) else None,
            "habitual_desde": DESPUES_MLV[0],
            "antes": {"periodo": list(ANTES_MLV), "meses": meses_antes, "por_mes": antes},
            "despues": {"desde": DESPUES_MLV[0], "meses": meses_despues, "por_mes": despues},
        },
    }


# --- Fronteras para los mapas ------------------------------------------------------

FRONTERAS_DIBUJO = RAIZ_PROYECTO / "data" / "fronteras" / "paises_110m.geojson"
MAPA_RECUADRO = (-84.0, -66.0, -52.0, -12.0)  # lon_min, lat_min, lon_max, lat_max


def fronteras_para_mapa() -> dict:
    """Contornos de países (escala 1:110 millones) recortados al recuadro de los mapas."""
    import shapely

    datos = json.loads(FRONTERAS_DIBUJO.read_text(encoding="utf-8"))
    recuadro = shapely.box(*MAPA_RECUADRO)
    lineas = []
    for f in datos["features"]:
        geom = shapely.geometry.shape(f["geometry"]).intersection(recuadro)
        for poligono in getattr(geom, "geoms", [geom]):
            if poligono.is_empty or poligono.geom_type != "Polygon":
                continue
            anillo = poligono.exterior.simplify(0.05)
            lineas.append({
                "pais": f["properties"]["nombre"],
                "puntos": [{"lon": round(x, 2), "lat": round(y, 2)} for x, y in anillo.coords],
            })
    return {"fuente": "Natural Earth, 1:110 millones (dominio público)", "lineas": lineas}


def main() -> None:
    limites = cargar_limites()
    df = asignar_limite(cargar_sismos(), limites)
    secuencias = elegir_terremotos(df, magnitud_min=MAGNITUD_SECUENCIAS, n=None)
    df["en_secuencia"] = marcar_secuencias(df, secuencias)
    grandes = elegir_terremotos(df)
    print(f"{len(df)} sismos entre {DESDE} y {HASTA}. Exportando:")
    guardar("00_cambio_metodo.json", cambio_de_metodo(cargar_sismos(DESDE_CATALOGO, HASTA)))
    guardar("01_donde_tiembla.json", seccion_donde_tiembla(df))
    guardar("02_magnitudes.json", seccion_magnitudes(df))
    guardar("03_placas.json", seccion_placas(df, limites))
    guardar("04_profundidad.json", seccion_profundidad(df))
    guardar("05_tiempo.json", seccion_tiempo(df))
    guardar("06_grandes_terremotos.json", seccion_grandes_terremotos(df, grandes, secuencias))
    guardar("07_fronteras.json", fronteras_para_mapa())


if __name__ == "__main__":
    main()
