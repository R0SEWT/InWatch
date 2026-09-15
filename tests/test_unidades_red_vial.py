"""Tests de las unidades de red vial: `tramo` e `interseccion`.

Todo sobre grafos sintéticos de pocos nodos en EPSG:32718, sin red. La descarga real con
osmnx no se prueba aquí: es I/O contra Overpass y su contrato lo fija osmnx.
"""

from __future__ import annotations

import networkx as nx
import pytest

gpd = pytest.importorskip("geopandas")
pytest.importorskip("osmnx")

from shapely.geometry import LineString, box  # noqa: E402

from inwatch.unidades import red_vial  # noqa: E402

CRS = "EPSG:32718"


def _grafo() -> nx.MultiDiGraph:
    """Cuatro intersecciones en línea recta sobre el eje x.

    - 1→2 y 2→1: calle de doble sentido de 100 m, con la misma geometría en ambos
      sentidos. Dirigida son dos aristas; como tramo es UNA.
    - 2→3: calle de un solo sentido de 100 m, sin `maxspeed` ni `name`.
    - 3→4: 100 m con `highway` como lista (osmnx la deja así cuando fusiona tramos).
    """
    G = nx.MultiDiGraph(crs=CRS)
    for n, x in [(1, 0.0), (2, 100.0), (3, 200.0), (4, 300.0)]:
        G.add_node(n, x=x, y=0.0, street_count=2)

    def arista(u, v, x0, x1, **attrs):
        G.add_edge(u, v, key=0, length=abs(x1 - x0),
                   geometry=LineString([(x0, 0.0), (x1, 0.0)]), **attrs)

    # `osmid` es el id de la vía OSM: los dos sentidos de una misma calle lo comparten, y
    # es lo que `ox.convert.to_undirected` usa para reconocerlos como la misma arista.
    base = {"osmid": 100, "highway": "primary", "name": "Av. Uno", "maxspeed": "50",
            "lanes": "2"}
    arista(1, 2, 0.0, 100.0, oneway=False, **base)
    arista(2, 1, 100.0, 0.0, oneway=False, **base)
    arista(2, 3, 100.0, 200.0, osmid=200, oneway=True, highway="residential", lanes="1")
    arista(3, 4, 200.0, 300.0, osmid=300, oneway=False, highway=["secondary", "tertiary"],
           name="Jr. Dos")
    return G


# ─── tramos e intersecciones ──────────────────────────────────────────────────
def test_la_calle_de_doble_sentido_es_un_solo_tramo():
    tramos = red_vial.tramos(_grafo())
    assert len(tramos) == 3
    assert tramos["largo_m"].sum() == pytest.approx(300.0)


def test_tramo_id_es_determinista_y_ordena_los_extremos():
    ids = set(red_vial.tramos(_grafo())["tramo_id"])
    assert ids == {"1-2-0", "2-3-0", "3-4-0"}


def test_el_orden_de_los_extremos_es_lexicografico_como_dice_el_contrato():
    """Con osmid reales (9-11 dígitos) el orden numérico y el lexicográfico difieren.

    El contrato fija el lexicográfico; este test lo ata, porque la diferencia rompe
    joins en silencio y no da error.
    """
    G = nx.MultiDiGraph(crs=CRS)
    for n, x in ((900_000_000, 0.0), (1_000_000_000, 100.0)):
        G.add_node(n, x=x, y=0.0, street_count=2)
    G.add_edge(1_000_000_000, 900_000_000, key=0, osmid=1, length=100.0, oneway=True,
               highway="residential",
               geometry=LineString([(100.0, 0.0), (0.0, 0.0)]))
    (tramo_id,) = red_vial.tramos(G)["tramo_id"]
    assert tramo_id == "1000000000-900000000-0"  # lexicográfico: "1…" < "9…"


def test_tramos_conserva_sentido_y_normaliza_highway():
    t = red_vial.tramos(_grafo()).set_index("tramo_id")
    assert bool(t.loc["2-3-0", "oneway"]) is True
    assert bool(t.loc["1-2-0", "oneway"]) is False
    assert t.loc["3-4-0", "highway"] == "secondary"
    assert t.crs == CRS


def test_tramos_exige_grafo_proyectado_en_metros():
    G = _grafo()
    G.graph["crs"] = "EPSG:4326"
    with pytest.raises(ValueError, match="EPSG:32718"):
        red_vial.tramos(G)


def test_intersecciones_usa_osmid_como_clave_string():
    inter = red_vial.intersecciones(_grafo())
    assert list(inter["node_id"]) == ["1", "2", "3", "4"]
    assert inter["node_id"].map(type).eq(str).all()
    assert inter.crs == CRS


def test_porcentaje_de_faltantes_por_atributo():
    """Lo exige el enunciado: % de aristas sin maxspeed, lanes o name."""
    faltan = red_vial.faltantes(red_vial.tramos(_grafo()))
    assert faltan["maxspeed"] == pytest.approx(200 / 3)
    assert faltan["name"] == pytest.approx(100 / 3)
    assert faltan["lanes"] == pytest.approx(100 / 3)


# ─── correspondencia por longitud ─────────────────────────────────────────────
def _poligonos() -> gpd.GeoDataFrame:
    """Dos celdas contiguas de 150 m que cubren x ∈ [0, 300], y ∈ [-50, 50]."""
    return gpd.GeoDataFrame(
        {"celda": ["izq", "der"]},
        geometry=[box(0, -50, 150, 50), box(150, -50, 300, 50)],
        crs=CRS,
    )


def test_correspondencia_conserva_la_longitud_de_cada_tramo_completo():
    corr = red_vial.correspondencia(red_vial.tramos(_grafo()), _poligonos(), clave="celda")
    suma = corr.groupby("tramo_id")["frac_tramo"].sum()
    assert suma.round(9).eq(1.0).all(), suma.to_dict()
    assert corr["largo_m"].sum() == pytest.approx(300.0)


def test_correspondencia_parte_el_tramo_a_caballo_por_longitud():
    corr = red_vial.correspondencia(red_vial.tramos(_grafo()), _poligonos(), clave="celda")
    partido = corr[corr["tramo_id"] == "2-3-0"].set_index("celda")
    assert partido.loc["izq", "largo_m"] == pytest.approx(50.0)
    assert partido.loc["der", "frac_tramo"] == pytest.approx(0.5)


def test_correspondencia_no_inventa_longitud_fuera_de_la_cobertura():
    """Un tramo que sale de toda celda suma < 1. Normalizarlo sería inventar calle."""
    solo_izq = _poligonos().iloc[[0]]
    corr = red_vial.correspondencia(red_vial.tramos(_grafo()), solo_izq, clave="celda")
    suma = corr.groupby("tramo_id")["frac_tramo"].sum()
    assert suma["2-3-0"] == pytest.approx(0.5)
    assert "3-4-0" not in suma.index


def test_correspondencia_descarta_astillas_bajo_el_umbral():
    """Un tramo que apenas roza otra celda no cuenta como partido."""
    celdas = gpd.GeoDataFrame(
        {"celda": ["grande", "roce"]},
        geometry=[box(0, -50, 299.5, 50), box(299.5, -50, 400, 50)],
        crs=CRS,
    )
    corr = red_vial.correspondencia(
        red_vial.tramos(_grafo()), celdas, clave="celda", longitud_minima_m=1.0
    )
    assert corr[corr["tramo_id"] == "3-4-0"]["celda"].tolist() == ["grande"]


def test_desvio_de_longitud_es_cero_en_una_tabla_sana():
    corr = red_vial.correspondencia(red_vial.tramos(_grafo()), _poligonos(), clave="celda")
    assert red_vial.desvio_de_longitud(corr) == pytest.approx(0.0, abs=1e-9)


def test_desvio_de_longitud_falla_si_ningun_tramo_queda_completo():
    """Devolver 0 sin nada contra qué verificar sería un check verde que no comprobó nada."""
    lejos = gpd.GeoDataFrame({"celda": ["x"]}, geometry=[box(1000, 1000, 1100, 1100)], crs=CRS)
    corr = red_vial.correspondencia(red_vial.tramos(_grafo()), lejos, clave="celda")
    with pytest.raises(ValueError, match="ningún tramo"):
        red_vial.desvio_de_longitud(corr)


def test_interseccion_se_asigna_a_la_celda_que_la_contiene():
    asign = red_vial.asignar_intersecciones(
        red_vial.intersecciones(_grafo()), _poligonos(), clave="celda"
    ).set_index("node_id")
    assert asign.loc["1", "celda"] == "izq"
    assert asign.loc["4", "celda"] == "der"


# ─── metadatos de descarga ────────────────────────────────────────────────────
def test_metadatos_registran_consulta_modo_y_versiones(tmp_path):
    meta = red_vial.metadatos(_grafo(), modo="drive", consulta="área A: 5 distritos")
    assert meta["modo"] == "drive"
    assert meta["crs"] == CRS
    assert meta["n_nodos"] == 4 and meta["n_aristas"] == 4
    assert {"osmnx", "networkx"} <= set(meta["versiones"])
    assert meta["descargado_en"]


def test_cargar_devuelve_los_booleanos_propios_como_bool_y_no_como_texto(tmp_path):
    """GraphML guarda todo como string y `bool("False")` es True.

    Sin reconvertir, un flag del repo se lee al revés en silencio: el grafo recargado
    diría que ninguna arista lleva velocidad imputada.
    """
    G = _grafo()
    for u, v, k in ((1, 2, 0), (2, 3, 0)):
        G.edges[u, v, k]["maxspeed_observado"] = u == 1
    ruta = tmp_path / "red.graphml"
    red_vial.guardar(G, ruta, red_vial.metadatos(G, modo="drive", consulta="q"))
    G2, _ = red_vial.cargar(ruta)
    valores = {(u, v): d["maxspeed_observado"] for u, v, d in G2.edges(data=True)
               if "maxspeed_observado" in d}
    assert valores[(1, 2)] is True
    assert valores[(2, 3)] is False


def test_cargar_falla_ruidoso_si_el_booleano_trae_basura(tmp_path):
    ruta = tmp_path / "red.graphml"
    G = _grafo()
    G.edges[1, 2, 0]["maxspeed_observado"] = "quizá"
    red_vial.guardar(G, ruta, red_vial.metadatos(G, modo="drive", consulta="q"))
    with pytest.raises(ValueError, match="maxspeed_observado"):
        red_vial.cargar(ruta)


def test_guardar_y_cargar_red_conserva_grafo_y_metadatos(tmp_path):
    G = _grafo()
    for _, _, d in G.edges(data=True):  # GraphML no serializa listas; osmnx las stringifica
        if isinstance(d.get("highway"), list):
            d["highway"] = str(d["highway"])
    ruta = tmp_path / "drive_2026-09-14.graphml"
    red_vial.guardar(G, ruta, red_vial.metadatos(G, modo="drive", consulta="q"))
    G2, meta = red_vial.cargar(ruta)
    assert G2.number_of_nodes() == 4
    assert meta["consulta"] == "q"
