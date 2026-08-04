"""Precómputo del experimento <slug>: artefactos crudos → parquet listo para presentar.

Esta capa existe porque ``marimo`` exporta a WASM sobre Pyodide, donde geopandas y
PyTorch Geometric **no corren**. Todo lo pesado ocurre acá, una vez, y deja un parquet;
el notebook solo lee. Si el notebook necesita recalcular algo desde datos crudos, la
separación se rompió.

Contrato de salida:
  - una clave de unidad declarada (ver ``design/contrato-unidades.md``)
  - las columnas de cobertura junto a las de valor, nunca sin ellas
  - determinista: dos corridas sobre los mismos inputs dan el mismo hash
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from inwatch import canon

SLUG = "<slug>"
# Read-only. El repo de origen nunca se modifica desde acá.
SOURCE = Path("/home/rosewt-dell/Code/tesis/infelix/data/silver")
OUT = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG


def build() -> pd.DataFrame:
    """Construye la tabla del experimento. Una fila por unidad espacial."""
    raise NotImplementedError("reemplazar: leer de SOURCE, unir, devolver el DataFrame")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = build()

    # Las cifras portantes se emiten acá, con procedencia — nunca se copian a mano a
    # un README o a un notebook.
    canon.emit(
        f"{SLUG}.<familia>",
        float(df["<columna>"].mean()),
        variant="<variant>",
        unit="<unidad de medida>",
        estimator="<cómo se calculó, en una línea>",
        inputs=[SOURCE / "<archivo fuente>"],
        script=__file__,
    )

    dest = OUT / f"{SLUG}.parquet"
    df.to_parquet(dest, index=False)
    print(f"  → {dest}  ({len(df):,} filas)")


if __name__ == "__main__":
    main()
