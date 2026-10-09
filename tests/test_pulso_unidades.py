"""Tests del hito 2 de `pulso-estadios`: banda de red y celda morfológica.

Todo corre sin datos: la distancia de red, los saltos de adyacencia, los cortes por área
y la correspondencia se ejercitan sobre una grilla de calles y una partición sintéticas.
Lo único que necesita artefactos es la corrida entera, y ésa no se prueba acá.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments/pulso-estadios"


def _cargar(nombre, archivo):
    spec = importlib.util.spec_from_file_location(nombre, _DIR / archivo)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


U = _cargar("pulso_unidades_t", "unidades.py")
L = _cargar("pulso_loader_unidades_t", "loader_unidades.py")


def _grilla(n=5, paso=100.0):
    """Grilla de calles n×n con cuadras de ``paso`` m: nodos y aristas no dirigidas."""
    xy = np.array([[i * paso, j * paso] for j in range(n) for i in range(n)], dtype=float)
    ar = []
    for j in range(n):
        for i in range(n):
            k = j * n + i
            if i + 1 < n:
                ar.append((k, k + 1, paso))
            if j + 1 < n:
                ar.append((k, k + n, paso))
    return xy, ar


# ─── distancia de red ────────────────────────────────────────────────────────
def test_la_distancia_de_red_es_manhattan_en_una_grilla():
    """En una grilla sin diagonales, caminar a la esquina opuesta cuesta |dx| + |dy|."""
    xy, ar = _grilla()
    d = U.distancia_red(xy, ar, np.array([0.0, 0.0]), np.array([[400.0, 400.0]]),
                        radio_fuente=1.0)
    assert d[0] == pytest.approx(800.0)


def test_la_distancia_de_red_nunca_es_menor_que_la_euclidiana():
    xy, ar = _grilla()
    rng = np.random.default_rng(0)
    pts = rng.uniform(0, 400, (200, 2))
    origen = np.array([130.0, 170.0])
    d = U.distancia_red(xy, ar, origen, pts, snap_max=1e9)
    assert np.all(d >= np.hypot(*(pts - origen).T) - 1e-9)


def test_un_punto_lejos_de_la_red_queda_sin_banda_y_no_en_la_mas_cercana():
    """Sin vereda debajo no hay distancia de red: nan, no el nodo más cercano a 1 km."""
    xy, ar = _grilla()
    d = U.distancia_red(xy, ar, np.array([0.0, 0.0]), np.array([[1400.0, 0.0]]),
                        snap_max=150.0)
    assert np.isnan(d[0])


def test_la_red_se_conecta_solo_donde_las_vias_comparten_vertice():
    """Un puente que cruza una calle en el plano no la toca: no hay atajo por el cruce."""
    calle = np.array([[0.0, 0.0], [0.0, 0.002]])          # vertical, lon fija
    puente = np.array([[-0.001, 0.001], [0.001, 0.001]])   # cruza por el medio sin vértice
    xy, ar = U.red_desde_lineas([calle, puente], lambda lo, la: (lo * 1e5, la * 1e5))
    assert len(xy) == 4                                    # cuatro extremos, ningún cruce
    assert len(ar) == 2


def test_dos_vias_que_comparten_un_vertice_quedan_unidas():
    a = np.array([[0.0, 0.0], [0.001, 0.0]])
    b = np.array([[0.001, 0.0], [0.001, 0.001]])
    xy, ar = U.red_desde_lineas([a, b], lambda lo, la: (lo * 1e5, la * 1e5))
    assert len(xy) == 3


# ─── saltos morfológicos ─────────────────────────────────────────────────────
def test_los_saltos_cuentan_la_distancia_en_el_grafo_de_adyacencia():
    ady = U.adyacencia([("a", "b"), ("b", "c"), ("c", "d"), ("a", "e")])
    h = U.saltos(ady, ["a"])
    assert h == {"a": 0, "b": 1, "e": 1, "c": 2, "d": 3}


def test_una_celda_inalcanzable_no_recibe_salto():
    """Queda fuera, no en el anillo más lejano: es masa perdida, no masa lejana."""
    ady = U.adyacencia([("a", "b"), ("x", "y")])
    assert "x" not in U.saltos(ady, ["a"])


def test_la_contiguidad_entre_manzanas_ignora_los_pares_de_la_misma_manzana():
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import box

    celdas = gpd.GeoDataFrame({
        "tess_id": ["a1", "a2", "b1"],
        "manzana": [0, 0, 1],
    }, geometry=[box(0, 0, 10, 10), box(10, 0, 20, 10), box(20, 0, 30, 10)])
    pares = U.contiguidad_entre_manzanas(celdas)
    assert {frozenset(p) for p in pares} == {frozenset(("a2", "b1"))}


# ─── cortes por área ─────────────────────────────────────────────────────────
def test_los_cortes_por_area_reproducen_el_area_objetivo():
    v = np.arange(100, dtype=float)       # 100 piezas de área 1, valor = su índice
    a = np.ones(100)
    t = U.cortes_por_area(v, a, np.array([10.0, 40.0]))
    b = U.banda(v, np.concatenate([[0.0], t]))
    assert (b == 0).sum() == 10 and (b == 1).sum() == 30


def test_los_cortes_por_area_no_parten_un_salto_entero():
    """Con valores discretos, el corte cae entre saltos, nunca dentro de uno."""
    v = np.array([0, 1, 1, 1, 2, 2, 2, 2, 2], dtype=float)
    t = U.cortes_por_area(v, np.ones(len(v)), np.array([3.0]))
    b = U.banda(v, np.concatenate([[0.0], t]))
    assert set(np.unique(v[b == 0])) in ({0.0}, {0.0, 1.0})


def test_la_banda_deja_fuera_lo_que_no_tiene_valor():
    b = U.banda(np.array([np.nan, 50.0, 600.0, 5000.0]), np.array(U.CORTES_M))
    assert b.tolist() == [-1, 0, 1, -1]


# ─── correspondencia y masa ──────────────────────────────────────────────────
def test_la_correspondencia_no_pierde_ni_inventa_masa():
    rng = np.random.default_rng(1)
    et = pd.DataFrame({"anillo": rng.integers(-1, 4, 500),
                       "banda_red": rng.integers(-1, 4, 500)})
    corr = U.correspondencia(et, "anillo", "banda_red", 625.0)
    assert U.desvio_de_masa(corr) == pytest.approx(0.0, abs=1e-12)
    total = corr["area_m2"].sum()
    assert total == pytest.approx((et["anillo"] >= 0).sum() * 625.0)


def test_el_deficit_de_la_correspondencia_no_se_normaliza():
    """La parte de la banda de origen que no cae en ninguna banda de destino queda en −1."""
    et = pd.DataFrame({"anillo": [0, 0, 0, 0], "banda_red": [0, 0, -1, -1]})
    corr = U.correspondencia(et, "anillo", "banda_red", 1.0)
    fuera = corr[corr["banda_destino"] == -1]["frac_origen"].sum()
    assert fuera == pytest.approx(0.5)


def test_desvio_de_masa_falla_sobre_una_tabla_vacia():
    with pytest.raises(ValueError):
        U.desvio_de_masa(pd.DataFrame(columns=["unidad_origen", "banda_origen",
                                               "frac_origen"]))


# ─── estimador pareado y soporte ─────────────────────────────────────────────
def test_el_bootstrap_vectorizado_coincide_con_el_escalar():
    rng = np.random.default_rng(3)
    a = rng.poisson(3, 50).astype(float)
    nc = rng.integers(1, 5, 50).astype(float)
    c = rng.poisson(2 * nc).astype(float)
    idx = rng.integers(0, 50, (20, 50))
    vec = L.mh_rr_boot(a, c, nc, idx)
    esc = [L.mh_rr(a[i], c[i], nc[i]) for i in idx]
    assert np.allclose(vec, esc)


def test_medible_exige_las_dos_nociones_de_soporte_a_la_vez():
    m = L.medible([5, 1, 5, 5], [3, 3, 0, 3], [40, 40, 40, 10])
    assert m.tolist() == [True, False, False, False]


def test_el_piso_de_control_del_loader_es_el_de_la_pieza():
    """Si la pieza sube su piso y el loader no, el hito 2 dibujaría firme lo que el video
    ya declaró sin dato."""
    arbol = ast.parse((_DIR / "pieza/datos.py").read_text(encoding="utf-8"))
    piso = next(n.value.value for n in arbol.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == "PISO_CONTROL" for t in n.targets))
    assert piso == L.PISO_CONTROL


def test_los_cortes_de_la_banda_de_red_son_los_del_anillo():
    assert tuple(L.RING_EDGES) == U.CORTES_M


def test_el_hito_2_no_emite_al_registro():
    """Sus cifras no son portantes todavía (inwatch-ap1 sin adjudicar)."""
    fuente = (_DIR / "loader_unidades.py").read_text(encoding="utf-8")
    llamadas = [n for n in ast.walk(ast.parse(fuente)) if isinstance(n, ast.Call)
                and getattr(n.func, "attr", None) == "emit"]
    assert llamadas == []


def test_la_preparacion_copiada_es_la_del_loader():
    """``_preparar`` es copia del bloque inline de ``construir``: si el loader cambia su
    preparación y ésta no, el anillo del hito 2 deja de ser el del hito 1."""
    fuente = (_DIR / "loader.py").read_text(encoding="utf-8")
    cuerpo = ast.get_source_segment(fuente, next(
        n for n in ast.parse(fuente).body
        if isinstance(n, ast.FunctionDef) and n.name == "construir"))
    copia = (_DIR / "loader_unidades.py").read_text(encoding="utf-8")
    for linea in ("geo = geo[~geo[\"exact_midnight\"]]",
                  "keep = (day >= 0) & (day < N_DAYS)",
                  "if otro != st and np.hypot(*(coords[st] - coords[otro])) < CROSS_CONTAM_M:",
                  "tfrac = day * 24.0 + geo[\"hour\"].to_numpy()"):
        assert linea in cuerpo and linea in copia
