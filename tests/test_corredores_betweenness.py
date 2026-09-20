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
    """Rombo 1→{2,3}→4: por 2 es la ruta corta; por 3, la rápida.

    El valor exacto es 1/6: de los 4·3 = 12 pares ordenados, solo 1→4 pasa por el nodo
    del medio, y la normalización dirigida divide entre (n−1)(n−2) = 6. Afirmarlo fija
    también la normalización; con `normalized=False` este test fallaría.
    """
    D = centralidad.a_digrafo(_multi([
        (1, 2, 0, 1.0, 10.0), (2, 4, 0, 1.0, 10.0),
        (1, 3, 0, 5.0, 1.0), (3, 4, 0, 5.0, 1.0),
    ]))
    por_largo, _ = centralidad.betweenness(D, peso="length")
    por_tiempo, _ = centralidad.betweenness(D, peso="travel_time")
    assert por_largo[2] == pytest.approx(1 / 6) and por_largo[3] == 0
    assert por_tiempo[3] == pytest.approx(1 / 6) and por_tiempo[2] == 0


def test_con_k_igual_a_todos_los_nodos_la_aproximada_es_la_exacta():
    """Ata que `k` de verdad muestrea y que networkx reescala por n/k.

    El test de reproducibilidad con semilla pasaría aunque `k` se ignorara por completo.
    """
    D = centralidad.a_digrafo(_multi([(i, i + 1, 0, 1.0, 1.0) for i in range(12)]))
    exacta, arcos_exacta = centralidad.betweenness(D, peso="length")
    completa, arcos_completa = centralidad.betweenness(D, peso="length", k=D.number_of_nodes())
    pd.testing.assert_series_equal(completa, exacta)
    assert (arcos_completa - arcos_exacta).abs().max() < 1e-12


def test_betweenness_con_k_es_reproducible_con_semilla():
    D = centralidad.a_digrafo(_multi([(i, i + 1, 0, 1.0, 1.0) for i in range(30)]))
    a, _ = centralidad.betweenness(D, peso="length", k=10, seed=7)
    b, _ = centralidad.betweenness(D, peso="length", k=10, seed=7)
    pd.testing.assert_series_equal(a, b)


# ─── de arcos dirigidos a tramos ──────────────────────────────────────────────
def _tramos_paralelos() -> pd.DataFrame:
    """Dos paralelas entre 1 y 2: la corta es la lenta, la larga es la rápida."""
    return pd.DataFrame({
        "tramo_id": ["1-2-0", "1-2-1", "2-3-0"],
        "u": [1, 1, 2], "v": [2, 2, 3],
        "largo_m": [100.0, 150.0, 50.0],
        "travel_time": [18.0, 9.0, 5.0],
    })


def test_a_tramos_suma_ambos_sentidos_y_asigna_la_paralela_mas_corta():
    arcos = pd.Series({(1, 2): 0.3, (2, 1): 0.2, (2, 3): 0.1})
    salida = centralidad.a_tramos(arcos, _tramos_paralelos(), peso="length")
    salida = salida.set_index("tramo_id")["betweenness"]
    assert salida["1-2-0"] == pytest.approx(0.5)
    assert salida["1-2-1"] == 0.0
    assert salida["2-3-0"] == pytest.approx(0.1)


def test_por_tiempo_la_betweenness_va_a_la_paralela_rapida_no_a_la_corta():
    """El caminos mínimo por tiempo pasa por la larga-rápida; adjudicar a la corta
    pondría todo el flujo en un tramo por el que ese camino no pasa."""
    arcos = pd.Series({(1, 2): 0.3, (2, 1): 0.2, (2, 3): 0.1})
    salida = centralidad.a_tramos(arcos, _tramos_paralelos(), peso="travel_time")
    salida = salida.set_index("tramo_id")["betweenness"]
    assert salida["1-2-1"] == pytest.approx(0.5)
    assert salida["1-2-0"] == 0.0


def test_con_empate_exacto_gana_el_tramo_id_menor_y_no_el_orden_de_las_filas():
    arcos = pd.Series({(1, 2): 0.4})
    empate = pd.DataFrame({
        "tramo_id": ["1-2-9", "1-2-3"], "u": [1, 1], "v": [2, 2],
        "largo_m": [100.0, 100.0], "travel_time": [9.0, 9.0],
    })
    salida = centralidad.a_tramos(arcos, empate, peso="length").set_index("tramo_id")
    assert salida.loc["1-2-3", "betweenness"] == pytest.approx(0.4)
    assert salida.loc["1-2-9", "betweenness"] == 0.0


def test_a_tramos_exige_la_columna_del_peso_con_el_que_se_calculo():
    arcos = pd.Series({(1, 2): 0.4})
    sin_tiempo = pd.DataFrame({"tramo_id": ["1-2-0"], "u": [1], "v": [2], "largo_m": [100.0]})
    with pytest.raises(ValueError, match="travel_time"):
        centralidad.a_tramos(arcos, sin_tiempo, peso="travel_time")


def test_a_tramos_no_pierde_betweenness():
    arcos = pd.Series({(1, 2): 0.3, (2, 1): 0.2, (2, 3): 0.1})
    tramos = pd.DataFrame({"tramo_id": ["1-2-0", "2-3-0"], "u": [1, 2], "v": [2, 3],
                           "largo_m": [100.0, 50.0], "travel_time": [18.0, 5.0]})
    suma = centralidad.a_tramos(arcos, tramos, peso="length")["betweenness"].sum()
    assert suma == pytest.approx(0.6)


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


# ─── el busway que se mantiene y se declara ───────────────────────────────────
def _tabla_busway() -> tuple[pd.DataFrame, pd.DataFrame]:
    tramos = pd.DataFrame({
        "tramo_id": ["a", "b", "c", "d"],
        "highway": ["busway", "primary", "residential", "residential"],
        "largo_m": [100.0, 300.0, 300.0, 300.0],
    })
    bc = pd.DataFrame({
        "tramo_id": ["a", "b", "c", "d"],
        "bc_length": [0.1, 0.5, 0.3, 0.1],
        "bc_travel_time": [0.4, 0.3, 0.2, 0.1],
    })
    return tramos, bc


def test_resumen_busway_mide_su_peso_en_red_y_en_betweenness():
    r = centralidad.resumen_busway(*_tabla_busway())
    assert r["pct_busway_tramos"] == pytest.approx(25.0)
    assert r["pct_busway_largo"] == pytest.approx(10.0)
    assert r["pct_busway_bc_length"] == pytest.approx(10.0)
    assert r["pct_busway_bc_travel_time"] == pytest.approx(40.0)


def test_resumen_busway_declara_si_encabeza_el_ranking():
    """Lo que hace la limitación reportable: por tiempo el primero es un busway."""
    r = centralidad.resumen_busway(*_tabla_busway())
    assert r["busway_es_primero_travel_time"] is True
    assert r["busway_es_primero_length"] is False


def test_resumen_busway_en_una_red_sin_busway_es_cero():
    tramos, bc = _tabla_busway()
    tramos.loc[0, "highway"] = "service"
    r = centralidad.resumen_busway(tramos, bc)
    assert r["pct_busway_tramos"] == 0.0
    assert r["busway_es_primero_travel_time"] is False
