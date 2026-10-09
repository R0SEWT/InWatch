"""Notebook marimo de `reloj-de-riesgo` (E8).

Solo lee artefactos y presenta. No calcula desde datos crudos — eso vive en
``loader.py``, por la restricción de Pyodide (ver el docstring de ese archivo). Los
mapas usan ``H3HexagonLayer`` de pydeck, que dibuja la celda desde su índice en el
navegador: ``h3`` no tiene que correr acá.

    uv run marimo edit experiments/reloj-de-riesgo/notebook.py
"""

import marimo

__generated_with = "0.23.16"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    import re
    from pathlib import Path

    import marimo as mo
    import matplotlib as mpl
    import numpy as np
    import pandas as pd
    import pydeck as pdk

    return Path, json, mo, mpl, np, pd, pdk, re


@app.cell
def _(Path, json, pd):
    SLUG = "reloj-de-riesgo"
    _dir = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG
    if not (_dir / "trampas.json").exists():
        raise FileNotFoundError(
            f"falta el artefacto: {_dir / 'trampas.json'}\n"
            f"  corre: uv run python experiments/{SLUG}/loader.py"
        )
    trampas = json.loads((_dir / "trampas.json").read_text())
    hist = pd.read_parquet(_dir / "heaping_hora_minuto.parquet")
    mods = pd.read_parquet(_dir / "aoristica_modalidades.parquet")
    sobrevive = trampas["veredicto"] == "sobrevive"
    mapa = pd.read_parquet(_dir / "mapa_turno.parquet") if sobrevive else None
    clusters = pd.read_parquet(_dir / "clusters.parquet") if sobrevive else None
    perfil = pd.read_parquet(_dir / "clusters_perfil.parquet") if sobrevive else None
    est = pd.read_parquet(_dir / "estabilidad.parquet") if sobrevive else None
    sens = pd.read_parquet(_dir / "sensibilidad.parquet") if sobrevive else None
    eje = pd.read_parquet(_dir / "eje.parquet") if sobrevive else None
    return clusters, eje, est, hist, mapa, mods, perfil, sens, sobrevive, trampas


@app.cell
def _(mo):
    mo.md(
        """
        # El reloj de riesgo

        ¿Tiene cada celda de Lima un reloj propio — una forma de repartir su crimen
        entre la madrugada, la mañana, la tarde y la noche que la distinga del resto de
        la ciudad? Y si lo tiene, ¿esos relojes se agrupan en unos pocos tipos?

        Antes de agrupar nada, tres trampas: la hora redondeada (*heaping*), la hora
        que es de descubrimiento y no del hecho (*incertidumbre aorística*) y la
        escasez (*sparsity*). Abajo, primero la auditoría; los mapas solo aparecen si
        las tres sobreviven.

        **Este es el reloj de la denuncia, no del crimen.** ENAPRES no registra la hora
        del hecho, así que la corrección de sesgo de denuncia no puede condicionarse a
        la hora: si lo que ocurre de madrugada se denuncia menos, este reloj lo hereda
        sin poder verlo.

        **Sin datos ≠ seguro.** Las celdas bajo el piso de eventos se dibujan
        punteadas. Ausencia de denuncia es ausencia de evidencia, no evidencia de
        ausencia.
        """
    )
    return


@app.cell
def _(mo, trampas):
    _h, _a, _s = trampas["heaping"], trampas["aoristica"], trampas["sparsity"]
    _hr = _h["resorteo"]["turnos4"]
    _sp = _s["por_esquema"]["turnos4"]
    _c = trampas["criterios"]

    def _v(muere):
        return "**mata**" if muere else "sobrevive"

    _filas = [
        ("1 · Heaping",
         f"{_h['frac_minuto_00']:.0%} de las horas en :00 y {_h['frac_minuto_mult5']:.0%} "
         f"en múltiplo de 5 (sin redondeo serían "
         f"{_h['frac_minuto_uniforme_esperada_mult5']:.0%}); espiga 00:00 "
         f"×{_h['espiga_0000_sobre_0100_0500']:.1f}. Re-sorteando cada hora redondeada en "
         f"su ventana cambia de turno el {_hr['frac_cambia_turno']:.1%} de los eventos; "
         f"el ruido es {_hr['ratio']:.2f} de la señal entre celdas",
         f"> {_c['KILL_HEAPING_FRAC_CAMBIA']:.0%} cambia, o ruido/señal ≥ "
         f"{_c['KILL_HEAPING_RATIO_TVD']:.2f}", _v(_h["muere"])),
        ("2 · Aorística",
         f"modalidades con hora de descubrimiento: {_a['frac_eventos_aoristicos']:.1%} de "
         f"los eventos; madrugada {_a['frac_madrugada_aoristicas']:.0%} contra "
         f"{_a['frac_madrugada_resto']:.0%} del resto. SIDPOL no trae ventana (inicio, "
         "fin): el reparto de Ratcliffe no es aplicable, se excluyen",
         f"excluidas > {_c['KILL_AORISTICA_FRAC']:.0%}", _v(_a["muere"])),
        ("3 · Sparsity",
         f"celda × hora: mediana {_s['celda_hora_mediana']:.0f} eventos, "
         f"{_s['celda_hora_frac_cero']:.0%} en cero; celda × turno × mes: media "
         f"{_s['celda_turno_mes_media']:.1f}. Climatología: {_s['celdas_sobre_piso']} "
         f"celdas con n ≥ {_s['piso_n_min']} retienen "
         f"{_s['cobertura_eventos_sobre_piso']:.0%} de los eventos; sobredispersión "
         f"{_sp['sobredispersion']:.2f}; fiabilidad split-half "
         f"{_sp['fiabilidad_split_half_aleatorio']:.2f}",
         f"< {_c['KILL_SPARSITY_MIN_CELDAS']} celdas, cobertura < "
         f"{_c['KILL_SPARSITY_MIN_COBERTURA']:.0%}, fiabilidad < "
         f"{_c['KILL_SPARSITY_MIN_FIABILIDAD']:.2f} o sobredispersión < "
         f"{_c['KILL_SPARSITY_MIN_SOBREDISP']:.2f}", _v(_s["muere"])),
    ]
    _tabla = "\n        ".join(f"| {a} | {b} | {c} | {d} |" for a, b, c, d in _filas)
    mo.md(
        f"""
        ## Las tres trampas

        | Trampa | Lo medido | Criterio de muerte | Resultado |
        |---|---|---|---|
        {_tabla}

        **Veredicto de las trampas: {trampas["veredicto"]}.**

        Lo que la auditoría deja escrito aunque no mate: la firma es menos estable entre
        años (split pares/impares {_sp["fiabilidad_split_half_años_par_impar"]:.2f}) que
        entre mitades al azar, y el toque de queda de 2020–21 cambió el perfil de la
        ciudad (madrugada {_sp["perfil_ciudad_toque_de_queda"]["madrugada"]:.1%} contra
        {_sp["perfil_ciudad_sin_toque_de_queda"]["madrugada"]:.1%} fuera de esos años).
        Una climatología que apila esos años promedia dos regímenes.
        """
    )
    return


@app.cell
def _(hist, mo, mpl, np):
    import matplotlib.pyplot as plt

    _m = hist.pivot_table(index="minuto", columns="hora", values="n", fill_value=0)
    _m = _m.reindex(index=range(60), columns=range(24), fill_value=0)
    _fig, _ax = plt.subplots(figsize=(10, 3.2))
    _ax.imshow(np.log10(_m.to_numpy() + 1), aspect="auto", cmap="magma", origin="lower")
    _ax.set_xlabel("hora del hecho (America/Lima)")
    _ax.set_ylabel("minuto")
    _ax.set_xticks(range(0, 24, 2))
    _ax.set_yticks([0, 15, 30, 45])
    _ax.set_title("Heaping: eventos por hora y minuto (log10). Las franjas son :00 y :30",
                  fontsize=10)
    for _b in (6, 12, 18):
        _ax.axvline(_b - 0.5, color="white", lw=0.6, ls="--")
    mpl.rcParams["figure.dpi"] = 110
    mo.vstack([_fig, mo.md("Las líneas punteadas son los bordes de los cuatro turnos.")])
    return (plt,)


@app.cell
def _(mo, mods):
    _t = mods.head(15)[["modalidad", "n", "frac_total", "frac_midnight", "frac_madrugada",
                        "lag_mediana_h", "aoristica"]]
    mo.vstack([
        mo.md("### Modalidades: 00:00, madrugada y rezago hasta el registro"),
        mo.ui.table(_t.round(3), selection=None),
    ])
    return


@app.cell
def _(mo, sobrevive):
    mo.stop(not sobrevive, mo.md("**Una trampa mató el experimento: no hay mapas.**"))
    esquema = mo.ui.dropdown({"4 turnos (SIDPOL)": "turnos4", "6 bloques de 4 h": "bloques6"},
                             value="4 turnos (SIDPOL)", label="Turnos")
    esquema
    return (esquema,)


@app.cell
def _(esquema, mapa, mo):
    _nombres = (mapa[mapa["esquema"] == esquema.value]
                .sort_values("turno_idx")["turno"].drop_duplicates().tolist())
    turno = mo.ui.dropdown(_nombres, value=_nombres[-1], label="Turno")
    k = mo.ui.slider(2, 8, value=3, label="k (número de tipos)")
    mo.hstack([turno, k], justify="start")
    return k, turno


@app.cell
def _(mo, np, pdk, re):
    PUNTEADO = [130, 130, 130, 115]

    def deck(capas):
        d = pdk.Deck(
            layers=capas,
            initial_view_state=pdk.ViewState(latitude=-12.05, longitude=-77.0, zoom=9.6),
            map_style="dark_no_labels",
            tooltip={"text": "{etiqueta}"},
        )
        # Mismo arreglo que en `donde-falla-el-dato`: to_html + iframe, y fuera el
        # script de Google Maps que la plantilla de pydeck inyecta.
        _html = d.to_html(as_string=True, notebook_display=False)
        _html = re.sub(r"<script[^>]*maps\.googleapis\.com[^>]*>\s*</script>", "", _html)
        return mo.iframe(_html, height="560px")

    def capa_punteada(df):
        return pdk.Layer("H3HexagonLayer", df, get_hexagon="h3_index", coverage=0.34,
                         get_fill_color=PUNTEADO, stroked=False, filled=True,
                         pickable=True)

    def capa_color(df):
        return pdk.Layer("H3HexagonLayer", df, get_hexagon="h3_index",
                         get_fill_color="color", stroked=False, filled=True,
                         extruded=False, pickable=True)

    def rampa(v, lo, hi, cmap):
        x = np.clip((np.asarray(v) - lo) / (hi - lo), 0, 1)
        return [[int(255 * c) for c in cmap(xi)[:3]] + [215] for xi in x]

    return capa_color, capa_punteada, deck, rampa


@app.cell
def _(capa_color, capa_punteada, deck, esquema, mapa, mo, mpl, np, rampa, turno):
    _m = mapa[(mapa["esquema"] == esquema.value) & (mapa["turno"] == turno.value)].copy()
    _m["lr"] = np.log2(_m["rr_ciudad"])
    _dib = _m[_m["sobre_piso"]].copy()
    # Rampa magma: luminosidad monótona, sin verde, legible en deuteranopia. El color
    # es log2 de la razón contra la ciudad, recortado a ±1 (la mitad / el doble).
    _dib["color"] = rampa(_dib["lr"], -1, 1, mpl.colormaps["magma"])
    _dib["etiqueta"] = _dib.apply(
        lambda r: f"{r['turno']}: {r['p_encogida']:.1%} de {r['n_celda']:,} eventos · "
        f"×{r['rr_ciudad']:.2f} la ciudad", axis=1)
    _fuera = _m[~_m["sobre_piso"]].copy()
    _fuera["etiqueta"] = _fuera["n_celda"].map(lambda n: f"bajo el piso: {n} eventos")
    mo.vstack([
        mo.md(f"### Mapa por turno · {turno.value}: razón de la proporción de la celda "
              "contra la ciudad (oscuro = menos que la ciudad, claro = más; ±1 = ×½ a ×2). "
              "Proporciones encogidas hacia la ciudad (Dirichlet)."),
        deck([capa_punteada(_fuera), capa_color(_dib)]),
    ])
    return


@app.cell
def _(mo, trampas):
    _e = trampas["estructura"]
    _r = _e["solo_robo_callejero"]
    _dt = ", ".join(_e["distritos_extremo_tarde"])
    _dm = ", ".join(_e["distritos_extremo_madrugada"])
    _cargas = ", ".join(f"{k} {v:+.2f}" for k, v in _e["pca1_cargas"].items())
    _mez = "\n        ".join(
        f"| {cat} | " + " | ".join(f"{v:+.2f}" for v in d.values()) + " |"
        for cat, d in _e["spearman_firma_vs_mezcla"].items())
    mo.md(
        f"""
        ## ¿Tipos, gradiente o mezcla de delitos?

        - **Un eje.** El primer componente de la firma explica el
          {_e["pca_frac_var"][0]:.0%} de su varianza. Cargas: {_cargas}.
        - **Es geografía.** Moran's I del eje sobre vecinos H3: {_e["moran_eje"]:.2f}
          (p95 bajo permutación: {_e["moran_eje_nulo_p95"]:.2f}). Extremo tarde:
          {_dt}. Extremo madrugada: {_dm}.
        - **Solo robo callejero** ({_r["celdas_sobre_piso"]} celdas sobre el piso):
          sobredispersión {_r["sobredispersion"]:.2f}, fiabilidad split-half
          {_r["fiabilidad_split_half_aleatorio"]:.2f}, k elegido: {_r["k_elegido"]};
          su eje correlaciona {_r["spearman_eje_robo_vs_todos"]:.2f} (Spearman) con el
          de todos los delitos.
        - **Mezcla.** Spearman entre la firma de cada turno y la fracción de cada
          categoría en la celda:

        | categoría | madrugada | mañana | tarde | noche |
        |---|---:|---:|---:|---:|
        {_mez}
        """
    )
    return


@app.cell
def _(capa_color, capa_punteada, deck, eje, mapa, mo, mpl, rampa):
    _todas = mapa[mapa["esquema"] == "turnos4"].drop_duplicates("h3_index")
    _fuera = _todas[~_todas["sobre_piso"]].assign(
        etiqueta=lambda d: d["n_celda"].map(lambda n: f"bajo el piso: {n} eventos"))
    _lim = float(eje["eje_madrugada_tarde"].abs().quantile(0.98))
    _d = eje.assign(
        color=rampa(eje["eje_madrugada_tarde"], -_lim, _lim, mpl.colormaps["cividis"]),
        etiqueta=eje.apply(lambda r: f"eje {r['eje_madrugada_tarde']:+.2f} · "
                           f"{int(r['n_celda']):,} eventos", axis=1))
    mo.vstack([
        mo.md("### El continuo: puntaje de cada celda en el eje madrugada ↔ tarde "
              "(claro = más madrugada que la ciudad, oscuro = más tarde). Rampa cividis: "
              "luminosidad monótona, apta para deuteranopia."),
        deck([capa_punteada(_fuera), capa_color(_d)]),
    ])
    return


@app.cell
def _(est, esquema, mo, trampas):
    _c = trampas["clustering"][esquema.value]
    _e = est[est["esquema"] == esquema.value].round(3)
    _ksel = _c["k_elegido"]
    _txt = (f"El criterio (silhouette > p95 del nulo, ARI bootstrap p05 > p95 del nulo y "
            f"ARI bootstrap medio ≥ 0,75) elige **k = {_ksel}**." if _ksel else
            "**Ningún k pasa el criterio** (silhouette > p95 del nulo, ARI bootstrap p05 "
            "> p95 del nulo y ARI bootstrap medio ≥ 0,75): las particiones de abajo son "
            "exploratorias, no tipos.")
    mo.vstack([
        mo.md("## Chronotypes: ¿hay tipos de reloj?\n\nk-means sobre el clr de la firma "
              "encogida, 20 semillas por k, bootstrap multinomial dentro de celda, y el "
              "mismo procedimiento sobre una ciudad nula sin relojes (cada celda saca del "
              "perfil de la ciudad con su propio n). " + _txt),
        mo.ui.table(_e.drop(columns=["esquema"]), selection=None),
    ])
    return


@app.cell
def _(capa_color, capa_punteada, clusters, deck, esquema, k, mapa, mo, perfil, sens):
    OKABE = [[230, 159, 0], [86, 180, 233], [0, 114, 178], [213, 94, 0],
             [204, 121, 167], [240, 228, 66], [153, 153, 153], [51, 34, 136]]
    _cl = clusters[(clusters["esquema"] == esquema.value) & (clusters["k"] == k.value)]
    _pf = perfil[(perfil["esquema"] == esquema.value) & (perfil["k"] == k.value)]
    _et = dict(zip(_pf["cluster"], _pf["etiqueta"], strict=True))
    _cl = _cl.assign(color=_cl["cluster"].map(lambda g: OKABE[g] + [215]),
                     etiqueta=_cl["cluster"].map(lambda g: f"tipo {g}: {_et[g]}"))
    _todas = mapa[(mapa["esquema"] == esquema.value)][["h3_index", "n_celda"]]
    _fuera = _todas.drop_duplicates("h3_index")
    _fuera = _fuera[~_fuera["h3_index"].isin(_cl["h3_index"])].assign(
        etiqueta="bajo el piso: sin tipo")
    _cols = ["cluster", "n_celdas", "n_eventos", "etiqueta"] + [
        c for c in _pf.columns if c.startswith("rr_")]
    _s = sens[sens["esquema"] == esquema.value]
    mo.vstack([
        mo.md(f"### Mapa de tipos con k = {k.value}. Las etiquetas salen del dato "
              "(turno de mayor exceso sobre la ciudad), no de la hipótesis nocturna / "
              "diurna / madrugada."),
        deck([capa_punteada(_fuera), capa_color(_cl)]),
        mo.ui.table(_pf[_cols].round(3), selection=None),
        mo.md(f"**Sensibilidad** (k = {int(_s['k'].iloc[0])}): ARI de la partición "
              "principal contra la que resulta de deshacer una decisión de las trampas."),
        mo.ui.table(_s.round(3), selection=None),
    ])
    return


if __name__ == "__main__":
    app.run()
