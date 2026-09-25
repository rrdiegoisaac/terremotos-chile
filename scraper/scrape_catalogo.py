"""
Scraper del catálogo diario de sismos del Centro Sismológico Nacional (CSN).

Fuente: https://www.sismologia.cl/sismicidad/catalogo/AAAA/MM/AAAAMMDD.html
Destino: base SQLite (por defecto data/sismos.db)

Es reanudable: cada día descargado queda registrado en la tabla dias_scrapeados,
así que si el proceso se corta, al volver a ejecutarlo sigue donde quedó.

Uso:
    python scraper/scrape_catalogo.py                      # 2000-01-01 hasta ayer
    python scraper/scrape_catalogo.py --desde 2010-02-01 --hasta 2010-02-28
"""

import argparse
import logging
import re
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.sismologia.cl"
CATALOGO_URL = BASE_URL + "/sismicidad/catalogo/{d:%Y}/{d:%m}/{d:%Y%m%d}.html"
USER_AGENT = "terremotos-chile/1.0 (proyecto de portafolio; github.com/rrdiegoisaac)"

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
DB_POR_DEFECTO = RAIZ_PROYECTO / "data" / "sismos.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS sismos (
    id              INTEGER PRIMARY KEY,
    informe_url     TEXT UNIQUE NOT NULL,   -- identificador único del evento en el CSN
    fecha_local     TEXT,                   -- 'AAAA-MM-DD HH:MM:SS' hora de Chile
    fecha_utc       TEXT NOT NULL,          -- 'AAAA-MM-DD HH:MM:SS' UTC
    lugar           TEXT,                   -- referencia geográfica, ej. '50 km al O de Pichilemu'
    latitud         REAL,
    longitud        REAL,
    profundidad_km  REAL,
    magnitud        REAL,
    tipo_magnitud   TEXT,                   -- Ml, Mw, Mb, etc.
    dia_catalogo    TEXT NOT NULL           -- página del catálogo de la que salió (AAAA-MM-DD)
);
CREATE INDEX IF NOT EXISTS idx_sismos_fecha_utc ON sismos (fecha_utc);

CREATE TABLE IF NOT EXISTS dias_scrapeados (
    dia            TEXT PRIMARY KEY,        -- AAAA-MM-DD
    n_sismos       INTEGER NOT NULL,
    estado         TEXT NOT NULL,           -- 'ok', 'sin_pagina' (404) o 'sin_tabla' (página sin la tabla esperada)
    scrapeado_en   TEXT NOT NULL            -- timestamp UTC de la descarga
);
"""

log = logging.getLogger("scraper")


def conectar(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(ESQUEMA)
    return conn


def dias_pendientes(conn: sqlite3.Connection, desde: date, hasta: date) -> list[date]:
    # Los días 'sin_tabla' se vuelven a intentar: pueden ser un error temporal del sitio
    hechos = {fila[0] for fila in conn.execute("SELECT dia FROM dias_scrapeados WHERE estado != 'sin_tabla'")}
    total = (hasta - desde).days + 1
    todos = (desde + timedelta(days=i) for i in range(total))
    return [d for d in todos if d.isoformat() not in hechos]


def descargar(session: requests.Session, url: str, intentos: int = 4) -> str | None:
    """Devuelve el HTML, None si la página no existe (404). Reintenta errores temporales."""
    for intento in range(1, intentos + 1):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except requests.RequestException as err:
            if intento == intentos:
                raise
            espera = 5 * 2 ** (intento - 1)  # 5, 10, 20 s
            log.warning("Error en %s (%s). Reintento %d en %d s", url, err, intento, espera)
            time.sleep(espera)
    return None


def a_float(texto: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", texto)
    return float(match.group()) if match else None


def parsear_dia(html: str, dia: date) -> list[dict] | None:
    """Sismos de la página de un día. None si la página no tiene la tabla del catálogo
    (p. ej. un cambio de diseño o una página de error), para no confundirla con un día sin sismos."""
    soup = BeautifulSoup(html, "html.parser")
    tabla = soup.find("table", class_="detalle")
    if tabla is None:
        return None

    sismos = []
    for fila in tabla.find_all("tr"):
        celdas = fila.find_all("td")
        if len(celdas) < 5:
            continue  # fila de encabezado

        enlace = celdas[0].find("a")
        if enlace is None or not enlace.get("href"):
            log.warning("%s: fila sin enlace a informe, se omite: %s", dia, fila.get_text(" ", strip=True))
            continue

        # Celda 0: '<a>fecha local</a><br>lugar'
        partes_local = list(celdas[0].stripped_strings)
        fecha_local = partes_local[0] if partes_local else None
        lugar = " ".join(partes_local[1:]) or None

        # Celda 2: 'latitud<br>longitud'
        coords = list(celdas[2].stripped_strings)
        latitud = a_float(coords[0]) if len(coords) > 0 else None
        longitud = a_float(coords[1]) if len(coords) > 1 else None

        # Celda 4: '4.8 Ml'
        texto_mag = celdas[4].get_text(" ", strip=True)
        tipo = re.search(r"[A-Za-z]+\w*", texto_mag)

        sismos.append({
            "informe_url": enlace["href"].strip(),
            "fecha_local": fecha_local,
            "fecha_utc": celdas[1].get_text(strip=True),
            "lugar": lugar,
            "latitud": latitud,
            "longitud": longitud,
            "profundidad_km": a_float(celdas[3].get_text()),
            "magnitud": a_float(texto_mag),
            "tipo_magnitud": tipo.group() if tipo else None,
            "dia_catalogo": dia.isoformat(),
        })
    return sismos


def guardar_dia(conn: sqlite3.Connection, dia: date, sismos: list[dict], estado: str) -> None:
    """Guarda los sismos y marca el día como hecho en una sola transacción."""
    with conn:
        conn.executemany(
            """INSERT OR IGNORE INTO sismos
               (informe_url, fecha_local, fecha_utc, lugar, latitud, longitud,
                profundidad_km, magnitud, tipo_magnitud, dia_catalogo)
               VALUES (:informe_url, :fecha_local, :fecha_utc, :lugar, :latitud, :longitud,
                       :profundidad_km, :magnitud, :tipo_magnitud, :dia_catalogo)""",
            sismos,
        )
        conn.execute(
            "INSERT OR REPLACE INTO dias_scrapeados VALUES (?, ?, ?, ?)",
            (dia.isoformat(), len(sismos), estado, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )


def main() -> None:
    ayer = datetime.now(timezone.utc).date() - timedelta(days=1)

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--desde", type=date.fromisoformat, default=date(2000, 1, 1))
    parser.add_argument("--hasta", type=date.fromisoformat, default=ayer)
    parser.add_argument("--pausa", type=float, default=1.0, help="segundos entre peticiones (default 1)")
    parser.add_argument("--db", type=Path, default=DB_POR_DEFECTO)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    conn = conectar(args.db)
    pendientes = dias_pendientes(conn, args.desde, args.hasta)
    log.info("Rango %s a %s: %d días pendientes (base: %s)", args.desde, args.hasta, len(pendientes), args.db)

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    inicio = time.monotonic()

    for i, dia in enumerate(pendientes, start=1):
        html = descargar(session, CATALOGO_URL.format(d=dia))
        if html is None:
            guardar_dia(conn, dia, [], "sin_pagina")
            log.warning("%s: página no encontrada (404)", dia)
        else:
            sismos = parsear_dia(html, dia)
            if sismos is None:
                guardar_dia(conn, dia, [], "sin_tabla")
                log.warning("%s: la página no tiene la tabla del catálogo", dia)
            else:
                guardar_dia(conn, dia, sismos, "ok")

        if i % 50 == 0 or i == len(pendientes):
            total_sismos = conn.execute("SELECT COUNT(*) FROM sismos").fetchone()[0]
            transcurrido = time.monotonic() - inicio
            restante = transcurrido / i * (len(pendientes) - i)
            log.info("%d/%d días (hasta %s) · %d sismos en la base · faltan ~%.0f min",
                     i, len(pendientes), dia, total_sismos, restante / 60)

        time.sleep(args.pausa)

    conn.close()
    log.info("Listo.")


if __name__ == "__main__":
    main()
