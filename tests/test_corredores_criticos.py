"""Tests de `corredores-criticos` (TP de Complex Networks, tema 2).

La lógica del loader corre sin datos sobre un grafo sintético: marcar qué `maxspeed` es
real antes de que osmnx impute, velocidades y tiempos de viaje, y el resumen que exige
el enunciado. Solo el chequeo del grafo real del área A necesita artefactos y va
marcado `needs_data`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import networkx as nx
import pytest

pytest.importorskip("osmnx")
pytest.importorskip("geopandas")

from shapely.geometry import LineString  # noqa: E402

_LOADER = Path(__file__).resolve().parents[1] / "experiments/corredores-criticos/loader.py"
_spec = importlib.util.spec_from_file_location("corredores_loader", _LOADER)
loader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(loader)

CRS = "EPSG:32718"


def _grafo() -> nx.MultiDiGraph:
    """Cuatro intersecciones y cinco aristas dirigidas.

    - 1→2 y 2→1: primary de 1000 m con maxspeed 60 (real).
    - 2→3: primary de 500 m SIN maxspeed → se imputa con la media de primary (60).
    - 3→4: residential de 200 m SIN maxspeed → se imputa con la media de residential (30).
    - 4→1: residential de 300 m con maxspeed 30 (real).
    """
    G = nx.MultiDiGraph(crs=CRS)
    coords = {1: (0.0, 0.0), 2: (1000.0, 0.0), 3: (1500.0, 0.0), 4: (1500.0, 200.0)}
    for n, (x, y) in coords.items():
        G.add_node(n, x=x, y=y, street_count=2)

    def arista(u, v, **attrs):
        G.add_edge(u, v, key=0, geometry=LineString([coords[u], coords[v]]), **attrs)

    arista(1, 2, osmid=10, highway="primary", length=1000.0, maxspeed="60", oneway=False)
    arista(2, 1, osmid=10, highway="primary", length=1000.0, maxspeed="60", oneway=False)
    arista(2, 3, osmid=20, highway="primary", length=500.0, oneway=True)
    arista(3, 4, osmid=30, highway="residential", length=200.0, oneway=True)
    arista(4, 1, osmid=40, highway="residential", length=300.0, maxspeed="30", oneway=True)
    return G


def _por_arista(G: nx.MultiDiGraph, atributo: str) -> dict[tuple[int, int], object]:
    return {(u, v): d[atributo] for u, v, d in G.edges(data=True)}


# ─── área A ───────────────────────────────────────────────────────────────────
def test_el_area_a_son_los_cinco_distritos_del_eje_metropolitano():
    assert set(loader.UBIGEOS) == {"150101", "150115", "150131", "150122", "150141"}
    assert loader.MODO == "drive"


def test_el_poligono_sale_de_una_fuente_que_existe_al_clonar():
    """Sin esto el TP solo corre en la máquina que tiene infelix montado."""
    from inwatch import fuentes

    f = fuentes.cargar_catalogo(fuentes.load_config(Path(__file__).parent))
    assert f.fuentes[loader.FUENTE_POLIGONO].curado


# ─── velocidades y tiempos ────────────────────────────────────────────────────
def test_marca_que_maxspeed_es_real_antes_de_imputar():
    G = loader.marcar_maxspeed(_grafo())
    assert _por_arista(G, "maxspeed_observado") == {
        (1, 2): True, (2, 1): True, (2, 3): False, (3, 4): False, (4, 1): True,
    }


def test_preparar_imputa_por_tipo_de_via_y_calcula_el_tiempo():
    G = loader.preparar(_grafo())
    velocidad = _por_arista(G, "speed_kph")
    assert velocidad[(2, 3)] == pytest.approx(60.0)
    assert velocidad[(3, 4)] == pytest.approx(30.0)
    tiempo = _por_arista(G, "travel_time")
    assert tiempo[(2, 3)] == pytest.approx(500 / (60 / 3.6))
    assert tiempo[(3, 4)] == pytest.approx(200 / (30 / 3.6))


def test_preparar_no_altera_las_velocidades_observadas():
    G = loader.preparar(_grafo())
    velocidad = _por_arista(G, "speed_kph")
    assert velocidad[(1, 2)] == pytest.approx(60.0)
    assert velocidad[(4, 1)] == pytest.approx(30.0)
    assert all(_por_arista(G, "maxspeed_observado")[e] for e in [(1, 2), (2, 1), (4, 1)])


def test_preparar_exige_el_grafo_proyectado():
    G = _grafo()
    G.graph["crs"] = "EPSG:4326"
    with pytest.raises(ValueError, match="EPSG:32718"):
        loader.preparar(G)


# ─── resumen para el enunciado ────────────────────────────────────────────────
def test_resumen_da_el_porcentaje_imputado_por_aristas_y_por_longitud():
    r = loader.resumen(loader.preparar(_grafo()))
    assert (r["n_nodos"], r["n_aristas"]) == (4, 5)
    assert r["pct_maxspeed_imputado_aristas"] == pytest.approx(100 * 2 / 5)
    assert r["pct_maxspeed_imputado_largo"] == pytest.approx(100 * 700 / 3000)


def test_resumen_incluye_los_faltantes_por_tramo():
    """El enunciado pide % sin maxspeed, lanes y name; se cuenta sobre tramos no dirigidos."""
    r = loader.resumen(loader.preparar(_grafo()))
    assert r["pct_sin_maxspeed"] == pytest.approx(100 * 2 / 4)
    assert r["pct_sin_lanes"] == pytest.approx(100.0)
    assert r["pct_sin_name"] == pytest.approx(100.0)


def test_reduccion_por_simplificacion():
    assert loader.reduccion_por_simplificacion(n_sin=10_000, n_con=7_500) == pytest.approx(25.0)


def test_reduccion_por_simplificacion_rechaza_un_grafo_simplificado_mas_grande():
    with pytest.raises(ValueError, match="simplificado"):
        loader.reduccion_por_simplificacion(n_sin=100, n_con=120)


# ─── el grafo real del área A ─────────────────────────────────────────────────
@pytest.mark.needs_data
def test_el_grafo_real_cumple_el_minimo_del_enunciado():
    ruta = loader.OUT / loader.GRAPHML
    if not ruta.exists():
        pytest.fail(
            f"falta {ruta}: corre `uv run python experiments/corredores-criticos/loader.py`"
        )
    G, meta = loader.red_vial.cargar(ruta)
    assert G.number_of_nodes() >= 3_000
    assert G.number_of_edges() >= 6_000
    assert meta["modo"] == "drive"
    assert all("travel_time" in d for _, _, d in G.edges(data=True))
