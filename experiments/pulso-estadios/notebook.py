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
        r"""
        ## Hito 2 · ¿el pulso sobrevive a recortar el espacio de otra forma?

        Hasta acá, «cerca del estadio» fue un disco. Abajo se recorta igual —mismos
        puntos, mismos días tratados, mismos controles, mismo estimador— pero de otras
        tres formas:

        - `anillo` — la réplica del hito 1: distancia en línea recta al estadio.
        - `banda_red` — distancia **caminando** sobre la red peatonal de OSM, con los
          mismos cortes en metros de red.
        - `banda_red_area` — la misma distancia de red, con cortes elegidos para que
          cada banda tenga **el área** del disco euclidiano: separa forma de tamaño.
        - `morfologica` — saltos de celda en celda sobre la tesselación de E5, con
          cortes igualados por área de tejido.

        ### El criterio, fijado antes de calcular

        Se escribió aquí y se commiteó **antes** de correr `loader_unidades.py`; el
        historial de la rama lo muestra.

        **Métrica primaria (M1)**: el rate-ratio MH en la ventana kickoff ± 4 h, banda
        interior, variante multitud, los tres estadios juntos —el mismo contraste que
        `pulso.rr_puerta`, calculado en cada unidad—.

        **El pulso sobrevive en la unidad U** si se cumplen las tres:

        1. el IC 95 % bootstrap de M1 en U tiene límite inferior **> 1**;
        2. la falsificación se sostiene: en dosis cero, el mismo contraste tiene límite
           inferior **≤ 1**;
        3. hay gradiente: el RR de la banda interior supera al de la exterior.

        **Magnitud**: M1 **se mueve** si el IC 95 % del bootstrap **pareado** —mismos días
        tratados remuestreados en todas las unidades— de log(RR_U / RR_anillo) excluye 0.
        El movimiento es **material** si además la razón puntual cae fuera de
        [0,8 ; 1,25].

        **Secundaria, descriptiva y sin veredicto**: el perfil horario. Un bin es
        **medible** sólo si cumple a la vez las dos nociones de soporte que hoy conviven
        (inwatch-ap1): `n_control ≥ PISO_CONTROL` (= 2, el piso de la pieza) **y**
        `n_control_estratos > 0` **y** `n_estratos_soporte ≥ 30`. Lo no medible se
        dibuja deshilachado. Los `n_control` de cada bin están en la tabla de abajo.
        """
    )
    return


@app.cell
def _(Path, pd):
    _dir = Path(__file__).resolve().parents[2] / "data" / "silver" / "pulso-estadios"
    _faltan = [n for n in ("perfil_unidades", "ventana_unidades", "masa_unidades",
                           "cortes_unidades", "correspondencia_unidades")
               if not (_dir / f"{n}.parquet").exists()]
    if _faltan:
        raise FileNotFoundError(
            f"faltan artefactos del hito 2: {_faltan}\n"
            "  corre: uv run --extra geo python experiments/pulso-estadios/loader_unidades.py"
            )
    perfil_u = pd.read_parquet(_dir / "perfil_unidades.parquet")
    ventana_u = pd.read_parquet(_dir / "ventana_unidades.parquet")
    masa_u = pd.read_parquet(_dir / "masa_unidades.parquet")
    cortes_u = pd.read_parquet(_dir / "cortes_unidades.parquet")
    corr_u = pd.read_parquet(_dir / "correspondencia_unidades.parquet")
    return corr_u, cortes_u, masa_u, perfil_u, ventana_u


@app.cell
def _(mo):
    unidades_sel = mo.ui.multiselect(
        options=["anillo", "banda_red", "banda_red_area", "morfologica"],
        value=["anillo", "banda_red", "morfologica"],
        label="unidades a superponer",
    )
    banda_sel = mo.ui.dropdown(
        options={"interior (0-500 m o equivalente)": 0, "500-1000 m": 1,
                 "1-2 km": 2, "exterior (2-4 km)": 3},
        value="interior (0-500 m o equivalente)", label="banda",
    )
    variante_u = mo.ui.radio(
        options={"multitud (full)": "full", "dosis cero (none)": "none"},
        value="multitud (full)", label="variante",
    )
    mo.hstack([unidades_sel, banda_sel, variante_u], justify="start", gap=2)
    return banda_sel, unidades_sel, variante_u


@app.cell
def _(banda_sel, np, perfil_u, plt, unidades_sel, variante_u):
    # Una sola escala: log2 del RR. El exceso en conteos no sirve para comparar unidades,
    # porque depende del área de la banda —y las bandas de red y de tejido no tienen el
    # área del disco—; el RR es un cociente intra-banda y no.
    _colores = {"anillo": "#1f4e79", "banda_red": "#b35806",
                "banda_red_area": "#b35806", "morfologica": "#542788"}
    _estilo = {"banda_red_area": (0, (4, 2))}
    fig_u, ax_u = plt.subplots(figsize=(10, 4.4))
    ax_u.axhline(0, color="0.55", lw=1)
    ax_u.axvline(0, color="#c0392b", lw=1.2, ls="--")
    for _u in unidades_sel.value:
        _d = perfil_u[(perfil_u["unidad"] == _u) & (perfil_u["banda"] == banda_sel.value)
                      & (perfil_u["variante"] == variante_u.value)].sort_values("offset_h")
        _x = _d["offset_h"].to_numpy()
        with np.errstate(divide="ignore"):
            _y = np.log2(_d["rr"].to_numpy())
        _y = np.clip(_y, -4, 4)
        _m = _d["medible"].to_numpy() & np.isfinite(_y)
        ax_u.plot(np.where(_m, _x, np.nan), np.where(_m, _y, np.nan),
                  color=_colores[_u], ls=_estilo.get(_u, "-"), lw=2, marker="o", ms=3.5,
                  label=_u)
        ax_u.plot(np.where(~_m, _x, np.nan), np.where(~_m, _y, np.nan),
                  color=_colores[_u], ls=":", lw=1, alpha=0.4, marker="o", ms=2.5)
    ax_u.set_yticks(range(-4, 5), [f"{2.0 ** k:g}×" for k in range(-4, 5)])
    ax_u.set_ylim(-4.2, 4.2)
    ax_u.set_xlabel("horas relativas al kickoff")
    ax_u.set_ylabel("rate-ratio tratado/control (escala log2, capado a 16×)")
    ax_u.set_title(f"banda {banda_sel.value} · {variante_u.value} · punteado = no medible "
                   "(sin dato ≠ seguro)")
    ax_u.legend(frameon=False, fontsize=8, loc="upper left")
    ax_u.spines[["top", "right"]].set_visible(False)
    fig_u.tight_layout()
    fig_u
    return


@app.cell
def _(np, pd, ventana_u):
    # El criterio aplicado a lo que dejó el loader. No recalcula nada desde datos: lee
    # la tabla de la ventana y compara contra los umbrales fijados arriba.
    def _veredicto(_v):
        _filas = []
        for _u, _g in _v.groupby("unidad", sort=False):
            _f0 = _g[(_g["banda"] == 0) & (_g["variante"] == "full")].iloc[0]
            _n0 = _g[(_g["banda"] == 0) & (_g["variante"] == "none")].iloc[0]
            _f3 = _g[(_g["banda"] == 3) & (_g["variante"] == "full")].iloc[0]
            _i, _ii, _iii = _f0["ic_low"] > 1, _n0["ic_low"] <= 1, _f0["rr"] > _f3["rr"]
            _razon = float(np.exp(_f0["log_razon_vs_anillo"]))
            _mueve = not (_f0["log_razon_ic_low"] <= 0 <= _f0["log_razon_ic_high"])
            _filas.append({
                "unidad": _u, "RR banda 0": _f0["rr"],
                "IC95": f"{_f0['ic_low']:.2f}–{_f0['ic_high']:.2f}",
                "n_tratado": _f0["n_tratado"], "n_control": _f0["n_control"],
                "(i) ic_low>1": _i, "(ii) dosis cero ic_low≤1": _ii,
                "(iii) gradiente": _iii, "SOBREVIVE": _i and _ii and _iii,
                "razón vs anillo": _razon,
                "IC95 razón pareado": (f"{np.exp(_f0['log_razon_ic_low']):.2f}–"
                                       f"{np.exp(_f0['log_razon_ic_high']):.2f}"),
                "se mueve": _mueve and _u != "anillo",
                "material": (_mueve and _u != "anillo"
                             and not (0.8 <= _razon <= 1.25)),
            })
        return pd.DataFrame(_filas)

    veredicto = _veredicto(ventana_u)
    veredicto
    return


@app.cell
def _(mo):
    mo.md(
        """
        ### El soporte, bin por bin

        `n_control` es el número de eventos en el denominador de cada bin horario (suma
        sobre los días control). Con 1 o 0 el cociente no es una medición: es la razón
        de `PISO_CONTROL`. La tabla muestra las cuatro unidades para la banda y la
        variante elegidas arriba.
        """
    )
    return


@app.cell
def _(banda_sel, perfil_u, variante_u):
    _d = perfil_u[(perfil_u["banda"] == banda_sel.value)
                  & (perfil_u["variante"] == variante_u.value)]
    _d.pivot_table(index="offset_h", columns="unidad", values="n_control",
                   aggfunc="first")
    return


@app.cell
def _(mo):
    mo.md(
        """
        ### Qué se pierde al cambiar de unidad

        Masa: de los puntos que el anillo mide dentro de 4 km, cuántos se quedan sin
        banda en cada unidad porque no hay red caminable o tejido registrado debajo. Esos
        puntos **no se reasignan** a la celda más cercana: sería inventar tejido donde
        OSM no tiene edificios. Cortes: los umbrales efectivos y el área de cada banda,
        junto al área del disco euclidiano del mismo corte.
        """
    )
    return


@app.cell
def _(masa_u):
    masa_u
    return


@app.cell
def _(cortes_u):
    cortes_u
    return


@app.cell
def _(corr_u):
    # Correspondencia anillo ↔ cada unidad, sobre una rejilla de píxeles de 25 m. Toda
    # banda de origen suma 1 contando la fila −1 (fuera de toda banda de destino): ése
    # es el test de masa del contrato de unidades.
    corr_u
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Lo que este hito todavía no responde

        El hito 2 recorta por la red que la gente camina, pero no por la que la trae:
        la distancia se mide desde el estadio y no desde las estaciones del
        Metropolitano y la Línea 1. Una banda centrada en las estaciones —o un corte por
        tiempo de viaje en transporte— es la pregunta siguiente. Y ninguna cifra de este
        hito es portante todavía: el loader no emite al registro hasta que se adjudique
        el soporte (inwatch-ap1) y se decida qué unidad es canónica.
        """
    )
    return


if __name__ == "__main__":
    app.run()
