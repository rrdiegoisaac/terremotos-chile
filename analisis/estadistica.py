"""Funciones estadísticas del análisis (sin dependencias de los datos, para poder probarlas)."""

from math import erfc, log10, e, sqrt

import numpy as np
import pandas as pd

PASO_MAGNITUD = 0.1  # el CSN publica las magnitudes con un decimal


def magnitud_de_completitud(magnitudes: pd.Series) -> float:
    """Magnitud más frecuente (en tramos de 0,1): bajo ella, el catálogo empieza a perder sismos.

    Es el método de 'máxima curvatura'. Tiende a subestimar la completitud y no
    distingue la detección de la red de un piso de publicación del catálogo.
    """
    tramos = (magnitudes * 10).round() / 10
    return float(tramos.value_counts().idxmax())


def valor_b(magnitudes: pd.Series, magnitud_minima: float) -> float:
    """Valor b de Gutenberg-Richter por máxima verosimilitud (estimador de Aki, con corrección por redondeo).

    b = log10(e) / (media(M) - (Mmin - paso/2)), usando solo magnitudes >= Mmin.
    """
    m = magnitudes[magnitudes >= magnitud_minima - 1e-9]
    if len(m) < 2:
        return float("nan")
    return log10(e) / (m.mean() - (magnitud_minima - PASO_MAGNITUD / 2))


def mann_kendall(serie: list[float]) -> dict:
    """Prueba de tendencia de Mann-Kendall (bilateral, aproximación normal, sin corrección por empates).

    Devuelve el estadístico S, z, el valor p y la pendiente de Sen (cambio típico por período).
    """
    x = np.asarray(serie, dtype=float)
    n = len(x)
    s = sum(np.sign(x[j] - x[i]) for i in range(n - 1) for j in range(i + 1, n))
    varianza = n * (n - 1) * (2 * n + 5) / 18
    if s > 0:
        z = (s - 1) / sqrt(varianza)
    elif s < 0:
        z = (s + 1) / sqrt(varianza)
    else:
        z = 0.0
    p = erfc(abs(z) / sqrt(2))
    pendientes = [(x[j] - x[i]) / (j - i) for i in range(n - 1) for j in range(i + 1, n)]
    return {
        "n": n,
        "s": int(s),
        "z": round(float(z), 2),
        "p": round(float(p), 3),
        "pendiente_sen": round(float(np.median(pendientes)), 1),
    }
