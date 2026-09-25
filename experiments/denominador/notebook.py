"""Notebook marimo de `denominador` (E7): riesgo por expuesto, no por residente.

Solo lee artefactos y presenta. No calcula desde datos crudos: todo vive en
``loader.py``, por la restricción de Pyodide. Ni ``h3`` ni geopandas se importan acá;
los hexágonos llegan precomputados en ``fronteras.parquet``. Lo único que se hace acá es
ordenar en percentiles una columna ya calculada, para pintarla.

Exploratorio: las cifras de este notebook salen de los parquets del loader, NO del
registro canónico (todavía no se emiten). Las de E1 sí salen del registro.

    uv run python experiments/denominador/loader.py
    uv run marimo edit experiments/denominador/notebook.py
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
        # El denominador: riesgo por expuesto, no por residente

        Todo mapa de riesgo del programa dividía entre **residentes**. Pero una persona se
        expone donde *está*, no donde duerme: Mesa Redonda tiene una población flotante
        enorme y pocos residentes. Acá se cambia el denominador —de residentes (WorldPop) a
        población **ambiente** (LandScan, promedio de 24 h)— y se mide si el mapa se
        **reordena**, con las mismas métricas con las que E1 encontró que la corrección
        por sesgo de denuncia *no* lo reordena.

        **El control que protege la conclusión**: Meta/HRSL es un *segundo* residencial.
        Si cambiar entre dos residenciales reordena tanto como pasar a ambiente, lo que
        mueve el mapa es ruido entre rasters, no la distinción conceptual.

        **Sin datos ≠ seguro.** Una celda con menos población que el piso en cualquiera de
        las tres fuentes se dibuja deshilachada: su riesgo no es cero, es no evaluable.
        """
    )
    return


@app.cell
def _(Path, pd):
    SLUG = "denominador"
    _dir = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG

    def _leer(nombre):
        p = _dir / f"{nombre}.parquet"
        if not p.exists():
            raise FileNotFoundError(
                f"falta el artefacto: {p}\n  corre: uv run python experiments/{SLUG}/loader.py"
            )
        return pd.read_parquet(p)

    art = {
        n: _leer(n)
        for n in (
            "celdas",
            "fronteras",
            "reordenamiento",
            "bootstrap",
            "pares",
            "suavizado",
            "agregado",
            "circularidad",
            "intra_distrito",
            "resolucion",
            "direccional",
            "por_distrito",
            "mesa_redonda",
        )
    }
    celdas = art["celdas"]
    return art, celdas


@app.cell
def _(celdas, np, art):
    # Vértices → (n_celdas, 6, 2) en el mismo orden que `celdas`, una sola vez.
    _f = art["fronteras"].sort_values(["h3_index", "vertice"], kind="stable")
    _orden = {h: i for i, h in enumerate(celdas["h3_index"])}
    _n_vert = len(_f) // len(_orden)
    _por = _f[["lng", "lat"]].to_numpy().reshape(len(_orden), _n_vert, 2)
    _idx = np.array([_orden[h] for h in _f["h3_index"].to_numpy()[::_n_vert]])
    poligonos = np.empty_like(_por)
    poligonos[_idx] = _por
    return (poligonos,)


@app.cell
def _(mo):
    NUMS = {
        "latente híbrido (patrón intra-distrital de denuncias geocodificadas)": "latente_hibrido",
        "denuncias geocodificadas crudas": "observado_geo",
        "latente de E1 — CIRCULAR, repartido con WorldPop": "latente",
    }
    DENS = {
        "ambiente — LandScan 2023": "ambiente",
        "otro residencial — Meta/HRSL (control)": "residente_meta",
        "ambiente — LandScan 2020 (control temporal)": "ambiente_2020",
    }
    numerador = mo.ui.dropdown(NUMS, value=list(NUMS)[0], label="numerador")
    denominador = mo.ui.dropdown(DENS, value=list(DENS)[0], label="comparar residente contra")
    piso = mo.ui.dropdown(
        {str(p): p for p in (0, 200, 500, 1000, 2000)},
        value="500",
        label="piso de población (en las 3 fuentes)",
    )
    oscuro = mo.ui.checkbox(value=False, label="fondo oscuro")
    mo.hstack([numerador, denominador, piso, oscuro], justify="start", gap=2)
    return denominador, numerador, oscuro, piso


@app.cell
def _(art, canon, denominador, mo, numerador, piso):
    _r = art["reordenamiento"]
    _r = _r[(_r["piso"] == piso.value) & (_r["numerador"] == numerador.value)].set_index(
        "contraste"
    )
    _et = {
        "correccion_sesgo": "E1 en estas mismas celdas: observado → latente, ambos por residente",
        "residente_meta": "residente → otro residencial (Meta/HRSL) · el control",
        "ambiente_2020": "residente → ambiente 2020",
        "ambiente": "residente → **ambiente 2023** · el tratamiento",
    }
    _filas = "\n".join(
        f"| {_et[c]} | {_r.loc[c, 'spearman']:.3f} | {_r.loc[c, 'kendall']:.3f} | "
        f"{_r.loc[c, 'top50']:.2f} | {_r.loc[c, 'top200']:.2f} |"
        for c in ("correccion_sesgo", "residente_meta", "ambiente_2020", "ambiente")
        if c in _r.index
    )
    _n = int(_r["n"].iloc[0])
    _aviso = (
        "\n\n> **Este numerador es circular.** La superficie de E1 reparte el latente de cada "
        "distrito en proporción a WorldPop, así que el riesgo por residente es *constante* "
        "dentro de cada distrito. Cualquier otro denominador lo reordena por construcción."
        if numerador.value == "latente"
        else ""
    )
    # Sin sangría a propósito: la tabla se arma línea a línea y un dedent parcial la
    # convertiría en bloque de código.
    mo.md(
        f"### ¿Cuánto se mueve el ranking? — {_n} celdas evaluables · piso {piso.value}\n\n"
        "| contraste | ρ Spearman | τ-b Kendall | top-50 | top-200 |\n"
        "|---|---|---|---|---|\n"
        f"{_filas}\n\n"
        "Referencia canónica de E1 (conteos, sus propias celdas): ρ "
        f"**{canon.display('rango_espacial.spearman')}**, top-50 "
        f"**{canon.display('rango_espacial.top_overlap')}**. Cifras de E7: exploratorias, "
        f"del loader, no del registro.{_aviso}"
    )
    _ = denominador
    return


@app.cell
def _(PolyCollection, celdas, denominador, mpl, np, numerador, oscuro, piso, plt, poligonos):
    INK = "#E8EDEC" if oscuro.value else "#1F2A33"
    MUTED = "#9AA7AE" if oscuro.value else "#55636E"
    HILO = "#7E8C95" if oscuro.value else "#AEB9BF"
    mpl.rcParams["hatch.linewidth"] = 0.3
    # `carrera_teal`, como E1: un tono, luminosidad monótona, sin verde para «bajo».
    CMAP = mpl.colors.LinearSegmentedColormap.from_list(
        "carrera_teal", ["#EDF3F2", "#A8CBC7", "#59A099", "#1F6F6B", "#0C3835"]
    )
    # Divergente sin verde ni rojo: tierra (baja) ↔ teal (sube), centro casi blanco.
    DIV = mpl.colors.LinearSegmentedColormap.from_list(
        "tierra_teal", ["#7A3E22", "#D3A487", "#F1EEEA", "#8FC0BA", "#0C3835"]
    )

    _ev = celdas[f"evaluable_{piso.value}"].to_numpy()
    _num, _den = numerador.value, denominador.value
    # Percentil dentro de las celdas evaluables: la escala es la misma para los dos
    # paneles por construcción, que es lo que manda la decisión de E1.
    _pr = celdas[f"r_{_num}__residente"].where(_ev).rank(pct=True).to_numpy()
    _pt = celdas[f"r_{_num}__{_den}"].where(_ev).rank(pct=True).to_numpy()

    def _panel(ax, valores, cmap, norm, titulo):
        ax.patch.set_alpha(0)
        ax.add_collection(
            PolyCollection(poligonos[_ev], facecolors=cmap(norm(valores[_ev])), linewidths=0.0)
        )
        ax.add_collection(
            PolyCollection(
                poligonos[~_ev],
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
        ax.set_title(titulo, fontsize=11.5, color=INK, pad=8)
        ax.axis("off")

    fig_mapa, _ax = plt.subplots(1, 3, figsize=(13.5, 6.2))
    fig_mapa.patch.set_alpha(0)
    _n01 = mpl.colors.Normalize(0, 1)
    _panel(_ax[0], _pr, CMAP, _n01, "Riesgo por residente (WorldPop)")
    _panel(_ax[1], _pt, CMAP, _n01, f"Riesgo por {_den.replace('_', ' ')}")
    _nd = mpl.colors.TwoSlopeNorm(vcenter=0, vmin=-1, vmax=1)
    _panel(_ax[2], _pt - _pr, DIV, _nd, "Cambio de percentil")
    for _i, (_cm, _nm, _lab) in enumerate(
        (
            (CMAP, _n01, "percentil de riesgo · escala compartida"),
            (DIV, _nd, "baja  ←  cambio de percentil  →  sube"),
        )
    ):
        _cax = fig_mapa.add_axes([0.10 + 0.52 * _i, 0.10, 0.30 if _i == 0 else 0.22, 0.022])
        _cb = fig_mapa.colorbar(
            mpl.cm.ScalarMappable(norm=_nm, cmap=_cm), cax=_cax, orientation="horizontal"
        )
        _cb.set_label(_lab, fontsize=9, color=MUTED, labelpad=6)
        _cb.ax.tick_params(labelsize=8, colors=MUTED, length=2)
        _cb.outline.set_visible(False)
    fig_mapa.subplots_adjust(left=0.01, right=0.99, top=0.93, bottom=0.18, wspace=0.02)
    fig_mapa
    return INK, MUTED


@app.cell
def _(INK, MUTED, celdas, denominador, numerador, piso, plt):
    # La nube de rangos. En E1 se pega a la diagonal; acá es donde hay que mirar si se abre.
    _ev = celdas[celdas[f"evaluable_{piso.value}"]]
    _a = _ev[f"r_{numerador.value}__residente"].rank()
    _b = _ev[f"r_{numerador.value}__{denominador.value}"].rank()
    fig_rango, _ax = plt.subplots(figsize=(4.8, 4.8))
    fig_rango.patch.set_alpha(0)
    _ax.patch.set_alpha(0)
    _ax.plot([0, len(_ev)], [0, len(_ev)], lw=0.8, color=MUTED, ls="--")
    _ax.scatter(_a, _b, s=4, color="#1F6F6B", alpha=0.35, linewidths=0)
    _ax.set_xlabel("rango por residente", fontsize=9.5, color=MUTED)
    _ax.set_ylabel(f"rango por {denominador.value.replace('_', ' ')}", fontsize=9.5, color=MUTED)
    _ax.set_title(f"{len(_ev)} celdas evaluables", fontsize=11, color=INK)
    for _s in _ax.spines.values():
        _s.set_visible(False)
    _ax.tick_params(labelsize=8, colors=MUTED, length=2)
    _ax.set_aspect(1)
    fig_rango
    return


@app.cell
def _(art, mo, numerador):
    _n = numerador.value
    _f = lambda d: d[d["numerador"] == _n].drop(columns="numerador").round(3)  # noqa: E731
    mo.vstack(
        [
            mo.md(
                "## Robustez\n\n**El control con IC bootstrap** (1000 remuestreos de celdas). "
                "La conclusión se cae si la diferencia `residente_meta − ambiente` incluye cero."
            ),
            mo.ui.table(_f(art["bootstrap"]), selection=None),
            mo.md(
                "**¿Es desalineación entre el píxel de ~1 km y el hexágono?** Si lo fuera, el "
                "desacuerdo se evaporaría al agregar a H3 res-7 o a distrito."
            ),
            mo.ui.table(_f(art["agregado"]), selection=None),
            mo.md(
                "**¿Depende de qué celdas deja fuera el piso?** Alternativa sin piso: "
                "`latente / (pob + m)`."
            ),
            mo.ui.table(_f(art["suavizado"]), selection=None),
            mo.md(
                "**Dentro de cada distrito** (ρ media ponderada por celdas, distritos con ≥ 10)."
            ),
            mo.ui.table(art["intra_distrito"].round(3), selection=None),
            mo.md("**Matriz completa de pares** en el piso 500."),
            mo.ui.table(_f(art["pares"]), selection=None),
        ]
    )
    return


@app.cell
def _(art, mo):
    mo.vstack(
        [
            mo.md(
                """
            ## Circularidad del numerador

            `var_intra_distrito = 0` significa que el riesgo por residente es constante en
            cada distrito: el numerador fue repartido con WorldPop. Es el caso de toda la
            superficie de E1 (`latente`, `observado` y sus categorías). Por eso el análisis
            principal usa la superficie híbrida y las denuncias geocodificadas.
            """
            ),
            mo.ui.table(art["circularidad"].round(3), selection=None),
            mo.md(
                """
            ## Kill-criterion de resolución

            ¿LandScan a ~1 km conserva contraste dentro del distrito? Se cierra como negativo
            de resolución si la varianza intra-distrital de log(1+pob) es < 0,10 o si tiene
            menos valores distintos que WorldPop.
            """
            ),
            mo.ui.table(art["resolucion"].round(3), selection=None),
        ]
    )
    return


@app.cell
def _(art, mo, numerador):
    _n = numerador.value
    _d = art["por_distrito"]
    mo.vstack(
        [
            mo.md(
                """
            ## Dónde diverge — la sub-predicción de infelix

            «Celdas comerciales/nightlife bajan, periferias residenciales suben.» Se mide como
            ρ entre el cambio de percentil y los POI comerciales de OSM (retail + comida +
            nightlife). Ojo: el sentido del cambio lo fija por completo el cociente
            LandScan/WorldPop, y LandScan usa uso de suelo como insumo; esta prueba dice
            dónde difieren los rasters, no algo sobre el delito.
            """
            ),
            mo.ui.table(art["direccional"].round(3), selection=None),
            mo.ui.table(
                _d[_d["numerador"] == _n].drop(columns="numerador").round(3), selection=None
            ),
            mo.md(
                "**Mesa Redonda** (celda del damero comercial de Cercado): percentil de riesgo "
                "por cada denominador, piso 500."
            ),
            mo.ui.table(art["mesa_redonda"].round(3), selection=None),
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Qué no dice esta vista

        - **LandScan no es el denominador de expuestos.** Es un modelo de población
          ambiente de 24 h a ~1 km. El denominador correcto —persona-horas por franja
          horaria— no existe en los datos locales; la parte horaria está en `inwatch-04w`.
        - **Riesgo por expuesto no es mejor para todo delito.** Para violencia familiar el
          denominador residencial es el correcto: ocurre donde la gente vive.
        - **Las cifras de E7 no son canónicas.** Salen del loader; cuando se emitan,
          entran al registro con procedencia y este aviso se quita.
        - **Nada acá es un ruteo.** El hexágono res-8 no respeta manzanas; ver
          `design/contrato-unidades.md`.
        """
    )
    return


if __name__ == "__main__":
    app.run()
