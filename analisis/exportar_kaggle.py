"""
Genera los archivos del dataset para Kaggle en kaggle/:
- sismos_csn_2000_2026.csv: el catálogo completo tal como lo publica el CSN (sin los filtros del análisis)
- sismos.db: copia de la base SQLite
- resumen.json: cifras para la descripción del dataset

Uso:
    python analisis/exportar_kaggle.py
"""

import json
import shutil
import sqlite3

import pandas as pd

from datos import DB, RAIZ_PROYECTO

SALIDA = RAIZ_PROYECTO / "kaggle"
URL_BASE = "https://www.sismologia.cl"

COLUMNAS = [
    "id_informe",
    "fecha_utc",
    "fecha_local",
    "latitud",
    "longitud",
    "profundidad_km",
    "magnitud",
    "tipo_magnitud",
    "lugar",
    "dia_catalogo",
    "url_informe",
]


def main() -> None:
    SALIDA.mkdir(exist_ok=True)
    with sqlite3.connect(DB) as conn:
        df = pd.read_sql("SELECT * FROM sismos ORDER BY fecha_utc", conn)
        dias = pd.read_sql("SELECT * FROM dias_scrapeados ORDER BY dia", conn)

    # Identificador del informe del CSN (último tramo de la URL) y URL completa
    df["id_informe"] = df.informe_url.str.extract(r"(\d{4}/\d{2}/\d+)\.html$")[0].str.replace("/", "-")
    df["url_informe"] = URL_BASE + df.informe_url
    csv = SALIDA / "sismos_csn_2000_2026.csv"
    df[COLUMNAS].to_csv(csv, index=False, encoding="utf-8")

    shutil.copy2(DB, SALIDA / "sismos.db")

    resumen = {
        "filas": len(df),
        "desde": df.fecha_utc.min(),
        "hasta": df.fecha_utc.max(),
        "dias_descargados": len(dias),
        "dias_sin_sismos": int((dias.n_sismos == 0).sum()),
        "magnitud_min": float(df.magnitud.min()),
        "magnitud_max": float(df.magnitud.max()),
        "profundidad_max_km": float(df.profundidad_km.max()),
        "tipos_magnitud": df.tipo_magnitud.value_counts().to_dict(),
        "tamano_csv_mb": round(csv.stat().st_size / 1e6, 1),
        "tamano_db_mb": round((SALIDA / "sismos.db").stat().st_size / 1e6, 1),
    }
    (SALIDA / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
