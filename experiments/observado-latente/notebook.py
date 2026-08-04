"""Notebook marimo de `observado-latente`: el slider entre lo denunciado y lo latente.

Solo lee artefactos y presenta. No calcula desde datos crudos — eso vive en
``loader.py``, por la restricción de Pyodide (ver el docstring de ese archivo). En
particular, ni ``h3`` ni geopandas se importan acá: los vértices de los hexágonos
llegan precomputados en ``fronteras.parquet``.

    uv run python experiments/observado-latente/loader.py
    uv run marimo edit experiments/observado-latente/notebook.py
"""

import marimo

__generated_with = "0.23.16"
app = marimo.App(width="full")


@app.cell
def _():
    from pathlib import Path

    import marimo as mo
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from matplotlib.collections import PolyCollection

    from inwatch import canon

    return Path, PolyCollection, canon, mo, mpl, np, pd, plt


@app.cell
def _(mo):
    mo.md(
        """
        # Observado ↔ latente

        El mismo mapa, dos superficies, **una sola escala**. A la izquierda lo que la
        policía registró. A la derecha, lo que la encuesta de victimización implica que
        pasó — y el slider te lleva de una a la otra.

        Lo que hay que mirar no es que la derecha esté más oscura. Es **cuánto no se
        mueve el ranking** mientras la magnitud se multiplica por diez.

        **Sin datos ≠ seguro.** Las celdas sin una sola denuncia registrada en siete años
        se dibujan deshilachadas, nunca vacías ni verdes. Ausencia de denuncia es
        ausencia de evidencia, no evidencia de ausencia.
        """
    )
    return


@app.cell
def _(Path, pd):
    SLUG = "observado-latente"
    _dir = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG

    def _leer(nombre):
        p = _dir / f"{nombre}.parquet"
        if not p.exists():
            raise FileNotFoundError(
                f"falta el artefacto: {p}\n"
                f"  corre: uv run python experiments/{SLUG}/loader.py"
            )
        return pd.read_parquet(p)

    celdas = _leer("celdas")
    fronteras = _leer("fronteras")
    composicion = _leer("composicion").set_index("crime_cat")
    return celdas, composicion, fronteras


@app.cell
def _(celdas, fronteras, np):
    # Vértices → un array (n_celdas, 6, 2) en el MISMO orden que `celdas`. Se hace una
    # vez, fuera de las celdas reactivas: mover el slider no debe reconstruir polígonos.
    _orden = {h: i for i, h in enumerate(celdas["h3_index"])}
    _f = fronteras.sort_values(["h3_index", "vertice"], kind="stable")
    _xy = _f[["lng", "lat"]].to_numpy()
    _n_vert = len(_f) // len(_orden)
    _por_celda = _xy.reshape(len(_orden), _n_vert, 2)
    _idx = np.array([_orden[h] for h in _f["h3_index"].to_numpy()[::_n_vert]])
    poligonos = np.empty_like(_por_celda)
    poligonos[_idx] = _por_celda

    sin_registro = celdas["sin_registro"].to_numpy()
    obs = celdas["observado"].to_numpy(dtype=float)
    lat = celdas["latente"].to_numpy(dtype=float)
    ancho_ic = celdas["ic_ancho_rel"].to_numpy(dtype=float)
    return ancho_ic, lat, obs, poligonos, sin_registro


@app.cell
def _(canon, mpl):
    # Paleta del repo de origen (`carrera_teal`): secuencial de un solo tono,
    # luminosidad monótona. Legible en gris y sin falso semáforo — el verde para
    # "bajo riesgo" es justo la mentira que este repo existe para no cometer.
    CMAP = mpl.colors.LinearSegmentedColormap.from_list(
        "carrera_teal", ["#EDF3F2", "#A8CBC7", "#59A099", "#1F6F6B", "#0C3835"]
    )

    # UNA escala, fijada al techo de la superficie LATENTE y nunca renormalizada por
    # panel. Si cada panel se autoescala, ambos se ven igual de intensos y la brecha
    # —que es el hallazgo— desaparece. Decidido en infelix/scripts/figures_carrera.py.
    # El tope sale del registro, no de un quantile calculado acá: es una cifra portante
    # (decide cuánto del mapa cae en el primer escalón de color) y el notebook no
    # calcula. Es el percentil 99.5 y no el máximo porque la cola es larguísima.
    VMAX = canon.value("escala.tope")
    NORM = mpl.colors.Normalize(vmin=0.0, vmax=VMAX)
    return CMAP, NORM, VMAX


@app.cell
def _(mo):
    alpha = mo.ui.slider(
        0.0, 1.0, value=0.0, step=0.02, label="denuncias ←→ riesgo latente", full_width=True
    )
    honestidad = mo.ui.checkbox(
        value=True, label="codificar incertidumbre (opacidad ∝ estrechez del intervalo)"
    )
    corte_ic = mo.ui.slider(
        2.0, 12.0, value=12.0, step=0.5, label="declarar «no evaluable» sobre ancho de IC"
    )
    oscuro = mo.ui.checkbox(value=False, label="fondo oscuro")
    mo.vstack([alpha, mo.hstack([honestidad, corte_ic, oscuro], justify="start", gap=2)])
    return alpha, corte_ic, honestidad, oscuro


@app.cell
def _(canon, mo):
    # Los números portantes salen del registro, ya redondeados por la policy. Ninguno
    # se escribe a mano acá: ese fue el fallo que originó el mecanismo.
    _sin = canon.display("cobertura.celdas_sin_registro")
    _total = canon.display("cobertura.celdas_totales")
    mo.md(
        f"""
        | | |
        |---|---|
        | Multiplicador global (las 5 categorías) | **×{canon.display("multiplier.total")}** |
        | ρ de Spearman entre las dos superficies | **{canon.display("rango_espacial.spearman")}** |
        | Solapamiento del top-50 de celdas | **{canon.display("rango_espacial.top_overlap")}** |
        | Celdas sin una sola denuncia registrada | **{_sin}** de {_total} |
        """
    )
    return


@app.cell
def _(np):
    def superficie(obs, lat, a):
        """Interpolación lineal entre la superficie observada y la latente."""
        return (1.0 - a) * obs + a * lat

    def opacidades(ancho_ic, activa, corte):
        """Opacidad por celda: intervalo estrecho → sólido, ancho → desvaído.

        La estafa tiene un multiplicador enorme con un intervalo enorme. Pintarla con
        la misma solidez que el robo callejero sería mentir sobre lo que se sabe.
        """
        if not activa:
            return np.ones_like(ancho_ic)
        lo, hi = np.nanmin(ancho_ic), np.nanmax(ancho_ic)
        estrechez = 1.0 - (ancho_ic - lo) / max(hi - lo, 1e-9)
        op = 0.30 + 0.70 * np.clip(estrechez, 0.0, 1.0)
        return np.where(np.isnan(ancho_ic), 1.0, np.where(ancho_ic > corte, np.nan, op))

    return opacidades, superficie


@app.cell
def _(
    CMAP,
    NORM,
    PolyCollection,
    VMAX,
    alpha,
    ancho_ic,
    corte_ic,
    honestidad,
    lat,
    mpl,
    np,
    obs,
    opacidades,
    oscuro,
    plt,
    poligonos,
    sin_registro,
    superficie,
):
    INK = "#E8EDEC" if oscuro.value else "#1F2A33"
    MUTED = "#9AA7AE" if oscuro.value else "#55636E"
    HILO = "#7E8C95" if oscuro.value else "#AEB9BF"  # el hilo del deshilachado

    # El deshilachado tiene que leerse como ausencia, no como una capa más. Con el
    # ancho de trama por defecto (1.0) las 924 celdas sin registro forman una malla
    # que se come el mapa y la ausencia termina gritando más que el dato.
    mpl.rcParams["hatch.linewidth"] = 0.3

    _op = opacidades(ancho_ic, honestidad.value, corte_ic.value)
    # Una celda es "no evaluable" si no hay registro, o si el intervalo es tan ancho
    # que el número no sostiene un color. Ambas se dibujan deshilachadas: sin relleno,
    # solo trama. Nunca vacías, nunca verdes.
    _deshilachada = sin_registro | np.isnan(_op)
    _pintable = ~_deshilachada

    def _panel(ax, valores, titulo, pie):
        ax.patch.set_alpha(0)
        rgba = CMAP(NORM(valores[_pintable]))
        rgba[:, 3] = np.nan_to_num(_op[_pintable], nan=1.0)
        ax.add_collection(
            PolyCollection(poligonos[_pintable], facecolors=rgba, linewidths=0.0)
        )
        ax.add_collection(
            PolyCollection(
                poligonos[_deshilachada],
                facecolors="none",
                edgecolors=HILO,
                linewidths=0.18,
                alpha=0.55,
                hatch="/",
            )
        )
        ax.set_xlim(poligonos[..., 0].min(), poligonos[..., 0].max())
        ax.set_ylim(poligonos[..., 1].min(), poligonos[..., 1].max())
        ax.set_aspect(1.0 / np.cos(np.radians(-12.05)))
        ax.set_title(titulo, fontsize=12.5, color=INK, pad=10)
        ax.axis("off")
        ax.annotate(
            pie,
            xy=(0.5, -0.01),
            xycoords="axes fraction",
            ha="center",
            va="top",
            fontsize=9,
            color=MUTED,
        )

    _v = superficie(obs, lat, alpha.value)
    fig_mapa, _axes = plt.subplots(1, 2, figsize=(9.5, 6.4))
    fig_mapa.patch.set_alpha(0)
    def _miles(x):
        return f"{x:,.0f}".replace(",", " ")

    _panel(_axes[0], obs, "Lo que registra la policía", f"pico {_miles(obs.max())} hechos")
    _panel(
        _axes[1],
        _v,
        f"Corrección aplicada al {alpha.value:.0%}",
        f"pico {_miles(_v.max())} hechos",
    )

    _sm = mpl.cm.ScalarMappable(norm=NORM, cmap=CMAP)
    _cax = fig_mapa.add_axes([0.30, 0.09, 0.40, 0.022])
    _cb = fig_mapa.colorbar(_sm, cax=_cax, orientation="horizontal", extend="max")
    _cb.set_label(
        "Hechos por celda H3 res-8, acumulados 2018–2024 · escala compartida",
        fontsize=9,
        color=MUTED,
        labelpad=7,
    )
    _cb.set_ticks([t for t in np.linspace(0, VMAX, 5)])
    _cb.set_ticklabels([f"{t:,.0f}".replace(",", " ") for t in np.linspace(0, VMAX, 5)])
    _cb.ax.tick_params(labelsize=8.5, colors=MUTED, length=2)
    _cb.outline.set_visible(False)
    fig_mapa.subplots_adjust(left=0.02, right=0.98, top=0.94, bottom=0.20, wspace=0.02)
    fig_mapa
    return INK, MUTED


@app.cell
def _(alpha, canon, mo, obs, superficie, lat):
    _v = superficie(obs, lat, alpha.value)
    mo.md(
        f"""
        Con la corrección al **{alpha.value:.0%}**, el pico del mapa pasa de
        {obs.max():,.0f} a **{_v.max():,.0f}** hechos por celda. El mapa se oscurece
        entero — pero mira la siguiente vista antes de concluir que cambió.

        El ranking entre celdas se mueve poquísimo: ρ de Spearman
        **{canon.display("rango_espacial.spearman")}**, y
        **{canon.display("rango_espacial.top_overlap")}** de las 50 celdas más cargadas
        son las mismas en las dos superficies. Corregir por subdenuncia **no reordena el
        mapa**; cambia su magnitud y su composición. Es un resultado más honesto, y más
        incómodo, que un «todo cambia».
        """
    )
    return


@app.cell
def _(INK, MUTED, lat, np, obs, plt, sin_registro):
    # Rango observado vs rango latente. Si la corrección reordenara el mapa, esta nube
    # se abriría; que se pegue a la diagonal ES el hallazgo.
    _m = ~sin_registro
    _ro = obs[_m].argsort().argsort()
    _rl = lat[_m].argsort().argsort()

    fig_rango, _ax = plt.subplots(figsize=(5.2, 5.2))
    fig_rango.patch.set_alpha(0)
    _ax.patch.set_alpha(0)
    _ax.plot([0, _m.sum()], [0, _m.sum()], lw=0.8, color=MUTED, ls="--", zorder=1)
    _ax.scatter(_ro, _rl, s=4, color="#1F6F6B", alpha=0.35, linewidths=0, zorder=2)
    _ax.set_xlabel("rango en la superficie observada", fontsize=9.5, color=MUTED)
    _ax.set_ylabel("rango en la superficie latente", fontsize=9.5, color=MUTED)
    _ax.set_title(
        f"{_m.sum():,} celdas con registro".replace(",", " "),
        fontsize=11,
        color=INK,
        pad=8,
    )
    for _s in _ax.spines.values():
        _s.set_visible(False)
    _ax.tick_params(labelsize=8, colors=MUTED, length=2)
    _ax.set_xlim(0, _m.sum())
    _ax.set_ylim(0, _m.sum())
    _ax.set_aspect(1)
    fig_rango
    return


@app.cell
def _(INK, MUTED, composicion, canon, np, plt):
    # Lo que SÍ cambia. La composición de delito se da vuelta: el robo callejero deja
    # de ser la mitad del mapa y la estafa —la categoría con peor tasa de denuncia—
    # pasa a ser un tercio.
    _cats = list(composicion.index)
    _et = {
        "robo_hurto_callejero": "Robo y hurto callejero",
        "violencia_familiar_sexual": "Violencia familiar y sexual",
        "extorsion": "Extorsión",
        "secuestro": "Secuestro",
        "estafa": "Estafa",
    }
    _y = np.arange(len(_cats))
    _o = [float(canon.value(f"superficie_share_observado.{c}")) for c in _cats]
    _l = [float(canon.value(f"superficie_share_latente.{c}")) for c in _cats]

    fig_comp, _ax = plt.subplots(figsize=(7.4, 3.4))
    fig_comp.patch.set_alpha(0)
    _ax.patch.set_alpha(0)
    _ax.barh(_y - 0.19, _o, height=0.34, color="#A8CBC7", label="denunciado")
    _ax.barh(_y + 0.19, _l, height=0.34, color="#1F6F6B", label="latente")
    for _i, (_a, _b) in enumerate(zip(_o, _l, strict=True)):
        _ax.annotate(
            f"{_a:.1f}%", (_a + 0.8, _i - 0.19), va="center", fontsize=8, color=MUTED
        )
        _ax.annotate(
            f"{_b:.1f}%", (_b + 0.8, _i + 0.19), va="center", fontsize=8, color=MUTED
        )
    _ax.set_yticks(_y, [_et[c] for c in _cats], fontsize=9.5, color=INK)
    _ax.invert_yaxis()
    _ax.set_xlim(0, 62)
    _ax.set_xlabel("% de la superficie", fontsize=9.5, color=MUTED)
    for _s in _ax.spines.values():
        _s.set_visible(False)
    _ax.tick_params(labelsize=8.5, colors=MUTED, length=0)
    _ax.legend(frameon=False, fontsize=9, labelcolor=MUTED, loc="lower right")
    _ax.set_title("Lo que sí se da vuelta: la composición", fontsize=11, color=INK, pad=8)
    fig_comp
    return


@app.cell
def _(canon, mo):
    mo.md(
        f"""
        ## Qué no dice esta vista

        - **Las celdas deshilachadas no son seguras.** Son
          {canon.display("cobertura.celdas_sin_registro")} de
          {canon.display("cobertura.celdas_totales")} celdas donde nadie denunció nada en
          siete años. El estimador latente allí también es cero, y por la misma razón:
          se construye multiplicando lo denunciado. Donde no hubo denuncia, la corrección
          no tiene de qué agarrarse. Es el límite del método, no una zona tranquila.
        - **La estafa domina el latente y es la menos confiable.** Su multiplicador es
          ×{canon.display("multiplier.estafa")} con un intervalo que abarca casi dos
          órdenes de magnitud. Por eso pesa en la opacidad y por eso el control de «no
          evaluable» existe: bájalo y mira cuánto mapa desaparece.
        - **El intervalo por celda suma los extremos de las cinco categorías**, que
          asume que se equivocan todas en la misma dirección. Es una cota conservadora,
          no un intervalo conjunto.
        - **Nada acá es un ruteo.** Un hexágono H3 res-8 promedia sobre el borde entre
          tejidos urbanos distintos; el escalón que la escalera de atribución encontró
          significativo es la manzana censal. Ver `design/contrato-unidades.md`.
        """
    )
    return


if __name__ == "__main__":
    app.run()
