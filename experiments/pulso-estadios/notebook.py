"""Notebook marimo de `pulso-estadios`: el pulso de crimen alrededor de un partido.

Solo lee artefactos y presenta. No calcula desde datos crudos — eso vive en
``loader.py``, que además explica por qué este port no pudo ser una transliteración.

    uv run python experiments/pulso-estadios/loader.py
    uv run marimo edit experiments/pulso-estadios/notebook.py
"""

import marimo

__generated_with = "0.23.16"
app = marimo.App(width="full")


@app.cell
def _():
    from pathlib import Path

    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    return Path, mo, np, pd, plt


@app.cell
def _(mo):
    mo.md(
        """
        # El pulso de estadios

        Un partido mete decenas de miles de personas en un punto de la ciudad durante
        unas pocas horas. Si el crimen denunciado sube alrededor del estadio ese día,
        compiten dos explicaciones: **hay más delito** o **hay más gente que denuncia**.

        El diseño las separa. La misma celda es su propio control —el mismo estadio, el
        mismo día de semana, el mismo mes, sin partido— así que el sesgo de denuncia,
        que es aproximadamente estático por celda, se cancela en el contraste.

        El eje X no es un control: es el dominio. Lo que se manipula abajo es **el
        anillo**, **la variante de evento** y **la escala a latente**.
        """
    )
    return


@app.cell
def _(Path, pd):
    _dir = Path(__file__).resolve().parents[2] / "data" / "silver" / "pulso-estadios"
    perfil = pd.read_parquet(_dir / "perfil.parquet")
    ancla = pd.read_parquet(_dir / "ancla.parquet")
    return ancla, perfil


@app.cell
def _(mo, perfil):
    anillo = mo.ui.dropdown(
        options=list(perfil["anillo"].unique()),
        value="r0_500",
        label="anillo",
    )
    variante = mo.ui.radio(
        options={"multitud (full)": "full", "dosis cero (none)": "none"},
        value="multitud (full)",
        label="variante de evento",
    )
    # r̂ distrital de robo. El deslizador escala el exceso observado a latente-implicado.
    # Es un ESCALADO declarado, no una estimación fina: r̂ es distrital y estático, y el
    # supuesto que lo hace admisible es justo el que el diseño intra-celda explota.
    r_hat = mo.ui.slider(
        start=0.05, stop=1.0, step=0.01, value=1.0,
        label="r̂ (1.00 = observado; bajarlo escala a latente-implicado)",
    )
    soporte_min = mo.ui.slider(
        start=0, stop=200, step=5, value=30,
        label="estratos tratados mínimos para dibujar en firme",
    )
    mo.hstack([anillo, variante, r_hat, soporte_min], justify="start", gap=2)
    return anillo, r_hat, soporte_min, variante


@app.cell
def _(anillo, mo, np, perfil, plt, r_hat, soporte_min, variante):
    d = perfil[(perfil["anillo"] == anillo.value)
               & (perfil["variante"] == variante.value)].sort_values("offset_h")

    x = d["offset_h"].to_numpy()
    exceso = d["exceso"].to_numpy() / r_hat.value

    # Qué cuenta como "sin dato" y qué como "el dato es cero". La distinción es la regla
    # dura del repo y acá se juega entera: un bin se dibuja deshilachado sólo si le
    # faltan estratos tratados, si no tiene controles con los que contrastar, o si el
    # bootstrap no pudo devolver intervalo. Un bin bien soportado cuyo exceso da cero se
    # dibuja EN FIRME — ese cero es el hallazgo, sobre todo en la variante dosis-cero y
    # en los anillos exteriores.
    firme = (
        (d["n_estratos_soporte"].to_numpy() >= soporte_min.value)
        & (d["n_control_estratos"].to_numpy() > 0)
        & np.isfinite(d["ic_low"].to_numpy())
        & np.isfinite(d["ic_high"].to_numpy())
    )

    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.axhline(0, color="0.55", lw=1)
    ax.axvline(0, color="#c0392b", lw=1.2, ls="--")
    ax.annotate("kickoff", (0, ax.get_ylim()[1]), color="#c0392b",
                fontsize=9, ha="center", va="bottom")

    # Regla dura del repo: lo que se apoya en pocos días se dibuja DESHILACHADO, no
    # plano. Un tramo punteado y translúcido dice "acá no sabemos"; una línea sólida
    # en cero diría "acá no pasa nada", que es una afirmación que el dato no sostiene.
    ax.plot(np.where(firme, x, np.nan), np.where(firme, exceso, np.nan),
            color="#1f4e79", lw=2.2, marker="o", ms=4, label="soporte suficiente")
    ax.plot(np.where(~firme, x, np.nan), np.where(~firme, exceso, np.nan),
            color="#1f4e79", lw=1.1, ls=":", alpha=0.45, marker="o", ms=3,
            label="soporte escaso — sin dato ≠ seguro")

    ax.set_xlabel("horas relativas al kickoff")
    ax.set_ylabel("exceso de denuncias" if r_hat.value == 1.0
                  else "exceso latente-implicado (escalado por r̂)")
    ax.set_title(f"{anillo.value} · variante {variante.value}")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig
    return


@app.cell
def _(mo, variante):
    mo.md(
        """
        La variante **dosis cero** es la falsificación incorporada: son partidos sin
        público. Si el pulso apareciera también ahí, no sería la multitud lo que lo
        produce, y el diseño entero se caería.
        """
        if variante.value == "none" else
        """
        Cámbialo a **dosis cero** para ver la falsificación: partidos sin público. Ahí
        el pulso debe aplanarse o irse a negativo.
        """
    )
    return


@app.cell
def _(ancla, mo):
    mo.md(
        f"""
        ## La réplica contra el ancla

        El criterio de cierre de este hito no es que la curva se vea bien: es que el
        contraste de kickoff±4h reproduzca el resultado ya computado en el repo de
        origen. Mayor desviación relativa observada: **{ancla["delta_rr_rel"].max():.3%}**.

        Importa más de lo que parece. El script que produjo esas cifras **ya no corre**
        en infelix —tiene el import roto contra un módulo que fue refactorizado sin
        actualizarlo—, así que mientras eso siga así esta tabla es el único chequeo
        ejecutable que existe sobre ellas.
        """
    )
    return


@app.cell
def _(ancla):
    ancla[["spec", "ring", "rr", "ci_lo", "ci_hi", "rr_infelix",
           "delta_rr_rel", "treated_days"]]
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Lo que este hito todavía no responde

        Todo lo de arriba recorta el espacio en **anillos euclidianos**. Pero el propio
        repo de origen escribió que *la multitud no llega en círculos, llega por el
        Metropolitano y la Línea 1* — y aun así midió con buffers. El hito 2 añade el
        corte por red de calles y por celda morfológica, y entonces el selector de
        unidad se vuelve el control interesante: si el pulso se mueve al cambiarlo, el
        anillo estaba haciendo trabajo silencioso.
        """
    )
    return


if __name__ == "__main__":
    app.run()
