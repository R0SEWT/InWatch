"""Tests de las métricas globales y locales de `corredores-criticos` (bead inwatch-92d.9).

Sobre grafos sintéticos cuyo valor se sabe a mano: una grilla perfecta tiene orden φ = 1,
una calle recta tiene circuidad 1, un ciclo dirigido es una sola componente fuerte.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import pytest

_MOD = Path(__file__).resolve().parents[1] / "experiments/corredores-criticos/metricas.py"
_spec = importlib.util.spec_from_file_location("corredores_metricas", _MOD)
metricas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(metricas)


def _grilla(lado: int = 3, paso: float = 100.0) -> nx.MultiDiGraph:
    """Grilla lado×lado de doble sentido, con street_count = grado físico."""
    G = nx.MultiDiGraph(crs="EPSG:32718")
    for i in range(lado):
        for j in range(lado):
            G.add_node((i, j), x=i * paso, y=j * paso)
    for i in range(lado):
        for j in range(lado):
            for di, dj in ((1, 0), (0, 1)):
                a, b = (i, j), (i + di, j + dj)
                if b in G:
                    G.add_edge(a, b, length=paso, travel_time=10.0)
                    G.add_edge(b, a, length=paso, travel_time=10.0)
    for n in G.nodes:
        G.nodes[n]["street_count"] = len(set(G.successors(n)) | set(G.predecessors(n)))
    return G


def _tramos_y_xy(G: nx.MultiDiGraph) -> tuple[pd.DataFrame, pd.DataFrame]:
    vistos, filas = set(), []
    for u, v, d in G.edges(data=True):
        par = frozenset((u, v))
        if par in vistos:
            continue
        vistos.add(par)
        filas.append({"u": u, "v": v, "largo_m": d["length"]})
    xy = pd.DataFrame.from_dict(dict(G.nodes(data=True)), orient="index")[["x", "y"]]
    return pd.DataFrame(filas), xy


# ─── orientación ──────────────────────────────────────────────────────────────
def test_grilla_perfecta_tiene_orden_uno_y_entropia_ln4():
    tramos, xy = _tramos_y_xy(_grilla())
    masa = metricas.histograma_orientacion(*metricas.rumbos(tramos, xy))
    o = metricas.orientacion(masa)
    assert o["entropia"] == pytest.approx(math.log(4))
    assert o["orden"] == pytest.approx(1.0)


def test_orientacion_uniforme_tiene_orden_cero():
    o = metricas.orientacion(np.ones(metricas.N_BINS))
    assert o["entropia"] == pytest.approx(math.log(metricas.N_BINS))
    assert o["orden"] == pytest.approx(0.0)


def test_histograma_cuenta_las_dos_direcciones_y_centra_el_norte():
    """Una calle norte-sur llena el bin 0 (norte) y el 18 (sur), con la misma masa."""
    masa = metricas.histograma_orientacion(np.array([2.0]), np.array([50.0]))
    assert masa[0] == pytest.approx(50.0)
    assert masa[18] == pytest.approx(50.0)
    assert masa.sum() == pytest.approx(100.0)


def test_rumbo_se_mide_desde_el_norte_en_sentido_horario():
    tramos = pd.DataFrame({"u": [0], "v": [1], "largo_m": [10.0]})
    xy = pd.DataFrame({"x": [0.0, 10.0], "y": [0.0, 0.0]}, index=[0, 1])
    rumbo, _ = metricas.rumbos(tramos, xy)
    assert rumbo[0] == pytest.approx(90.0)


# ─── circuidad ────────────────────────────────────────────────────────────────
def test_circuidad_de_calles_rectas_es_uno():
    tramos, xy = _tramos_y_xy(_grilla())
    assert metricas.circuidad(tramos, xy) == pytest.approx(1.0)


def test_circuidad_pondera_por_longitud_y_excluye_lazos():
    xy = pd.DataFrame({"x": [0.0, 100.0], "y": [0.0, 0.0]}, index=[0, 1])
    tramos = pd.DataFrame({"u": [0, 1], "v": [1, 1], "largo_m": [150.0, 40.0]})
    assert metricas.circuidad(tramos, xy) == pytest.approx(1.5)


# ─── componentes, grados, densidad ────────────────────────────────────────────
def test_componentes_distinguen_fuerte_de_debil():
    """Ciclo 1→2→3→1 más un ramal de un solo sentido 3→4: 2 SCC, 1 WCC."""
    G = nx.MultiDiGraph()
    G.add_edges_from([(1, 2), (2, 3), (3, 1), (3, 4)])
    c = metricas.componentes(G)
    assert (c["n_scc"], c["n_wcc"]) == (2, 1)
    assert c["pct_nodos_scc_gigante"] == pytest.approx(75.0)
    assert c["pct_nodos_wcc_gigante"] == pytest.approx(100.0)


def test_grados_de_una_grilla_3x3():
    """4 esquinas (2 calles), 4 bordes (3) y un centro (4)."""
    g = metricas.grados(_grilla())
    assert g["calles_por_nodo"] == pytest.approx((4 * 2 + 4 * 3 + 4) / 9)
    assert g["pct_nodos_3_calles"] == pytest.approx(100 * 4 / 9)
    assert g["pct_nodos_4_o_mas"] == pytest.approx(100 / 9)
    assert g["pct_nodos_callejon"] == 0.0
    assert g["grado_medio_salida"] == pytest.approx(24 / 9)


def test_grados_exige_street_count():
    G = nx.MultiDiGraph()
    G.add_edge(1, 2)
    with pytest.raises(ValueError, match="street_count"):
        metricas.grados(G)


def test_densidad_x1e4_es_la_dirigida():
    G = nx.MultiDiGraph()
    G.add_edges_from([(1, 2), (2, 1), (2, 3)])
    assert metricas.densidad_x1e4(G) == pytest.approx(1e4 * 3 / 6)


def test_clustering_de_un_triangulo_es_uno():
    G = nx.MultiDiGraph()
    G.add_edges_from([(1, 2), (2, 3), (3, 1)])
    assert metricas.clustering_medio(G) == pytest.approx(1.0)


# ─── closeness ────────────────────────────────────────────────────────────────
def test_closeness_es_nan_fuera_de_la_scc_gigante():
    D = nx.DiGraph()
    D.add_edge(1, 2, length=1.0)
    D.add_edge(2, 3, length=1.0)
    D.add_edge(3, 1, length=1.0)
    D.add_edge(3, 4, length=1.0)
    c = metricas.closeness_gigante(D)
    assert math.isnan(c[4])
    # En un ciclo dirigido de 3 con aristas unitarias, las distancias de llegada son 1 y 2.
    assert c[1] == pytest.approx(2 / 3)
