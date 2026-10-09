"""Notebook marimo de `escalera-de-unidades`: el escalón de manzana, unidad por unidad.

Solo lee artefactos y presenta. No calcula desde datos crudos: los modelos, el
bootstrap y la asignación de puntos a unidades viven en ``loader.py`` y
``unidades_finas.py``, por la restricción de Pyodide.

**Exploratorio.** Las cifras de acá salen de ``data/silver/escalera-de-unidades/``, no
del registro canónico: el experimento no emite (``inwatch-uiv``). No se citan hasta que
se emitan con procedencia.

    uv run python experiments/escalera-de-unidades/loader.py
    uv run marimo edit experiments/escalera-de-unidades/notebook.py
"""

import marimo

__generated_with = "0.23.16"
app = marimo.App(width="full")


@app.cell
def _():
    import json
    from pathlib import Path

    import marimo as mo
    import matplotlib.pyplot as plt
    import pandas as pd

    return Path, json, mo, pd, plt


@app.cell
def _(mo):
    mo.md(
        """
        # La escalera de unidades

        La escalera de atribución agrega fuentes de datos de a una y mide cuánto mejora
        el ordenamiento intra-distrital del crimen geocodificado (ρ de Spearman, macro
        sobre cinco categorías). En hexágonos H3 encontró **un solo escalón
        significativo**: la manzana censal INEI. Todo lo demás, nulo.

        Acá se puede cambiar **la unidad** en la que se mide la escalera, y **cómo se
        tratan los hexágonos que cruzan un límite distrital**, y ver si el escalón —y
        los nulos— siguen donde estaban.

        Un nulo con intervalo que cruza cero **no es evidencia de ausencia**: es un
        efecto que este diseño no resuelve. Se dibuja con su intervalo entero, nunca
        como una barra en cero.

        *Exploratorio: cifras del loader, no del registro canónico.*
        """
    )
    return


@app.cell
def _(Path, json, pd):
    SLUG = "escalera-de-unidades"
    _dir = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG

    def _leer(nombre):
        p = _dir / nombre
        if not p.exists():
            raise FileNotFoundError(
                f"falta el artefacto: {p}\n  corre: uv run python experiments/{SLUG}/loader.py"
            )
        return pd.read_parquet(p) if p.suffix == ".parquet" else json.loads(p.read_text())

    contrastes = _leer("contrastes.parquet")
    reproduccion = _leer("reproduccion_h3.parquet")
    meta = _leer("familias.json")
    semillas = _leer("semillas.parquet") if (_dir / "semillas.parquet").exists() else None
    return contrastes, meta, reproduccion, semillas


@app.cell
def _(contrastes, mo):
    ETIQUETAS = {
        "h3_8_origen": "H3 res-8, como en origen (hexágonos de borde duplicados)",
        "h3_8": "H3 res-8, un hexágono = una fila (conteo sumado)",
        "h3_8_propio": "H3 res-8, solo puntos del distrito del hexágono",
        "manzana": "manzana censal INEI (centroide más cercano, ≤150 m)",
        "morfologica": "celda morfológica (tesselación city2graph)",
    }
    _presentes = [u for u in ETIQUETAS if u in set(contrastes["unidad"])]
    unidad = mo.ui.dropdown(
        {ETIQUETAS[u]: u for u in _presentes}, value=ETIQUETAS[_presentes[0]],
        label="unidad de evaluación",
    )
    banda = mo.ui.radio(
        {"simultáneo (max-t, familia de 3)": "sim", "marginal (percentil 95 %)": "marg"},
        value="simultáneo (max-t, familia de 3)", label="intervalo",
    )
    mo.hstack([unidad, banda], justify="start", gap=3)
    return ETIQUETAS, banda, unidad


@app.cell
def _(banda, contrastes, meta, plt, unidad):
    _t = contrastes[contrastes["unidad"] == unidad.value].reset_index(drop=True)
    _fam = meta["familias"][unidad.value]
    _rho = _fam["rho_macro"]
    _sim = banda.value == "sim"

    # Waterfall: parte de ρ(M1_demografia) y cada escalón suma su Δ, con el intervalo
    # del Δ colgado del tope de su barra. Tono único: oscuro = sobrevive la corrección,
    # gris = no. Sin verde ni rojo: acá no hay "bueno" y "malo", hay resuelto y no.
    _fig, _ax = plt.subplots(figsize=(8.5, 4.2))
    _pasos = [("demografía\ndistrital", None)] + [
        (_n, _r) for _n, _r in zip(
            ["+ manzana\ncensal INEI", "+ forma\nurbana OSM", "+ ocho fuentes\n(conjunto)"],
            _t.itertuples(), strict=False,
        )
    ]
    _nivel = _rho["M1_demografia"]
    _ax.bar(0, _nivel, color="#B8C2C8", width=0.6)
    _ax.text(0, _nivel + 0.005, f"{_nivel:.3f}", ha="center", va="bottom", fontsize=9)
    for _i, (_lab, _r) in enumerate(_pasos[1:], start=1):
        # H2 y H3 se miden contra M1b, no contra el escalón anterior del gráfico.
        _base = _rho[_r.base]
        _lo, _hi = (_r.sim_lo, _r.sim_hi) if _sim else (_r.ci_lo, _r.ci_hi)
        _col = "#1F3A4D" if _r.sobrevive else "#9AA5AD"
        _ax.bar(_i, _r.delta, bottom=_base, color=_col, width=0.6)
        _ax.errorbar(_i, _base + _r.delta, yerr=[[_r.delta - _lo], [_hi - _r.delta]],
                     color="#222", capsize=5, lw=1.2)
        # Un p en el piso del bootstrap es una cota, no un cero.
        _en_piso = _r.p_wy <= _fam["p_piso"] + 1e-12
        _p = f"p_WY < {_fam['p_piso']:.0e}" if _en_piso else f"p_WY = {_r.p_wy:.3f}"
        _ax.text(_i + 0.34, _base + _r.delta, f"{_r.delta:+.3f}\n{_p}", va="center", fontsize=8.5)
        _ax.hlines(_base, _i - 0.45, _i + 0.45, colors="#555", linestyles=":", lw=0.8)
    _ax.set_xticks(range(len(_pasos)), [p[0] for p in _pasos])
    _ax.set_ylabel("ρ intra-distrital (macro)")
    _todo = [_rho[s] for s in _rho] + list(_t["sim_hi"].dropna()) + list(_t["ci_hi"])
    _ax.set_ylim(0, max(_todo) * 1.12)
    _ax.set_xlim(-0.5, len(_pasos) - 0.1)
    _ax.spines[["top", "right"]].set_visible(False)
    _ax.set_title(f"{_fam['n_pares']} pares (categoría, distrito) · B = {meta['B']:,} · "
                  f"c max-t = {_fam['c_sim']:.2f}", fontsize=9, loc="left")
    _fig.tight_layout()
    _fig
    return


@app.cell
def _(ETIQUETAS, contrastes, meta, mo, pd):
    # El resumen que responde la pregunta: ¿sobrevive el escalón en cada unidad?
    _p = contrastes[contrastes["familia_primaria"]].copy()
    _p["unidad"] = pd.Categorical(_p["unidad"], categories=list(ETIQUETAS), ordered=True)
    _p = _p.sort_values(["unidad", "contraste"])
    _filas = ["| unidad | contraste | Δρ | CI 95 % simultáneo | p Westfall-Young | ¿sobrevive? |",
              "|:--|:--|--:|:--|--:|:--|"]
    for _r in _p.itertuples():
        _piso = meta["familias"][_r.unidad]["p_piso"]
        _pw = f"< {_piso:.0e} (piso)" if _r.p_wy <= _piso + 1e-12 else f"{_r.p_wy:.4f}"
        _filas.append(
            f"| {_r.unidad} | {_r.contraste} | {_r.delta:+.4f} | "
            f"[{_r.sim_lo:+.4f}, {_r.sim_hi:+.4f}] | {_pw} | {'**sí**' if _r.sobrevive else 'no'} |"
        )
    mo.md("## Las cuatro lecturas lado a lado\n\n" + "\n".join(_filas))
    return


@app.cell
def _(mo, semillas):
    # Sensibilidad a la semilla del modelo: HGB con early stopping sortea su split de
    # validación, así que la semilla cambia el ρ de cada escalón. Si el veredicto
    # dependiera de la semilla, no sería un veredicto.
    if semillas is None:
        _out = mo.md("*(sin `semillas.parquet`: corre el loader con `--semillas`)*")
    else:
        _s = semillas[semillas["familia_primaria"]]
        _g = (_s.groupby(["unidad", "contraste"])
              .agg(delta_min=("delta", "min"), delta_max=("delta", "max"),
                   sobrevive=("sobrevive", "sum"), n=("sobrevive", "size"))
              .reset_index())
        _filas = ["| unidad | contraste | Δρ mín–máx | sobrevive en |", "|:--|:--|:--|:--|"]
        for _r in _g.itertuples():
            _filas.append(f"| {_r.unidad} | {_r.contraste} | {_r.delta_min:+.3f} – "
                          f"{_r.delta_max:+.3f} | {_r.sobrevive}/{_r.n} semillas |")
        _out = mo.md("## ¿Y si cambia la semilla del modelo?\n\n" + "\n".join(_filas))
    _out
    return


@app.cell
def _(meta, mo, reproduccion):
    _chk = meta["diagnosticos"].get("puntos_vs_oraculo", {})
    _filas = ["| clave de origen | registro infelix | acá | diferencia |", "|:--|--:|--:|--:|"]
    for _r in reproduccion.itertuples():
        _filas.append(f"| `{_r.clave}` | {_r.origen:.6f} | {_r.aca:.6f} | {_r.dif:+.1e} |")
    _asig = [f"- **{u}**: {d['unidades']:,} unidades; {d['puntos_sin_unidad']:,} de "
             f"{d['puntos']:,} puntos quedan sin unidad"
             for u, d in meta["diagnosticos"].items() if u in ("manzana", "morfologica")]
    mo.md(
        "## Reproducción y asignación\n\n"
        "La escalera de origen se reproduce en `h3_8_origen` con el mismo panel, la misma "
        "semilla y B igual:\n\n" + "\n".join(_filas)
        + f"\n\nLos puntos limpios, agregados como el oráculo, lo rehacen con "
        f"{_chk.get('filas_distintas', '?')} filas distintas de {_chk.get('filas', '?')}.\n\n"
        + "\n".join(_asig)
    )
    return


if __name__ == "__main__":
    app.run()
