"""Notebook marimo de `donde-falla-el-dato`: el mapa de dónde el mapa falla.

Solo lee el artefacto de ``loader.py`` y presenta. No calcula desde datos crudos —
eso vive en el loader, por la restricción de Pyodide (ver su docstring).

La codificación visual es deliberadamente austera: **un solo tono, y la opacidad
lleva la confianza**. No hay rampa de color que interpretar, no hay verde que se pueda
leer como "acá no pasa nada", y una rampa monocroma es monótona en luminosidad por
construcción, así que no hay nada que verificar en deuteranopia: no queda información
codificada en el matiz. Lo que no se puede sostener con dato, literalmente no se ve.

Las celdas no evaluables no desaparecen: se dibujan como un hexágono encogido, un
punteado que cubre la región sin afirmar nada sobre ella. Deshilachado, no vacío.

    uv run marimo edit experiments/donde-falla-el-dato/notebook.py
"""

import marimo

__generated_with = "0.23.16"
app = marimo.App(width="full")


@app.cell
def _():
    import re
    from pathlib import Path

    import marimo as mo
    import pandas as pd
    import pydeck as pdk

    from inwatch import canon

    return Path, canon, mo, pd, pdk, re


@app.cell
def _(canon, mo):
    _con_registro = canon.display("cobertura.celdas_con_registro")
    _evaluables = canon.display("cobertura.celdas_evaluables")
    mo.md(
        f"""
        # Dónde el mapa deja de ser confiable

        Casi ningún mapa de crimen muestra dónde falla su propio dato. Este lo muestra
        primero, antes de mostrar nada más.

        De la grilla canónica de Lima y Callao, solo el **{_con_registro} %** de las
        celdas tiene al menos un registro policial geocodificado, y solo el
        **{_evaluables} %** tiene además una medida de qué tan bien geocodifica su
        distrito. Todo lo demás son las celdas punteadas.

        **Sin datos ≠ seguro.** Una celda sin registro se dibuja deshilachada, nunca
        vacía ni verde. Ausencia de denuncia es ausencia de evidencia, no evidencia de
        ausencia. Y una celda cuyo distrito nunca se auditó no es una celda con dato
        malo: es una celda de la que no se sabe, que es distinto y peor.
        """
    )
    return


@app.cell
def _(Path, pd):
    SLUG = "donde-falla-el-dato"
    _art = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG / f"{SLUG}.parquet"
    if not _art.exists():
        raise FileNotFoundError(
            f"falta el artefacto: {_art}\n"
            f"  corre: uv run python experiments/{SLUG}/loader.py"
        )
    df = pd.read_parquet(_art)

    # Etiquetas de las tres medidas. Se declaran acá, en la capa de presentación,
    # porque son texto para un lector — el loader nombra las columnas, no las explica.
    MEDIDAS = {
        "geo_exito_distrito": "geocodificación exitosa",
        "geo_con_coord_distrito": "registro con alguna coordenada",
        "geo_coord_real_distrito": "coordenada real (no imputada)",
    }
    return MEDIDAS, SLUG, df


@app.cell
def _(MEDIDAS, mo):
    # Los tres controles que hacen del experimento un experimento.
    #
    # `medida` primero y a propósito: cuál se elija cambia qué significa "confiable".
    # Sus rangos ni se solapan, así que no son tres versiones del mismo número.
    medida = mo.ui.dropdown(
        # marimo toma las claves como etiquetas visibles, así que el diccionario va
        # invertido respecto de MEDIDAS: se muestra la frase, se devuelve la columna.
        options={etiqueta: col for col, etiqueta in MEDIDAS.items()},
        value=MEDIDAS["geo_exito_distrito"],
        label="Qué mide la confianza",
    )
    # El piso de calidad es el control principal: subirlo disuelve el mapa.
    piso_calidad = mo.ui.slider(
        0.0, 1.0, value=0.0, step=0.01, label="Piso de calidad geocodificadora",
        show_value=True,
    )
    # El soporte es el otro eje, y se mantiene separado a propósito: mezclarlo con la
    # calidad en un índice ponderado sería inventar una cifra portante con pesos
    # elegidos a mano. Escala logarítmica porque el soporte va de 1 a más de 4000.
    piso_soporte = mo.ui.slider(
        steps=[0, 1, 2, 5, 10, 25, 50, 100, 250, 500, 1000],
        value=0, label="Piso de soporte (registros en la celda)", show_value=True,
    )
    mo.vstack([medida, piso_calidad, piso_soporte])
    return medida, piso_calidad, piso_soporte


@app.cell
def _(df, medida, piso_calidad, piso_soporte):
    # Tres estados excluyentes, y el orden importa: "no evaluable" gana sobre "bajo el
    # piso", porque no poder medir no es lo mismo que medir mal.
    _calidad = df[medida.value]
    vista = df.assign(
        calidad=_calidad,
        evaluable_aqui=df["tiene_registro"] & _calidad.notna(),
    )
    vista["sobre_piso"] = (
        vista["evaluable_aqui"]
        & (vista["calidad"] >= piso_calidad.value)
        & (vista["soporte_registros"] >= piso_soporte.value)
    )
    return (vista,)


@app.cell
def _(canon, mo, vista):
    _n = len(vista)
    _sobre = int(vista["sobre_piso"].sum())
    _no_eval = int((~vista["evaluable_aqui"]).sum())
    # Cuánto del registro policial vive en las celdas que sobreviven al piso. Casi
    # siempre es mucho mayor que la fracción de celdas: el dato se concentra donde ya
    # se miraba, que es la forma que toma el sesgo de denuncia en el espacio.
    _masa = vista.loc[vista["sobre_piso"], "soporte_registros"].sum()
    _masa_pct = 100.0 * _masa / max(vista["soporte_registros"].sum(), 1)

    mo.md(
        f"""
        | | celdas | % de la grilla |
        |---|---:|---:|
        | Sobre el piso, se dibujan | {_sobre:,} | {100 * _sobre / _n:.1f} % |
        | Bajo el piso | {_n - _sobre - _no_eval:,} | {100 * (_n - _sobre - _no_eval) / _n:.1f} % |
        | No evaluables, punteadas | {_no_eval:,} | {100 * _no_eval / _n:.1f} % |

        Las celdas dibujadas retienen el **{_masa_pct:.1f} %** de los registros
        geocodificados. Que ese porcentaje caiga mucho más lento que el de celdas es el
        sesgo de denuncia visto de frente: el dato se concentra donde ya se miraba.

        Con el piso en cero ya faltan
        {canon.display("cobertura.celdas_sin_auditoria")} % de las celdas por no tener
        auditoría distrital — entre ellas **todo el Callao**, cuya cobertura observada
        es {canon.display("cobertura.celdas_con_registro_callao")} % contra
        {canon.display("cobertura.celdas_con_registro_lima")} % en Lima.
        """
    )
    return


@app.cell
def _(mo, pdk, re, vista):
    # Un solo tono. La opacidad ES la confianza: lo que no se puede sostener con dato
    # no se ve. Sin matiz no hay nada que interpretar mal ni que revisar en
    # deuteranopia.
    TONO = [214, 96, 46]  # naranja cálido, sin lectura de "seguro/peligroso"

    _dib = vista[vista["sobre_piso"]].copy()
    # Opacidad proporcional a la calidad, con un piso visible: una celda que pasó el
    # umbral tiene que verse, aunque apenas.
    _dib["alpha"] = (60 + 195 * _dib["calidad"].clip(0, 1)).round().astype(int)
    _dib["color"] = _dib["alpha"].map(lambda a: [*TONO, a])
    _dib["etiqueta"] = _dib.apply(
        lambda r: f"{r['distrito'] or 'sin distrito'} · {r['soporte_registros']:,} registros "
        f"· calidad {r['calidad']:.0%}",
        axis=1,
    )

    _fuera = vista[~vista["sobre_piso"]].copy()
    _fuera["etiqueta"] = _fuera["motivo"].astype(str)

    capa_punteado = pdk.Layer(
        "H3HexagonLayer",
        _fuera,
        get_hexagon="h3_index",
        # `coverage` encoge cada hexágono: la región queda cubierta por un punteado
        # que se lee como textura deshilachada, no como un bloque de color ni como un
        # hueco. Es la regla dura del repo hecha píxeles.
        #
        # Los valores salieron de mirar el render, no de estimarlos: con 0.28 y alfa
        # 70 los huecos INTERIORES de la mancha observada —celdas sin registro
        # rodeadas de celdas con registro— se leían como fondo liso, es decir, como
        # "acá no pasa nada". Que el punteado se vea en los bordes no basta; los
        # huecos de adentro son justo los que un lector interpretaría como seguros.
        coverage=0.34,
        get_fill_color=[130, 130, 130, 115],
        stroked=False,
        filled=True,
        pickable=True,
    )
    capa_confianza = pdk.Layer(
        "H3HexagonLayer",
        _dib,
        get_hexagon="h3_index",
        get_fill_color="color",
        stroked=False,
        filled=True,
        extruded=False,
        pickable=True,
    )
    mapa = pdk.Deck(
        layers=[capa_punteado, capa_confianza],
        # Centro y zoom salen del centroide real de la grilla (lat -12.30..-11.70,
        # lon -77.20..-76.70), no de la plaza de Armas: encuadrar en el centro de Lima
        # tira medio visor al mar y recorta justo el borde este, que es donde la
        # cobertura se deshilacha. El encuadre por defecto es parte del argumento.
        initial_view_state=pdk.ViewState(latitude=-12.0, longitude=-76.95, zoom=9.0),
        map_style="dark_no_labels",
        tooltip={"text": "{etiqueta}"},
    )
    # Vía `to_html` + `mo.iframe` y no dejando que marimo formatee el Deck directo:
    # el `_repr_html_` de pydeck importa IPython, que no es dependencia de este repo,
    # y falla en silencio dejando la celda del mapa vacía. Se descubrió exportando el
    # notebook y mirando el HTML, no corriéndolo — un mapa ausente no levanta error.
    _html = mapa.to_html(as_string=True, notebook_display=False)
    # La plantilla de pydeck inyecta el loader de Google Maps con una API key ajena
    # incrustada, pase el proveedor que se le pase. El basemap acá es Carto, así que
    # ese <script> solo sirve para que cada render de un notebook de investigación
    # golpee un tercero. Si pydeck cambia la plantilla, el patrón deja de casar y no
    # se rompe nada.
    _html = re.sub(r"<script[^>]*maps\.googleapis\.com[^>]*>\s*</script>", "", _html)
    mo.iframe(_html, height="560px")
    return capa_confianza, capa_punteado, mapa


@app.cell
def _(mo, vista):
    mo.md(
        f"""
        ## Los distritos que ni siquiera se pueden evaluar

        No aparecen en la auditoría de geocodificación, así que sobre ellos no se puede
        afirmar que el dato sea malo — solo que no se sabe. Son
        {vista.loc[~vista["tiene_auditoria"], "distrito"].dropna().nunique()} distritos,
        el Callao entero entre ellos.
        """
    )
    return


@app.cell
def _(mo, vista):
    _t = (
        vista[~vista["tiene_auditoria"]]
        .groupby("distrito", observed=True)
        .agg(celdas=("h3_index", "size"), registros=("soporte_registros", "sum"))
        .sort_values("celdas", ascending=False)
    )
    mo.ui.table(_t.reset_index(), selection=None)
    return


if __name__ == "__main__":
    app.run()
