"""Notebook marimo de `tejido-vs-hexagono`: la unidad espacial como parámetro.

Solo lee los artefactos de ``loader.py`` y presenta. No calcula desde datos crudos —
geopandas y city2graph no corren en Pyodide, así que ni siquiera podría.

El parámetro manipulable acá **es la unidad**. En los otros experimentos se mueve un
umbral y el mapa cambia de contenido; en este se cambia la rejilla y el mapa cambia de
*sujeto*. Es la demostración de que "la unidad espacial es un parámetro" no es una
frase de diseño: es una perilla, y girarla parte manzanas.

Tres cosas que el lector tiene que poder ver por sí mismo, en este orden:

1. **El corte.** Sobre la misma cuadra, el borde del hexágono atraviesa manzanas que la
   tesselación mantiene enteras. No se argumenta, se superpone.
2. **La adyacencia vacía.** El grado del hexágono es ~6 para todos por construcción de
   la grilla. Un grafo sobre esa adyacencia no codifica ciudad, codifica rejilla.
3. **El hueco.** Subir el piso de cobertura areal disuelve la grilla y deja ver cuánta
   de ella nunca tuvo tejido edificado debajo. Esas celdas se dibujan encogidas, no
   verdes y no ausentes.

    uv run marimo edit experiments/tejido-vs-hexagono/notebook.py
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
    mo.md(
        f"""
        # La unidad espacial es un parámetro

        No hay rejilla privilegiada. La grilla canónica H3 res-8 existe porque los
        artefactos del trabajo de origen están calculados sobre ella, no porque respete
        la ciudad — un hexágono res-8 mide cientos de metros de arista y no sabe dónde
        termina una manzana.

        La tesselación morfológica construye la unidad al revés: las calles son
        **barreras**, los edificios son semillas, y cada celda es el espacio que le toca
        a un edificio dentro de su manzana cerrada. Sobre Lima y Callao salen
        **{canon.display("tejido.celdas")}** celdas donde el hexágono pone
        {canon.display("conteo.celdas_grilla")}.

        El precio de haber usado el hexágono está medido, no supuesto: el
        **{canon.display("correspondencia.celdas_partidas")} %** de las celdas
        morfológicas cae repartido entre dos o más hexágonos, y eso es el
        **{canon.display("correspondencia.area_partida")} %** del área del tejido. Cada
        una de esas celdas es una manzana cuyo valor el mapa hexagonal promedió con la
        de al lado sin decirlo.
        """
    )
    return


@app.cell
def _(Path, pd):
    SLUG = "tejido-vs-hexagono"
    _dir = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG

    def _leer(nombre: str) -> pd.DataFrame:
        ruta = _dir / f"{nombre}.parquet"
        if not ruta.exists():
            raise FileNotFoundError(
                f"falta el artefacto: {ruta}\n"
                f"  corre: uv run --extra geo python experiments/{SLUG}/loader.py"
            )
        return pd.read_parquet(ruta)

    celdas = _leer("tejido_celdas")
    cobertura = _leer("hexagonos_cobertura")
    ventana_hex = _leer("ventana_hexagonos")
    ventana_tejido = _leer("ventana_tejido")
    return celdas, cobertura, ventana_hex, ventana_tejido


@app.cell
def _(mo):
    mo.md(
        """
        ## 1 · El corte

        La misma cuadra, partida de dos maneras. Enciende y apaga cada capa: donde el
        borde naranja del hexágono cruza por encima de una celda azul, hay una manzana
        que el mapa hexagonal partió en dos.
        """
    )
    return


@app.cell
def _(mo):
    ver_tejido = mo.ui.checkbox(value=True, label="Tesselación morfológica (azul)")
    ver_hexagono = mo.ui.checkbox(value=True, label="Grilla H3 res-8 (naranja)")
    mo.hstack([ver_tejido, ver_hexagono], justify="start", gap=2)
    return ver_hexagono, ver_tejido


@app.cell
def _(mo, pdk, re, ventana_hex, ventana_tejido, ver_hexagono, ver_tejido):
    # pydeck quiere [[lng, lat], ...]; el loader deja las dos listas por separado para
    # no guardar una estructura anidada de dos niveles en parquet. El zip es Python
    # puro y corre en Pyodide, que es la razón de que la geometría llegue así.
    def _poligonos(df):
        d = df.copy()
        d["poligono"] = [
            [[x, y] for x, y in zip(lng, lat, strict=True)]
            for lng, lat in zip(d["lng"], d["lat"], strict=True)
        ]
        return d

    _tejido = _poligonos(ventana_tejido)
    _hex = _poligonos(ventana_hex)

    _centro = _hex["poligono"].iloc[0][0]

    _capas = []
    if ver_tejido.value:
        _capas.append(
            pdk.Layer(
                "PolygonLayer",
                _tejido,
                get_polygon="poligono",
                # Relleno tenue y borde nítido: lo que hay que ver es el **límite** de
                # cada celda, no su interior. Un relleno saturado convertiría la capa en
                # una mancha y taparía justo la comparación.
                get_fill_color=[70, 130, 190, 55],
                get_line_color=[70, 130, 190, 210],
                line_width_min_pixels=1,
                stroked=True,
                filled=True,
                pickable=True,
            )
        )
    if ver_hexagono.value:
        _capas.append(
            pdk.Layer(
                "PolygonLayer",
                _hex,
                get_polygon="poligono",
                # El hexágono va sin relleno y encima: es el que hace el corte, y tiene
                # que leerse como una cuchilla sobre el tejido, no como otra mancha.
                get_line_color=[214, 96, 46, 255],
                line_width_min_pixels=2,
                stroked=True,
                filled=False,
                pickable=True,
            )
        )

    _mapa = pdk.Deck(
        layers=_capas,
        initial_view_state=pdk.ViewState(
            latitude=_centro[1], longitude=_centro[0], zoom=14.2
        ),
        map_style="dark_no_labels",
    )
    # Vía `to_html` + `mo.iframe`: el `_repr_html_` de pydeck importa IPython, que no es
    # dependencia de este repo, y deja la celda del mapa vacía sin levantar error.
    _html = _mapa.to_html(as_string=True, notebook_display=False)
    # La plantilla de pydeck inyecta el loader de Google Maps con una API key ajena
    # incrustada, pase el proveedor que se le pase. El basemap acá es Carto, así que ese
    # <script> solo sirve para golpear a un tercero en cada render.
    _html = re.sub(r"<script[^>]*maps\.googleapis\.com[^>]*>\s*</script>", "", _html)
    mo.iframe(_html, height="520px")
    return


@app.cell
def _(canon, mo, ventana_hex, ventana_tejido):
    mo.md(
        f"""
        La ventana son {len(ventana_hex)} hexágonos y {len(ventana_tejido):,} celdas
        morfológicas: la mediana de la ciudad es de
        **{canon.display("correspondencia.tejido_por_hexagono_mediana")}** celdas por
        hexágono. Un hexágono no es una unidad de análisis fina que convenga suavizar;
        es un promedio sobre cientos de piezas de tejido con historias distintas.
        """
    )
    return


@app.cell
def _(canon, mo):
    mo.md(
        f"""
        ## 2 · La adyacencia hexagonal no informa

        Un grafo necesita aristas, y de dónde salgan decide qué puede aprender. La
        adyacencia H3 da a cada hexágono interior seis vecinos **por construcción de la
        grilla**: grado medio {canon.display("hexagono.grado_medio")} sobre
        {canon.display("conteo.celdas_grilla")} celdas. Eso no es una medición de la
        ciudad, es una propiedad del dibujo.

        La adyacencia morfológica es `touched_to`: dos celdas son vecinas si comparten
        borde **dentro de la misma manzana cerrada**. Dos edificios a ambos lados de una
        avenida se tocan en el mapa y no son vecinos acá, porque la avenida es una
        barrera y no un pixel. Su grado medio es
        {canon.display("tejido.grado_medio")} con desviación
        {canon.display("tejido.grado_desviacion")} — la dispersión es el dato: el grado
        varía con la forma real de la manzana.
        """
    )
    return


@app.cell
def _(celdas, mo, pd):
    # La distribución del grado, en texto y no en figura: el punto es la forma de la
    # distribución (una masa dispersa contra un pico en 6), y una tabla corta lo dice
    # sin arrastrar matplotlib a la capa de presentación.
    _dist = (
        celdas["grado"]
        .clip(upper=10)
        .value_counts(normalize=True)
        .sort_index()
        .mul(100)
        .round(1)
    )
    _tabla = pd.DataFrame(
        {
            "vecinos": [str(g) if g < 10 else "10 o más" for g in _dist.index],
            "% de celdas del tejido": _dist.to_numpy(),
        }
    )
    mo.hstack(
        [
            mo.ui.table(_tabla, selection=None),
            mo.md(
                """
                El hexágono no tiene tabla equivalente: **todas** sus celdas interiores
                están en la fila "6". Una columna de un solo valor no puede explicar
                nada, y un GNN sobre esa adyacencia aprende de las features, nunca de la
                estructura — que era el motivo de traer un grafo.
                """
            ),
        ],
        widths=[1, 1],
    )
    return


@app.cell
def _(canon, mo):
    mo.md(
        f"""
        ## 3 · Dónde la grilla nunca tuvo tejido debajo

        El tejido morfológico solo existe donde hay edificios registrados. Eso deja
        hexágonos de la grilla canónica sin una sola celda: el
        **{canon.display("correspondencia.hexagonos_sin_tejido")} %** de la grilla.

        **Sin datos ≠ seguro.** Esos hexágonos no son campo vacío ni zona tranquila: son
        celdas sobre las que OSM no registra edificación, y un mapa que las pinta igual
        que al resto está afirmando algo que nadie midió. Acá se dibujan encogidas —
        cubren su región sin llenarla.

        Mové el piso: exigirle al hexágono que esté realmente cubierto de tejido disuelve
        la grilla mucho antes de lo que su apariencia sólida sugiere.
        """
    )
    return


@app.cell
def _(mo):
    piso_cobertura = mo.ui.slider(
        0.0, 1.0, value=0.0, step=0.01,
        label="Piso de cobertura areal (fracción del hexágono cubierta por tejido)",
        show_value=True,
    )
    piso_cobertura
    return (piso_cobertura,)


@app.cell
def _(cobertura, mo, piso_cobertura):
    vista = cobertura.assign(
        sobre_piso=cobertura["tiene_tejido"]
        & (cobertura["cobertura_areal"] >= piso_cobertura.value)
    )
    _n = len(vista)
    _sobre = int(vista["sobre_piso"].sum())
    _sin = int((~vista["tiene_tejido"]).sum())
    _bajo = _n - _sobre - _sin

    mo.md(
        f"""
        | | hexágonos | % de la grilla |
        |---|---:|---:|
        | Sobre el piso, se dibujan | {_sobre:,} | {100 * _sobre / _n:.1f} % |
        | Con tejido, bajo el piso | {_bajo:,} | {100 * _bajo / _n:.1f} % |
        | Sin ninguna celda de tejido | {_sin:,} | {100 * _sin / _n:.1f} % |
        """
    )
    return (vista,)


@app.cell
def _(mo, pdk, re, vista):
    TONO = [70, 130, 190]  # el azul del tejido, para que la lectura sea continua

    _dib = vista[vista["sobre_piso"]].copy()
    _dib["alpha"] = (55 + 200 * _dib["cobertura_areal"].clip(0, 1)).round().astype(int)
    _dib["color"] = _dib["alpha"].map(lambda a: [*TONO, a])
    _dib["etiqueta"] = _dib.apply(
        lambda r: f"{r['distrito'] or 'sin distrito'} · {r['celdas_tejido']:,} celdas "
        f"· cobertura {r['cobertura_areal']:.0%}",
        axis=1,
    )

    _fuera = vista[~vista["sobre_piso"]].copy()
    _fuera["etiqueta"] = _fuera["tiene_tejido"].map(
        {True: "bajo el piso de cobertura", False: "sin tejido edificado"}
    )

    _capa_punteado = pdk.Layer(
        "H3HexagonLayer",
        _fuera,
        get_hexagon="h3_index",
        # `coverage` encoge el hexágono: la región queda cubierta por un punteado que se
        # lee como textura deshilachada, no como bloque de color ni como hueco. Mismo
        # valor que en `donde-falla-el-dato`, por la misma razón: con menos, los huecos
        # interiores de la mancha se leen como fondo liso, o sea como "acá no pasa nada".
        coverage=0.34,
        get_fill_color=[130, 130, 130, 115],
        stroked=False,
        filled=True,
        pickable=True,
    )
    _capa_cobertura = pdk.Layer(
        "H3HexagonLayer",
        _dib,
        get_hexagon="h3_index",
        get_fill_color="color",
        stroked=False,
        filled=True,
        pickable=True,
    )
    _mapa = pdk.Deck(
        layers=[_capa_punteado, _capa_cobertura],
        # Mismo encuadre que `donde-falla-el-dato`: centrado en el centroide real de la
        # grilla y no en el centro de Lima, que tira medio visor al mar y recorta el
        # borde este — que es justo donde el tejido se acaba.
        initial_view_state=pdk.ViewState(latitude=-12.0, longitude=-76.95, zoom=9.0),
        map_style="dark_no_labels",
        tooltip={"text": "{etiqueta}"},
    )
    _html = _mapa.to_html(as_string=True, notebook_display=False)
    _html = re.sub(r"<script[^>]*maps\.googleapis\.com[^>]*>\s*</script>", "", _html)
    mo.iframe(_html, height="560px")
    return


@app.cell
def _(canon, mo):
    mo.md(
        f"""
        ## Qué queda anotado

        La tabla de correspondencia `tess_id` ↔ `h3_index` con factor de área en ambos
        sentidos es lo que `design/contrato-unidades.md` exige antes de admitir una
        unidad nueva, y existe para que ningún cruce entre capas vuelva a hacerse con un
        `merge` implícito. Reconstruir el área de una celda desde la tabla desvía como
        máximo **{canon.display("correspondencia.desvio_masa")}** en términos relativos:
        el reparto no pierde ni inventa masa.

        Lo que **no** está resuelto: `frac_h3` no suma 1 en casi ningún hexágono, porque
        el tejido no cubre todo. Repartir una cantidad de H3 hacia el tejido exige
        decidir qué hacer con ese déficit, y esa decisión es del experimento que lo
        necesite — normalizarla acá, en silencio, sería exactamente el join implícito que
        el contrato prohíbe.
        """
    )
    return


if __name__ == "__main__":
    app.run()
