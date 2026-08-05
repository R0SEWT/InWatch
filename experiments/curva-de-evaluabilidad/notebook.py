"""Notebook marimo de `curva-de-evaluabilidad`: el slider que apaga la capacidad de medir.

Solo lee artefactos y presenta. No calcula desde datos crudos — eso vive en ``loader.py``,
por la restricción de Pyodide (ver el docstring de ese archivo). En particular **no
reimplementa la regla del piso**: la tabla de pisos viene precomputada, y el notebook la
busca. Si la recalculara podría discrepar del número que el registro declara canónico.

    uv run python experiments/curva-de-evaluabilidad/loader.py
    uv run marimo edit experiments/curva-de-evaluabilidad/notebook.py
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

    from inwatch import canon

    return Path, canon, mo, mpl, np, pd, plt


@app.cell
def _(canon, mo):
    mo.md(
        f"""
        # La curva de evaluabilidad

        Baja la tasa de geocodificación de {canon.display("evaluabilidad.tasa_lima")} % —la
        real de Lima— hacia abajo, y mira cuál de las dos curvas se mueve.

        **La habilidad del modelo casi no se mueve.** Lo que colapsa es la capacidad de
        medirla. Son dos cosas distintas que la práctica normal reporta como una sola:

        - **lo que creerías saber** — el ρ contra el oráculo *degradado*: el número que un
          analista de esa ciudad calcularía y publicaría.
        - **lo que realmente sabes** — el ρ contra el oráculo *completo*: lo que el modelo
          de verdad aprendió. Nadie en esa ciudad puede calcularlo, porque exigiría
          exactamente el dato que falta.

        La distancia entre las dos es el error de medición, y crece a medida que el
        registro empeora. A la tasa real de Trujillo
        ({canon.display("evaluabilidad.tasa_trujillo")} %) ya vale
        {canon.display("evaluabilidad.brecha_trujillo")} de ρ.

        **Sin datos ≠ seguro**, y acá la regla toma su forma más incómoda: por debajo del
        piso de evaluabilidad la zona se dibuja deshilachada, no vacía. No significa que el
        mapa sea malo — significa que **no se puede saber si lo es**, y eso no autoriza a
        mostrarlo sin marcarlo.
        """
    )
    return


@app.cell
def _(Path, pd):
    SLUG = "curva-de-evaluabilidad"
    _dir = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG

    def _leer(nombre):
        p = _dir / f"{nombre}.parquet"
        if not p.exists():
            raise FileNotFoundError(
                f"falta el artefacto: {p}\n"
                f"  corre: uv run python experiments/{SLUG}/loader.py"
            )
        return pd.read_parquet(p)

    curvas = _leer("curvas")
    penalidad = _leer("penalidad")
    pisos = _leer("pisos")
    return curvas, penalidad, pisos


@app.cell
def _():
    # Subconjunto de Okabe-Ito, heredado de `infelix/scripts/figures_simbig.py`, donde ya
    # está validado para esta misma figura. Re-verificado acá contra las seis pruebas de
    # paleta en claro y en oscuro: el peor par adyacente queda en ΔE 11.0 bajo deuteranopia
    # y 25.8 en visión normal, con todos los checks en PASS.
    #
    # El color NO es la única señal de identidad: cada serie lleva además su propio estilo
    # de línea, su propio marcador y una etiqueta directa al final del trazo. Es una
    # paleta categórica —tres series con nombre—, no una rampa de riesgo, así que la regla
    # de «nada de verde para bajo riesgo» no aplica: acá el verde nombra a la persistencia,
    # no a una zona del mapa.
    C_REAL = "#0072B2"
    C_MEDIBLE = "#D55E00"
    C_PERSIST = "#009E73"

    # (columna, sd, etiqueta, color, estilo, marcador, desplazamiento vertical del rótulo)
    # Las dos primeras convergen en la base por construcción, así que sus rótulos directos
    # necesitan offsets opuestos o se pisan.
    SERIES = (
        ("real", "real_sd", "lo que realmente sabes", C_REAL, "-", "o", 12),
        ("medible", "medible_sd", "lo que creerías saber", C_MEDIBLE, "--", "s", -13),
        ("persistencia", "persistencia_sd", "persistencia", C_PERSIST, ":", "^", 0),
    )
    return C_MEDIBLE, C_PERSIST, C_REAL, SERIES


@app.cell
def _(canon, mo):
    tasa = mo.ui.slider(
        10.0, 83.4, value=83.4, step=0.1, show_value=True, full_width=True,
        label="tasa de geocodificación (%)",
    )
    mecanismo = mo.ui.radio(
        options={
            "aleatoria — cota optimista (la figura del paper)": "uniforme",
            "selectiva — cota empírica": "selectivo",
        },
        value="aleatoria — cota optimista (la figura del paper)",
        inline=True,
        label="cómo se pierde la geocodificación",
    )
    tolerancia = mo.ui.slider(
        0.0, 0.13, value=0.05, step=0.005, show_value=True,
        label="error de medición tolerado (ρ) antes de declarar «no evaluable»",
    )
    oscuro = mo.ui.checkbox(value=False, label="fondo oscuro")
    mo.vstack(
        [
            tasa,
            mecanismo,
            mo.hstack([tolerancia, oscuro], justify="start", gap=2),
            mo.md(
                "Los marcadores en el eje son ciudades reales: Lima en "
                f"{canon.display('evaluabilidad.tasa_lima')} % y Trujillo en "
                f"{canon.display('evaluabilidad.tasa_trujillo')} %."
            ),
        ]
    )
    return mecanismo, oscuro, tasa, tolerancia


@app.cell
def _(canon, mo):
    # Los números portantes salen del registro, ya redondeados por la policy. Ninguno se
    # escribe a mano acá: ese fue el fallo que originó el mecanismo. Las cifras de Trujillo
    # son las de la cota SELECTIVA, que es la que la policy declara canónica.
    _tru = canon.display("evaluabilidad.tasa_trujillo")
    _med = canon.display("evaluabilidad.rho_medible_trujillo")
    _rea = canon.display("evaluabilidad.rho_real_trujillo")
    _bre = canon.display("evaluabilidad.brecha_trujillo")
    _piso = canon.display("evaluabilidad.piso_geocod_tau05")
    _sem = canon.display("evaluabilidad.conteo_semillas")
    _cor = canon.display("evaluabilidad.conteo_corridas")
    mo.md(
        f"""
        | A la tasa real de Trujillo ({_tru} %) | |
        |---|---|
        | Lo que creerías saber (ρ medible) | **{_med}** |
        | Lo que realmente sabes (ρ real) | **{_rea}** |
        | Brecha: cuánto te equivocarías al reportar | **{_bre}** |
        | Piso de geocodificación con τ = 0.05 | **{_piso} %** |
        | Semillas por nivel · corridas totales | {_sem} · {_cor} |
        """
    )
    return


@app.cell
def _(np):
    def curva_de(curvas, nombre):
        """Una curva del artefacto, ordenada por tasa creciente (lo que exige `np.interp`)."""
        return curvas[curvas["curva"] == nombre].sort_values("rate")

    def leer_en(curva, tasa, col):
        """Valor de una columna a una tasa cualquiera, interpolando entre niveles medidos.

        Interpolación de presentación, no de estimación: los cinco niveles son lo que se
        midió y el trazo entre ellos es una conjetura de continuidad. Por eso la figura
        dibuja los niveles medidos como marcadores — para que se vea dónde hay medición y
        dónde hay recta.
        """
        return float(np.interp(tasa, curva["rate"], curva[col]))

    def es_nivel_medido(curva, tasa, tol=5e-4):
        return bool(np.min(np.abs(curva["rate"].to_numpy() - tasa)) < tol)

    def piso_en(pisos, nombre, tau):
        """Busca el piso precomputado. NO lo recalcula — ver el docstring del módulo."""
        p = pisos[pisos["curva"] == nombre].sort_values("tau")
        return float(np.interp(tau, p["tau"], p["piso"]))

    return curva_de, es_nivel_medido, leer_en, piso_en


@app.cell
def _(
    C_MEDIBLE,
    C_REAL,
    SERIES,
    curva_de,
    curvas,
    leer_en,
    mecanismo,
    mpl,
    np,
    oscuro,
    piso_en,
    pisos,
    plt,
    tasa,
    tolerancia,
):
    INK = "#E8EDEC" if oscuro.value else "#1F2A33"
    MUTED = "#9AA7AE" if oscuro.value else "#55636E"
    HILO = "#7E8C95" if oscuro.value else "#AEB9BF"  # el hilo del deshilachado

    # Trama más gruesa que en `observado-latente` (0.3) y a propósito: allá el deshilachado
    # cubre novecientos hexágonos chicos y con el ancho por defecto formaba una malla que se
    # comía el mapa; acá es UNA región grande, y a 0.3 la ausencia se volvía invisible. Es
    # el mismo criterio —que la ausencia se lea como ausencia, ni más ni menos— resuelto al
    # revés porque la geometría es otra.
    mpl.rcParams["hatch.linewidth"] = 0.5

    _c = curva_de(curvas, mecanismo.value)
    _x = _c["rate"].to_numpy() * 100.0
    _t = tasa.value
    _piso = piso_en(pisos, mecanismo.value, tolerancia.value) * 100.0

    fig_curva, _ax = plt.subplots(figsize=(8.6, 4.9))
    fig_curva.patch.set_alpha(0)
    _ax.patch.set_alpha(0)
    _XLO, _XHI = 6.0, 104.0

    # La zona no evaluable se dibuja deshilachada, nunca vacía: es la misma regla que en el
    # mapa, aplicada a un eje. No dice «acá el modelo falla», dice «acá no se puede saber».
    if _piso > _XLO:
        _ax.axvspan(
            _XLO, _piso, facecolor="none", edgecolor=HILO, hatch="/", linewidth=0.0,
            alpha=0.7, zorder=0,
        )
        # El rótulo de la zona va ARRIBA a la izquierda y no abajo: la franja inferior es la
        # única banda del gráfico que ninguna curva visita, y queda reservada para el
        # lectorado del cursor, que se mueve por todo el ancho y no tiene dónde más ir.
        # Solo se dibuja si la franja lo puede contener: con la tolerancia al máximo el piso
        # cae al 10 % y el rótulo sobresaldría de su propia zona, señalando lo que no es.
        if _piso - _XLO > 15.0:
            _ax.annotate(
                f"no evaluable con τ = {tolerancia.value:.3f}\n(por debajo de {_piso:.1f} %)",
                xy=(_XLO + 1.5, 0.97), xycoords=("data", "axes fraction"),
                ha="left", va="top", fontsize=7.5, color=MUTED,
            )

    for _col, _sd, _lab, _color, _ls, _mk, _dy in SERIES:
        _y = _c[_col].to_numpy()
        _e = np.nan_to_num(_c[f"{_col}_sd"].to_numpy(), nan=0.0)
        _ax.fill_between(_x, _y - _e, _y + _e, color=_color, alpha=0.15, linewidth=0)
        _ax.plot(_x, _y, _ls, color=_color, marker=_mk, markersize=4.5, linewidth=1.8,
                 label=_lab, zorder=3)
        _ax.annotate(_lab, (_x[-1], _y[-1]), xytext=(8, _dy), textcoords="offset points",
                     fontsize=8, color=_color, va="center")

    # Ciudades: rótulo por FUERA del área de datos, para que no pueda chocar nunca con la
    # leyenda ni con los rótulos directos de las series.
    for _r, _n in ((83.4, "Lima"), (24.9, "Trujillo")):
        _ax.axvline(_r, color=HILO, linewidth=0.8, zorder=1)
        _ax.annotate(_n, (_r, 1.0), xycoords=("data", "axes fraction"), xytext=(0, 4),
                     textcoords="offset points", ha="center", fontsize=7.5, color=MUTED)

    # El cursor y la brecha: el objeto del experimento, dibujado como distancia.
    _med = leer_en(_c, _t / 100.0, "medible")
    _rea = leer_en(_c, _t / 100.0, "real")
    _ax.axvline(_t, color=INK, linewidth=1.1, alpha=0.65, zorder=2)
    # Con la brecha casi cerrada —el caso de Lima, donde vale cero por construcción— una
    # flecha de doble punta colapsa en un borrón. Los dos marcadores superpuestos dicen lo
    # mismo sin ensuciar.
    if _rea - _med >= 0.005:
        _ax.annotate("", xy=(_t, _rea), xytext=(_t, _med),
                     arrowprops={"arrowstyle": "<->", "color": INK, "linewidth": 1.1,
                                 "shrinkA": 0, "shrinkB": 0}, zorder=4)
    # El lectorado se ancla al PIE del cursor, no al medio de la cuña. Colgado de la cuña
    # aterrizaba encima de alguna curva en casi todo el recorrido —en la base porque las
    # tres convergen, a tasas bajas porque la cuña cruza la naranja— y perseguir el hueco
    # con offsets condicionales es una carrera que se pierde. La franja inferior está
    # siempre libre y la vertical del cursor mantiene la conexión visual.
    _lado = -1 if _t > 46.0 else 1
    _ax.annotate(
        f"brecha {_rea - _med:.3f}", xy=(_t, 0.015), xycoords=("data", "axes fraction"),
        xytext=(5 * _lado, 0), textcoords="offset points",
        ha="right" if _lado < 0 else "left", va="bottom", fontsize=8.5, color=INK,
    )
    for _y, _color in ((_rea, C_REAL), (_med, C_MEDIBLE)):
        _ax.plot([_t], [_y], "o", markersize=7, color=_color, markeredgewidth=1.4,
                 markeredgecolor="#1a1a19" if oscuro.value else "#fcfcfb", zorder=5)

    _ax.set_xlim(_XLO, _XHI)
    _ax.set_ylim(0.17, 0.50)
    # El eje se estira hasta 104 solo para alojar las etiquetas directas. Los ticks paran
    # en 80 para no sugerir que hay medición donde no la hay.
    _ax.set_xticks([20, 40, 60, 80])
    _ax.set_xlabel("tasa de geocodificación (%)", fontsize=9.5, color=MUTED)
    _ax.set_ylabel("ρ de Spearman intra-distrital (macro)", fontsize=9.5, color=MUTED)
    _ax.grid(axis="y", color=HILO, alpha=0.35, linewidth=0.5)
    _ax.set_axisbelow(True)
    for _s in _ax.spines.values():
        _s.set_visible(False)
    _ax.tick_params(labelsize=8.5, colors=MUTED, length=2)
    # Leyenda FUERA del área de datos, en una fila. Dentro solo cabía abajo a la derecha, y
    # esa franja está reservada para el lectorado del cursor. Se mantiene aunque las tres
    # series ya lleven etiqueta directa: con la etiqueta directa a la altura del último
    # punto, en la base las tres se amontonan, y la leyenda es lo que garantiza que la
    # identidad de cada serie nunca dependa solo del color.
    _ax.legend(frameon=False, fontsize=8.5, labelcolor=MUTED, loc="upper center",
               bbox_to_anchor=(0.5, -0.16), ncol=3)
    _ax.set_title(
        "Los niveles medidos son los marcadores; el trazo entre ellos es interpolación",
        fontsize=9, color=MUTED, pad=18, loc="left",
    )
    fig_curva.subplots_adjust(left=0.07, right=0.86, top=0.88, bottom=0.22)
    fig_curva
    return HILO, INK, MUTED


@app.cell
def _(
    canon,
    curva_de,
    curvas,
    es_nivel_medido,
    leer_en,
    mecanismo,
    mo,
    piso_en,
    pisos,
    tasa,
    tolerancia,
):
    _c = curva_de(curvas, mecanismo.value)
    _t = tasa.value / 100.0
    _med = leer_en(_c, _t, "medible")
    _rea = leer_en(_c, _t, "real")
    _per = leer_en(_c, _t, "persistencia")
    _piso = piso_en(pisos, mecanismo.value, tolerancia.value) * 100.0

    _origen = (
        "nivel **medido**" if es_nivel_medido(_c, _t)
        else "**interpolado** entre dos niveles medidos"
    )
    _veredicto = (
        f"### 🚫 No evaluable\n\nCon la tolerancia en {tolerancia.value:.3f} de ρ, el piso "
        f"de esta curva está en **{_piso:.1f} %** de geocodificación. A {tasa.value:.1f} % "
        "un mapa se puede dibujar, pero **no se puede afirmar que sea bueno ni que sea "
        "malo**: la evaluación que lo respaldaría se equivoca más de lo tolerado. Lo "
        "correcto no es una nota al pie, es no publicar el número de desempeño."
        if tasa.value < _piso else
        f"### ✅ Evaluable\n\nA {tasa.value:.1f} % la evaluación se equivoca en "
        f"{_rea - _med:.3f} de ρ, por debajo de la tolerancia de {tolerancia.value:.3f}. El "
        f"piso de esta curva está en **{_piso:.1f} %**."
    )

    mo.md(
        f"""
        {_veredicto}

        A **{tasa.value:.1f} %** de geocodificación ({_origen}, mecanismo
        **{mecanismo.value}**):

        | | |
        |---|---|
        | Lo que creerías saber | {_med:.3f} |
        | Lo que realmente sabes | {_rea:.3f} |
        | Persistencia (la práctica estándar) | {_per:.3f} |
        | Brecha de medición | **{_rea - _med:.3f}** |

        El analista de esa ciudad ve **{_med:.3f}** y concluye que su modelo rinde eso.
        Rinde {_rea:.3f}. No tiene forma de enterarse: para calcular la segunda cifra
        haría falta el oráculo completo, que es justamente el dato que su ciudad no tiene.
        Lo que la mala geocodificación rompe no es el modelo — es el termómetro.

        El modelo con features supera a la persistencia en el
        {canon.display("evaluabilidad.pct_seeds_feat_gana")} % de las semillas, en todos
        los niveles y con los dos mecanismos. Incluso al 10 % de geocodificación la señal
        sigue ahí; lo que no sigue ahí es la prueba de que sigue ahí.
        """
    )
    return


@app.cell
def _(C_MEDIBLE, INK, MUTED, curva_de, curvas, mecanismo, np, plt):
    # Lo contraintuitivo del experimento: bajo pérdida aleatoria la ventaja sobre la
    # persistencia se ENSANCHA cuando el registro empeora. La persistencia sufre dos veces
    # —historial degradado Y referencia de evaluación degradada—, así que justo donde el
    # dato es peor, la práctica estándar (hotspots por persistencia) es la que más pierde
    # frente al modelo estructural. Es lo contrario de «si el dato es malo, usa algo simple».
    #
    # Pero bajo pérdida SELECTIVA la monotonía se rompe, y el título no puede afirmarla como
    # si valiera siempre: el control deja elegir la curva, así que una leyenda fija mentiría
    # en la mitad de los estados. El título se queda neutro y la lectura se calcula.
    _c = curva_de(curvas, mecanismo.value)
    _x = np.arange(len(_c))
    _v = _c["ventaja"].to_numpy()
    _e = np.nan_to_num(_c["ventaja_sd"].to_numpy(), nan=0.0)

    fig_ventaja, _ax = plt.subplots(figsize=(6.6, 2.9))
    fig_ventaja.patch.set_alpha(0)
    _ax.patch.set_alpha(0)
    # Barra angosta y superficie visible entre contiguas: el ancho de la barra no codifica
    # nada, así que engordarla solo agrega tinta.
    _ax.bar(_x, _v, width=0.52, color=C_MEDIBLE, yerr=_e, capsize=3,
            error_kw={"elinewidth": 1.0, "ecolor": MUTED})
    for _i, (_vi, _ei) in enumerate(zip(_v, _e, strict=True)):
        _ax.annotate(f"{_vi:.3f}", (_i, _vi + _ei), xytext=(0, 4),
                     textcoords="offset points", ha="center", fontsize=8, color=MUTED)
    # La lectura sale de los datos de la curva ELEGIDA, no de una frase fija. Y el nivel base
    # no lleva barra de error: es determinista, no es que se haya medido dispersión y diera
    # cero.
    _crece = bool(np.all(np.diff(_c.sort_values("rate", ascending=False)["ventaja"]) >= 0))
    _ax.annotate(
        (
            "crece sin excepción al empeorar el registro: la persistencia sufre dos veces"
            if _crece else
            "NO crece sin excepción: el orden se rompe y los intervalos se solapan"
        )
        + "\nel nivel base no lleva barra: sin adelgazamiento no hay nada que aleatorizar",
        xy=(1.0, -0.30), xycoords="axes fraction", ha="right", va="top",
        fontsize=7.5, color=MUTED,
    )

    _ax.set_xticks(_x, [f"{r:.0%}" for r in _c["rate"]], fontsize=8.5, color=INK)
    _ax.set_xlabel("tasa de geocodificación", fontsize=9.5, color=MUTED)
    _ax.set_ylabel("ρ medible − ρ persistencia", fontsize=9.5, color=MUTED)
    _ax.set_ylim(0, (_v + _e).max() * 1.28)
    for _s in _ax.spines.values():
        _s.set_visible(False)
    _ax.tick_params(labelsize=8.5, colors=MUTED, length=0)
    _ax.set_title(
        "Lo que el analista ve ganar sobre la persistencia, nivel por nivel",
        fontsize=11, color=INK, pad=8, loc="left",
    )
    fig_ventaja.subplots_adjust(bottom=0.34)
    fig_ventaja
    return


@app.cell
def _(C_MEDIBLE, C_PERSIST, C_REAL, HILO, INK, MUTED, penalidad, plt):
    # Cuánto costó suponer que la pérdida era aleatoria. Comparación pareada por semilla
    # sobre la MISMA grilla y el MISMO script de origen: es la única forma de que la
    # diferencia sea del mecanismo y no de la corrida.
    _x = penalidad["rate"].to_numpy() * 100.0

    fig_penalidad, _ax = plt.subplots(figsize=(6.6, 3.0))
    fig_penalidad.patch.set_alpha(0)
    _ax.patch.set_alpha(0)
    _ax.axhline(0.0, color=HILO, linewidth=1.0, zorder=1)
    for _col, _lab, _color, _ls, _mk in (
        ("d_real", "sobre lo que realmente sabes", C_REAL, "-", "o"),
        ("d_medible", "sobre lo que creerías saber", C_MEDIBLE, "--", "s"),
        ("d_persistencia", "sobre la persistencia", C_PERSIST, ":", "^"),
    ):
        _ax.plot(_x, penalidad[_col], _ls, color=_color, marker=_mk, markersize=4.5,
                 linewidth=1.8, label=_lab, zorder=3)

    _ax.set_xlabel("tasa de geocodificación (%)", fontsize=9.5, color=MUTED)
    _ax.set_ylabel("Δρ selectivo − aleatorio", fontsize=9.5, color=MUTED)
    _ax.grid(axis="y", color=HILO, alpha=0.35, linewidth=0.5)
    _ax.set_axisbelow(True)
    _ax.margins(y=0.14)
    for _s in _ax.spines.values():
        _s.set_visible(False)
    _ax.tick_params(labelsize=8.5, colors=MUTED, length=2)
    # Leyenda FUERA del área de datos: las tres series se cruzan por todo el ancho y no hay
    # una sola esquina libre donde ponerla sin taparlas.
    _ax.legend(frameon=False, fontsize=8, labelcolor=MUTED, loc="upper center",
               bbox_to_anchor=(0.5, -0.30), ncol=3)
    _ax.set_title(
        "La pérdida selectiva ensucia la MEDICIÓN, no tanto la señal",
        fontsize=11, color=INK, pad=8, loc="left",
    )
    fig_penalidad.subplots_adjust(bottom=0.34)
    fig_penalidad
    return


@app.cell
def _(canon, mo):
    mo.md(
        f"""
        ## Qué no dice esta vista

        - **La curva aleatoria es una cota optimista, y el propio repo de origen lo
          declara.** Suponer que cada hecho pierde su coordenada con la misma probabilidad
          es lo más benigno que puede pasar. La pérdida real no es así: se concentra por
          comisaría, por categoría y con gradiente de pobreza. Por eso el segundo mecanismo
          está en el control y no escondido en una nota — a la tasa de Trujillo la pérdida
          selectiva cuesta {canon.display("evaluabilidad.penalidad_medible_trujillo")} de ρ
          medible extra contra solo
          {canon.display("evaluabilidad.penalidad_real_trujillo")} de ρ real.
        - **Ni siquiera la curva selectiva es el peor caso.** Modela la selectividad sobre
          observables (propensión distrito × categoría). La selectividad *intra*-distrital
          —qué calle, qué tipo de predio— no está capturada, así que sigue siendo una cota
          inferior del daño; mucho menos optimista, pero cota inferior.
        - **El mecanismo se midió en Lima, no en Trujillo.** Extrapolar el patrón de
          selectividad al nivel de {canon.display("evaluabilidad.tasa_trujillo")} % supone
          que el modo de fallo es comparable — plausible, misma institución y mismo
          sistema, pero no verificado con datos de Trujillo. Lo que está medido en Trujillo
          es su tasa; lo que está simulado es lo que le pasa a la evaluación a esa tasa.
        - **La persistencia es la serie más inestable de las tres, y se nota.** Su Δ entre
          mecanismos salta y hasta cambia de signo al 10 %. Tiene sentido —sufre dos veces,
          en el historial de entrenamiento y en la referencia de evaluación— pero significa
          que la tercera línea del último gráfico se lee como tendencia gruesa, no punto a
          punto.
        - **La tolerancia τ es una elección, no un hallazgo.** No hay ningún número en los
          datos que diga cuánto error de medición es aceptable. El control existe para que
          esa decisión sea visible y de quien la toma, en vez de quedar enterrada en un
          umbral por defecto.
        - **«No evaluable» no significa «el modelo es malo».** Significa que la afirmación
          «el modelo es bueno» no tiene con qué sostenerse. Es la misma regla que la celda
          deshilachada del mapa, un piso más arriba: ausencia de evaluación es ausencia de
          evidencia, no evidencia de fracaso.
        - **Esto no es una curva de riesgo.** El eje y es ρ de Spearman intra-distrital
          macro sobre celdas H3 res-8: mide si el modelo ordena bien las celdas *dentro* de
          cada distrito. No dice nada sobre el nivel de delito ni sobre dónde patrullar.
        """
    )
    return


if __name__ == "__main__":
    app.run()
