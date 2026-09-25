"""
Secuencias de los grandes terremotos: qué pasó antes y después de cada uno.

Criterios:
- Se eligen los terremotos más fuertes del territorio analizado (sin el Paso Drake
  ni la zona oceánica), descartando los que son réplicas de otro ya elegido.
- Radio de la secuencia: la mitad del largo típico de la ruptura más 50 km. El
  largo sale de Wells y Coppersmith (1994), log10(L) = -2,44 + 0,59·M, estimada
  con sismos de hasta magnitud 8,1: para terremotos mayores es una aproximación.
- El círculo se centra en las réplicas del primer mes y no en el epicentro,
  porque muchas rupturas avanzan hacia un solo lado.
- Solo se cuentan sismos de magnitud >= umbral (4,0) y hasta 70 km de profundidad
  (la zona de contacto entre placas), en la secuencia y en la actividad normal.
- Actividad normal, con dos referencias:
  1. el año previo al terremoto, sin el último mes (por posibles precursores);
  2. el largo plazo: mediana de las tasas anuales en el mismo círculo, sin las
     secuencias de otros terremotos de magnitud 7 o más ni el entorno del propio.
"""

from math import sqrt

import numpy as np
import pandas as pd

RADIO_MIN_KM = 50
MARGEN_RADIO_KM = 50
PROFUNDIDAD_MAX_KM = 70
DIAS_CENTROIDE = 30
MIN_SISMOS_CENTROIDE = 5
DIAS_LINEA_BASE = 365
DIAS_EXCLUIDOS_ANTES = 30
DIAS_VENTANA = 365
DIAS_GRAFICO_ANTES = 30
DIAS_GRAFICO_DESPUES = 60
N_TERREMOTOS = 3
MAGNITUD_SECUENCIAS = 7.0  # terremotos cuyas secuencias se marcan (y se excluyen de la actividad normal)
MIN_DIAS_ANIO_BASE = 180
ZONAS_EXCLUIDAS = {"Antártica y Drake", "Oceánico"}


def distancia_km(lat1, lon1, lat2, lon2):
    """Distancia sobre la superficie terrestre (fórmula de haversine)."""
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def largo_ruptura_km(magnitud: float) -> float:
    """Largo típico de la ruptura (Wells y Coppersmith, 1994, todos los tipos de falla)."""
    return 10 ** (-2.44 + 0.59 * magnitud)


def radio_km(magnitud: float) -> int:
    return int(max(RADIO_MIN_KM, round(largo_ruptura_km(magnitud) / 2 + MARGEN_RADIO_KM)))


def _dias_desde(df: pd.DataFrame, fecha: pd.Timestamp) -> pd.Series:
    return (df.fecha_utc - fecha).dt.total_seconds() / 86400


def centro_secuencia(df: pd.DataFrame, t, umbral: float) -> tuple[float, float]:
    """Centro de las réplicas del primer mes; si hay muy pocas, el epicentro.

    Se usa un mes y no las primeras horas porque, tras un gran terremoto, el catálogo
    registra primero las réplicas cercanas a más estaciones (en el Maule, solo las del norte).
    """
    dias = _dias_desde(df, t.fecha_utc)
    cerca = distancia_km(t.latitud, t.longitud, df.latitud, df.longitud) <= largo_ruptura_km(t.magnitud)
    tempranas = df[
        cerca
        & (dias > 0)
        & (dias <= DIAS_CENTROIDE)
        & (df.magnitud >= umbral)
        & (df.profundidad_km <= PROFUNDIDAD_MAX_KM)
    ]
    if len(tempranas) < MIN_SISMOS_CENTROIDE:
        return float(t.latitud), float(t.longitud)
    return float(tempranas.latitud.mean()), float(tempranas.longitud.mean())


def elegir_terremotos(df: pd.DataFrame, magnitud_min: float | None = None, n: int | None = N_TERREMOTOS) -> list:
    """Terremotos principales, de mayor a menor, sin contar réplicas de otro ya elegido."""
    candidatos = df[~df.zona.isin(ZONAS_EXCLUIDAS)]
    if magnitud_min is not None:
        candidatos = candidatos[candidatos.magnitud >= magnitud_min]
    candidatos = candidatos.sort_values("magnitud", ascending=False)

    elegidos = []
    for r in candidatos.itertuples():
        es_replica = any(
            0 < (r.fecha_utc - e.fecha_utc).total_seconds() / 86400 <= DIAS_VENTANA
            and distancia_km(e.latitud, e.longitud, r.latitud, r.longitud) <= radio_km(e.magnitud)
            for e in elegidos
        )
        if not es_replica:
            elegidos.append(r)
        if n is not None and len(elegidos) == n:
            break
    return elegidos


def marcar_secuencias(df: pd.DataFrame, terremotos: list) -> pd.Series:
    """True para los sismos dentro de la secuencia (1 año, dentro del radio) de alguno de los terremotos."""
    marca = pd.Series(False, index=df.index)
    for t in terremotos:
        dias = _dias_desde(df, t.fecha_utc)
        cerca = distancia_km(t.latitud, t.longitud, df.latitud, df.longitud) <= radio_km(t.magnitud)
        marca |= cerca & (dias >= 0) & (dias <= DIAS_VENTANA)
    return marca


def intervalo_poisson(n: int, confianza: float = 0.95) -> tuple[float, float]:
    """Intervalo exacto (Garwood) para un conteo de Poisson.

    Usa la aproximación de Wilson-Hilferty para los cuantiles de chi-cuadrado,
    precisa para conteos desde ~5.
    """
    z = {0.95: 1.959964}[confianza]

    def cuantil_chi2(p_z: float, k: int) -> float:
        return k * (1 - 2 / (9 * k) + p_z * sqrt(2 / (9 * k))) ** 3

    inferior = 0.0 if n == 0 else cuantil_chi2(-z, 2 * n) / 2
    superior = cuantil_chi2(z, 2 * n + 2) / 2
    return round(inferior, 1), round(superior, 1)


def tasa_largo_plazo(df: pd.DataFrame, t, en_circulo: pd.Series, fin: str) -> float:
    """Mediana de las tasas diarias por año, sin secuencias marcadas ni el entorno del propio terremoto."""
    inicio_excluido = t.fecha_utc - pd.Timedelta(days=DIAS_LINEA_BASE + DIAS_EXCLUIDOS_ANTES)
    fin_excluido = t.fecha_utc + pd.Timedelta(days=DIAS_VENTANA)
    validos = en_circulo & ~df.en_secuencia & ~df.fecha_utc.between(inicio_excluido, fin_excluido)

    tasas = []
    for anio in range(df.fecha_utc.min().year, pd.Timestamp(fin).year + 1):
        dia_1, dia_n = pd.Timestamp(f"{anio}-01-01"), pd.Timestamp(f"{anio}-12-31 23:59:59")
        solapado = max(pd.Timedelta(0), min(dia_n, fin_excluido) - max(dia_1, inicio_excluido))
        dias = 365 - solapado.days
        if dias < MIN_DIAS_ANIO_BASE:
            continue
        n = (validos & (df.fecha_utc.dt.year == anio)).sum()
        tasas.append(n / dias)
    return float(np.median(tasas)) if tasas else float("nan")


def analizar_secuencia(df: pd.DataFrame, t, umbral: float, fin_largo_plazo: str) -> dict:
    lat_c, lon_c = centro_secuencia(df, t, umbral)
    radio = radio_km(t.magnitud)
    dias = _dias_desde(df, t.fecha_utc)
    en_circulo = (
        (distancia_km(lat_c, lon_c, df.latitud, df.longitud) <= radio)
        & (df.magnitud >= umbral)
        & (df.profundidad_km <= PROFUNDIDAD_MAX_KM)
        & (df.fecha_utc != t.fecha_utc)
    )

    inicio_base = -(DIAS_LINEA_BASE + DIAS_EXCLUIDOS_ANTES)
    hay_linea_base = df.fecha_utc.min() <= t.fecha_utc + pd.Timedelta(days=inicio_base)
    tasa_previa = (en_circulo & (dias >= inicio_base) & (dias < -DIAS_EXCLUIDOS_ANTES)).sum() / DIAS_LINEA_BASE
    tasa_larga = tasa_largo_plazo(df, t, en_circulo, fin_largo_plazo)

    despues = df[en_circulo & (dias > 0) & (dias <= DIAS_VENTANA)]
    dias_despues = dias[despues.index]
    antes_30 = int((en_circulo & (dias >= -DIAS_EXCLUIDOS_ANTES) & (dias < 0)).sum())

    # Sismos por día, del día -30 al +60 (día 0 = primeras 24 horas)
    ventana = en_circulo & (dias >= -DIAS_GRAFICO_ANTES) & (dias < DIAS_GRAFICO_DESPUES)
    por_dia = np.floor(dias[ventana]).astype(int).value_counts()
    diario = [{"dia": d, "sismos": int(por_dia.get(d, 0))} for d in range(-DIAS_GRAFICO_ANTES, DIAS_GRAFICO_DESPUES)]

    # Sismos atribuibles acumulados (registrados menos esperables), con la actividad normal del año previo
    por_dia_completo = np.floor(dias_despues).astype(int).value_counts().reindex(range(DIAS_VENTANA), fill_value=0)
    acumulado = por_dia_completo.cumsum()
    exceso = [
        {"dia": d, "exceso": round(float(acumulado.iloc[d - 1] - tasa_previa * d), 1) if d else 0.0}
        for d in range(0, DIAS_VENTANA + 1, 5)
    ]

    total_30 = int((dias_despues <= 30).sum())
    replicas = df[(distancia_km(lat_c, lon_c, df.latitud, df.longitud) <= radio) & (dias > 0) & (dias <= DIAS_VENTANA)]
    mayor = replicas.loc[replicas.magnitud.idxmax()] if len(replicas) else None

    def rango(valores):
        return [round(float(min(valores))), round(float(max(valores)))]

    return {
        "fecha_utc": t.fecha_utc.strftime("%Y-%m-%d %H:%M"),
        "fecha_local": t.fecha_local.strftime("%Y-%m-%d %H:%M"),
        "anio": int(t.fecha_utc.year),
        "magnitud": float(t.magnitud),
        "tipo_magnitud": t.tipo_magnitud,
        "profundidad_km": float(t.profundidad_km),
        "lat": float(t.latitud),
        "lon": float(t.longitud),
        "centro": {"lat": round(lat_c, 2), "lon": round(lon_c, 2)},
        "lugar": t.lugar,
        "zona": t.zona,
        "radio_km": radio,
        "hay_linea_base": bool(hay_linea_base),
        "linea_base_por_dia": {"anio_previo": round(float(tasa_previa), 3), "largo_plazo": round(tasa_larga, 3)},
        "primer_dia": int((dias_despues <= 1).sum()),
        "total_30_dias": total_30,
        "total_365_dias": len(despues),
        "exceso_30_dias": rango([total_30 - tasa_previa * 30, total_30 - tasa_larga * 30]),
        "exceso_365_dias": rango([len(despues) - tasa_previa * DIAS_VENTANA, len(despues) - tasa_larga * DIAS_VENTANA]),
        "antes_30_dias": antes_30,
        "antes_30_dias_ic95": list(intervalo_poisson(antes_30)),
        "esperado_30_dias": {"anio_previo": round(tasa_previa * 30, 1), "largo_plazo": round(tasa_larga * 30, 1)},
        "mayor_replica": None if mayor is None else {
            "magnitud": float(mayor.magnitud),
            "horas_despues": round(float((mayor.fecha_utc - t.fecha_utc).total_seconds() / 3600), 1),
            "lugar": mayor.lugar,
        },
        "diario": diario,
        "exceso_acumulado": exceso,
    }
