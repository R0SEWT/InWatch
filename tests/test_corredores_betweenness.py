"""Tests de la betweenness de `corredores-criticos` (TP, bead inwatch-92d.3).

Todo sobre grafos sintéticos de pocos nodos: el valor exacto de la betweenness en una
cadena y en un rombo se calcula a mano, así que los tests verifican la cifra y no solo
que el código corra.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import networkx as nx
import pandas as pd
import pytest

pytest.importorskip("osmnx")

_MOD = Path(__file__).resolve().parents[1] / "experiments/corredores-criticos/centralidad.py"
_spec = importlib.util.spec_from_file_location("corredores_centralidad", _MOD)
centralidad = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(centralidad)


def _multi(aristas: list[tuple[int, int, int, float, float]]) -> nx.MultiDiGraph:
    """(u, v, key, length, travel_time) → MultiDiGraph con coordenadas triviales."""
    G = nx.MultiDiGraph(crs="EPSG:32718")
    for u, v, k, largo, tiempo in aristas:
        for n in (u, v):
            G.add_node(n, x=float(n), y=0.0)
        G.add_edge(u, v, key=k, length=largo, travel_time=tiempo)
    return G


# ─── a_digrafo ────────────────────────────────────────────────────────────────
def test_a_digrafo_colapsa_paralelas_con_el_minimo_de_cada_peso():
    """La paralela más corta y la más rápida pueden ser distintas: se guardan ambas."""
    G = _multi([(1, 2, 0, 100.0, 20.0), (1, 2, 1, 150.0, 10.0), (2, 3, 0, 50.0, 5.0)])
    D = centralidad.a_digrafo(G)
    assert D.number_of_edges() == 2
    assert D[1][2]["length"] == 100.0 and D[1][2]["key_length"] == 0
    assert D[1][2]["travel_time"] == 10.0 and D[1][2]["key_travel_time"] == 1


def test_a_digrafo_falla_si_una_arista_no_tiene_un_peso():
    G = _multi([(1, 2, 0, 100.0, 20.0)])
    del G.edges[1, 2, 0]["travel_time"]
    with pytest.raises(ValueError, match="travel_time"):
        centralidad.a_digrafo(G)


# ─── betweenness exacta ───────────────────────────────────────────────────────
def test_betweenness_exacta_en_una_cadena_dirigida():
    """1→2→3: solo el camino 1→3 pasa por 2.

    Nodos, dirigido y normalizado por (n−1)(n−2) = 2: el nodo 2 vale 1/2.
    Aristas, normalizado por n(n−1) = 6: (1,2) está en 1→2 y 1→3, así que vale 2/6.
    """
    D = centralidad.a_digrafo(_multi([(1, 2, 0, 1.0, 1.0), (2, 3, 0, 1.0, 1.0)]))
    nodos, arcos = centralidad.betweenness(D, peso="length")
    assert nodos[2] == pytest.approx(0.5)
    assert nodos[1] == nodos[3] == 0.0
    assert arcos[(1, 2)] == pytest.approx(2 / 6)
    assert arcos[(2, 3)] == pytest.approx(2 / 6)


def test_la_betweenness_depende_del_peso():
    """Rombo 1→{2,3}→4: por 2 es la ruta corta; por 3, la rápida."""
    D = centralidad.a_digrafo(_multi([
        (1, 2, 0, 1.0, 10.0), (2, 4, 0, 1.0, 10.0),
        (1, 3, 0, 5.0, 1.0), (3, 4, 0, 5.0, 1.0),
    ]))
    por_largo, _ = centralidad.betweenness(D, peso="length")
    por_tiempo, _ = centralidad.betweenness(D, peso="travel_time")
    assert por_largo[2] > 0 and por_largo[3] == 0
    assert por_tiempo[3] > 0 and por_tiempo[2] == 0


def test_betweenness_con_k_es_reproducible_con_semilla():
    D = centralidad.a_digrafo(_multi([(i, i + 1, 0, 1.0, 1.0) for i in range(30)]))
    a, _ = centralidad.betweenness(D, peso="length", k=10, seed=7)
    b, _ = centralidad.betweenness(D, peso="length", k=10, seed=7)
    pd.testing.assert_series_equal(a, b)


# ─── de arcos dirigidos a tramos ──────────────────────────────────────────────
def test_a_tramos_suma_ambos_sentidos_y_asigna_la_paralela_mas_corta():
    arcos = pd.Series({(1, 2): 0.3, (2, 1): 0.2, (2, 3): 0.1})
    tramos = pd.DataFrame({
        "tramo_id": ["1-2-0", "1-2-1", "2-3-0"],
        "u": [1, 1, 2], "v": [2, 2, 3],
        "largo_m": [100.0, 150.0, 50.0],
    })
    salida = centralidad.a_tramos(arcos, tramos).set_index("tramo_id")["betweenness"]
    assert salida["1-2-0"] == pytest.approx(0.5)
    assert salida["1-2-1"] == 0.0
    assert salida["2-3-0"] == pytest.approx(0.1)


def test_a_tramos_no_pierde_betweenness():
    arcos = pd.Series({(1, 2): 0.3, (2, 1): 0.2, (2, 3): 0.1})
    tramos = pd.DataFrame({"tramo_id": ["1-2-0", "2-3-0"], "u": [1, 2], "v": [2, 3],
                           "largo_m": [100.0, 50.0]})
    assert centralidad.a_tramos(arcos, tramos)["betweenness"].sum() == pytest.approx(0.6)


# ─── error de la aproximación ─────────────────────────────────────────────────
def test_comparar_da_uno_cuando_la_aproximacion_es_exacta():
    exacta = pd.Series({"a": 0.9, "b": 0.5, "c": 0.2, "d": 0.1})
    r = centralidad.comparar(exacta.copy(), exacta, top=2)
    assert r == {"spearman": pytest.approx(1.0), "solape_top": pytest.approx(1.0)}


def test_comparar_detecta_un_top_distinto():
    exacta = pd.Series({"a": 0.9, "b": 0.5, "c": 0.2, "d": 0.1})
    invertida = pd.Series({"a": 0.1, "b": 0.2, "c": 0.5, "d": 0.9})
    r = centralidad.comparar(invertida, exacta, top=2)
    assert r["spearman"] == pytest.approx(-1.0)
    assert r["solape_top"] == 0.0


def test_comparar_rechaza_un_top_mayor_que_las_unidades():
    s = pd.Series({"a": 1.0, "b": 0.5})
    with pytest.raises(ValueError, match="top"):
        centralidad.comparar(s, s, top=3)
