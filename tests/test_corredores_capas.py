"""Tests de las capas complementarias del TP: estaciones, estadios y ranking (92d.4).

El enunciado exige integrar al menos una capa de puntos al grafo. Acá se prueba la
aritmética espacial con geometrías sintéticas en EPSG:32718, sin red y sin datos reales.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("osmnx")
gpd = pytest.importorskip("geopandas")

from shapely.geometry import LineString, Point  # noqa: E402

_MOD = Path(__file__).resolve().parents[1] / "experiments/corredores-criticos/capas.py"
_spec = importlib.util.spec_from_file_location("corredores_capas", _MOD)
capas = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(capas)

CRS = "EPSG:32718"


def _intersecciones() -> gpd.GeoDataFrame:
    """Cuatro intersecciones sobre el eje x, cada 100 m."""
    return gpd.GeoDataFrame(
        {"node_id": ["n0", "n1", "n2", "n3"]},
        geometry=[Point(x, 0.0) for x in (0.0, 100.0, 200.0, 300.0)],
        crs=CRS,
    )


def _tramos() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"tramo_id": ["n0-n1-0", "n1-n2-0", "n2-n3-0"], "u": ["n0", "n1", "n2"],
         "v": ["n1", "n2", "n3"]},
        geometry=[LineString([(a, 0.0), (a + 100.0, 0.0)]) for a in (0.0, 100.0, 200.0)],
        crs=CRS,
    )


def _puntos() -> gpd.GeoDataFrame:
    """Una estación a 10 m de n1 y un estadio a 40 m de n3."""
    return gpd.GeoDataFrame(
        {"nombre": ["Estación A", "Estadio B"], "capa": ["estacion", "estadio"]},
        geometry=[Point(100.0, 10.0), Point(300.0, 40.0)],
        crs=CRS,
    )


# ─── asignación al grafo ──────────────────────────────────────────────────────
def test_cada_punto_se_asocia_a_su_interseccion_mas_cercana_con_la_distancia():
    a = capas.asignar_mas_cercana(_puntos(), _intersecciones()).set_index("nombre")
    assert a.loc["Estación A", "node_id"] == "n1"
    assert a.loc["Estación A", "dist_m"] == pytest.approx(10.0)
    assert a.loc["Estadio B", "node_id"] == "n3"
    assert a.loc["Estadio B", "dist_m"] == pytest.approx(40.0)


def test_la_asignacion_marca_los_puntos_lejanos_en_vez_de_esconderlos():
    """Un punto fuera del área no debe colgarse de la intersección del borde en silencio."""
    lejos = gpd.GeoDataFrame({"nombre": ["Lejana"], "capa": ["estacion"]},
                             geometry=[Point(0.0, 5_000.0)], crs=CRS)
    a = capas.asignar_mas_cercana(lejos, _intersecciones(), dist_maxima_m=500.0)
    assert bool(a.loc[0, "fuera_de_rango"]) is True
    assert a.loc[0, "dist_m"] == pytest.approx(5_000.0)


def test_los_tramos_dentro_del_radio_salen_con_su_distancia():
    cerca = capas.tramos_cercanos(_puntos(), _tramos(), radio_m=50.0)
    de_a = set(cerca[cerca["nombre"] == "Estación A"]["tramo_id"])
    assert de_a == {"n0-n1-0", "n1-n2-0"}
    assert set(cerca[cerca["nombre"] == "Estadio B"]["tramo_id"]) == {"n2-n3-0"}


def test_el_radio_se_respeta_y_no_hay_tramos_fuera():
    cerca = capas.tramos_cercanos(_puntos(), _tramos(), radio_m=5.0)
    assert cerca.empty


# ─── ranking ──────────────────────────────────────────────────────────────────
def _bc() -> pd.DataFrame:
    return pd.DataFrame({
        "node_id": ["n0", "n1", "n2", "n3"],
        "bc_length": [0.10, 0.40, 0.30, 0.05],
        "bc_travel_time": [0.05, 0.20, 0.50, 0.10],
    })


def test_el_ranking_ordena_y_numera_desde_uno():
    r = capas.ranking(_bc(), "bc_length", clave="node_id", top=3)
    assert list(r["node_id"]) == ["n1", "n2", "n0"]
    assert list(r["rango"]) == [1, 2, 3]


def test_el_ranking_desempata_por_clave_para_ser_determinista():
    empate = pd.DataFrame({"node_id": ["b", "a"], "bc_length": [0.5, 0.5]})
    assert list(capas.ranking(empate, "bc_length", clave="node_id", top=2)["node_id"]) == ["a", "b"]


def test_el_ranking_rechaza_un_top_mayor_que_la_tabla():
    with pytest.raises(ValueError, match="top"):
        capas.ranking(_bc(), "bc_length", clave="node_id", top=99)


# ─── nodos contra aristas, y cercanía a las capas ─────────────────────────────
def test_cobertura_mide_que_parte_del_top_esta_cerca_de_una_capa():
    assert capas.cobertura(["n1", "n2", "n0"], {"n1", "n3"}) == pytest.approx(1 / 3)
    assert capas.cobertura(["n1"], set()) == 0.0


def test_cobertura_falla_con_un_top_vacio():
    """Dividir entre cero daría 0 %, que se leería como 'no hay cobertura'."""
    with pytest.raises(ValueError, match="vac"):
        capas.cobertura([], {"n1"})


def test_los_tramos_del_top_entre_intersecciones_del_top():
    """El contraste nodo-arista: ¿el corredor une hubs, o los puentea?"""
    frac = capas.tramos_entre_top(["n1-n2-0", "n2-n3-0"], {"n1", "n2"}, _tramos())
    assert frac == pytest.approx(0.5)


def test_los_tramos_del_top_exigen_existir_en_la_tabla_de_tramos():
    with pytest.raises(ValueError, match="no existe"):
        capas.tramos_entre_top(["inventado"], {"n1"}, _tramos())
