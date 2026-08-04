"""Notebook marimo del experimento <slug>.

Solo lee artefactos y presenta. No calcula desde datos crudos — eso vive en
``loader.py``, por la restricción de Pyodide (ver el docstring de ese archivo).

    uv run marimo edit experiments/<slug>/notebook.py
"""

import marimo

__generated_with = "0.23.16"
app = marimo.App(width="full")


@app.cell
def _():
    from pathlib import Path

    import marimo as mo
    import pandas as pd

    from inwatch import canon

    return Path, canon, mo, pd


@app.cell
def _(mo):
    mo.md(
        """
        # <título>

        <Una frase sobre qué se está viendo y qué se puede mover.>

        **Sin datos ≠ seguro.** Las unidades sin registro se dibujan deshilachadas.
        Ausencia de denuncia es ausencia de evidencia, no evidencia de ausencia.
        """
    )
    return


@app.cell
def _(Path, pd):
    SLUG = "<slug>"
    _art = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG / f"{SLUG}.parquet"
    if not _art.exists():
        raise FileNotFoundError(
            f"falta el artefacto: {_art}\n"
            f"  corre: uv run python experiments/{SLUG}/loader.py"
        )
    df = pd.read_parquet(_art)
    return SLUG, df


@app.cell
def _(mo):
    # El control que hace del experimento un experimento.
    control = mo.ui.slider(0, 1, value=0, step=0.01, label="<qué se mueve>")
    control
    return (control,)


@app.cell
def _(canon, mo):
    # Los números portantes salen del registro, ya redondeados por la policy.
    # Nunca se escriben a mano acá.
    mo.md(f"Multiplicador canónico: **{canon.display('<key>')}**")
    return


@app.cell
def _(control, df, mo):
    # La vista. Recordatorio: rampa de luminosidad monótona, verificada en
    # deuteranopia, y sin verde para "bajo riesgo".
    mo.md(f"<vista con {len(df):,} unidades · control en {control.value}>")
    return


if __name__ == "__main__":
    app.run()
