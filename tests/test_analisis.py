"""Pruebas de las funciones principales. Ejecutar desde la raíz del proyecto: python -m pytest"""

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "analisis"), str(RAIZ / "scraper")]

from estadistica import magnitud_de_completitud, mann_kendall, valor_b  # noqa: E402
from scrape_catalogo import parsear_dia  # noqa: E402
from secuencias import intervalo_poisson, largo_ruptura_km, radio_km  # noqa: E402


# --- Estadística ------------------------------------------------------------------

def test_magnitud_de_completitud_es_la_mas_frecuente():
    magnitudes = pd.Series([2.1, 2.5, 2.5, 2.5, 2.6, 3.0, 3.4])
    assert magnitud_de_completitud(magnitudes) == 2.5


def test_valor_b_recupera_el_valor_de_una_muestra_sintetica():
    # Magnitudes con distribución de Gutenberg-Richter de b = 1, redondeadas a 0,1 como el CSN
    rng = np.random.default_rng(0)
    magnitudes = 3.95 + rng.exponential(1 / np.log(10), size=20_000)
    magnitudes = pd.Series(np.round(magnitudes, 1))
    assert valor_b(magnitudes, 4.0) == pytest.approx(1.0, abs=0.05)


def test_mann_kendall_detecta_tendencia_y_su_ausencia():
    creciente = mann_kendall(list(range(15)))
    assert creciente["s"] > 0 and creciente["p"] < 0.01

    plana = mann_kendall([5] * 15)
    assert plana["s"] == 0 and plana["p"] == 1.0


def test_intervalo_poisson_coincide_con_el_exacto():
    # Valores exactos (Garwood) para n = 105: 85,9 a 127,1
    inferior, superior = intervalo_poisson(105)
    assert inferior == pytest.approx(85.9, abs=0.3)
    assert superior == pytest.approx(127.1, abs=0.3)


# --- Secuencias ---------------------------------------------------------------------

def test_largo_ruptura_wells_coppersmith():
    # log10(L) = -2,44 + 0,59·M  →  M7: ~49 km
    assert largo_ruptura_km(7.0) == pytest.approx(49.0, rel=0.01)


def test_radio_es_la_mitad_de_la_ruptura_mas_50_km():
    assert radio_km(8.8) == round(largo_ruptura_km(8.8) / 2 + 50)  # Maule: ~332 km
    assert radio_km(8.8) > radio_km(8.2) > radio_km(7.0) > 50


# --- Datos (requieren las fronteras en data/fronteras) ---------------------------------

def test_clasificar_zona():
    from datos import clasificar_zona

    assert clasificar_zona(-20.0, -70.0) == "Norte Grande"
    assert clasificar_zona(-35.0, -72.0) == "Centro"
    assert clasificar_zona(-30.0, -100.0) == "Oceánico"
    assert clasificar_zona(-60.0, -60.0) == "Antártica y Drake"


def test_filtro_territorial():
    from datos import en_territorio_analizado

    lat = pd.Series([-33.45, -31.42, -33.0, -17.8])
    lon = pd.Series([-70.67, -64.18, -73.0, -72.0])
    # Santiago (sí), Córdoba, Argentina (no), mar frente a Chile (sí), mar frente a Perú (no)
    assert en_territorio_analizado(lat, lon).tolist() == [True, False, True, False]


def test_quitar_casi_duplicados():
    from datos import quitar_casi_duplicados

    df = pd.DataFrame({
        "fecha_utc": pd.to_datetime(["2010-03-21 18:56:45", "2010-03-21 18:56:47", "2010-03-21 19:30:00"]),
        "latitud": [-34.10, -34.12, -34.10],
        "longitud": [-72.00, -72.01, -72.00],
        "magnitud": [4.3, 4.4, 4.3],
    })
    assert len(quitar_casi_duplicados(df)) == 2


# --- Scraper ------------------------------------------------------------------------

HTML_CON_TABLA = """
<table class="sismologia detalle">
  <tr><th>Fecha Local / Lugar</th><th>Fecha UTC</th><th>Latitud / Longitud</th><th>Profundidad</th><th>Magnitud</th></tr>
  <tr>
    <td><a href="/sismicidad/informes/2010/02/71800.html">2010-02-27 03:34:08</a><br>44 km al O de Cobquecura</td>
    <td>2010-02-27 06:34:08</td>
    <td>-36.290<br> -73.239</td>
    <td>30 km</td>
    <td class="magnitud">8.8 Mw</td>
  </tr>
</table>
"""


def test_parsear_dia_extrae_cada_campo():
    sismos = parsear_dia(HTML_CON_TABLA, date(2010, 2, 27))
    assert sismos == [{
        "informe_url": "/sismicidad/informes/2010/02/71800.html",
        "fecha_local": "2010-02-27 03:34:08",
        "fecha_utc": "2010-02-27 06:34:08",
        "lugar": "44 km al O de Cobquecura",
        "latitud": -36.29,
        "longitud": -73.239,
        "profundidad_km": 30.0,
        "magnitud": 8.8,
        "tipo_magnitud": "Mw",
        "dia_catalogo": "2010-02-27",
    }]


def test_parsear_dia_distingue_pagina_sin_tabla():
    assert parsear_dia("<html><body>Error</body></html>", date(2010, 2, 27)) is None
