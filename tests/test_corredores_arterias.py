"""Tests del contraste betweenness ↔ jerarquía OSM (TP, bead inwatch-92d.5).

Todas las tablas son sintéticas y de pocas filas: la precisión@k, la tasa base y el
lift se calculan a mano, así que los tests verifican la cifra y no solo que el código
corra. Ninguno toca ``data/`` ni la red.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_MOD = Path(__file__).resolve().parents[1] / "experiments/corredores-criticos/arterias.py"
_spec = importlib.util.spec_from_file_location("corredores_arterias", _MOD)
arterias = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(arterias)


# ─── clasificación por jerarquía OSM ──────────────────────────────────────────
def test_clasificar_reparte_las_bandas_declaradas_por_osm():
    """motorway/trunk/primary y sus _link son arteriales; secondary es la intermedia."""
    t = pd.DataFrame({"highway": [
        "motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link",
        "secondary", "secondary_link", "residential", "tertiary",
    ]})
    c = arterias.clasificar(t)
    assert list(c["clase"]) == (
        ["arterial"] * 6 + ["intermedia"] * 2 + ["local"] * 2
    )
    assert list(c["arterial"]) == [True] * 6 + [False] * 4


def test_clasificar_aisla_el_busway_en_vez_de_diluirlo_entre_las_locales():
    """El corredor del Metropolitano no es una calle local: es una limitación declarada."""
    c = arterias.clasificar(pd.DataFrame({"highway": ["busway", "residential"]}))
    assert list(c["clase"]) == ["busway", "local"]
    assert not c["arterial"].any()


def test_clasificar_no_confunde_un_highway_ausente_con_una_via_local():
    c = arterias.clasificar(pd.DataFrame({"highway": [None, "", "primary"]}))
    assert list(c["clase"]) == ["sin_dato", "sin_dato", "arterial"]


def test_clasificar_toma_el_primer_tipo_cuando_osm_deja_una_lista():
    """osmnx deja listas al fusionar segmentos con atributos distintos."""
    c = arterias.clasificar(pd.DataFrame({"highway": [["primary", "secondary"], ["service"]]}))
    assert list(c["clase"]) == ["arterial", "local"]


def test_clasificar_exige_la_columna_highway():
    with pytest.raises(ValueError, match="highway"):
        arterias.clasificar(pd.DataFrame({"tramo_id": ["a"]}))


# ─── tasa base ────────────────────────────────────────────────────────────────
def test_tasa_base_se_mide_por_tramos_y_por_longitud():
    """Una arterial es más larga que un pasaje: el % de tramos y el % de km no coinciden."""
    t = arterias.clasificar(pd.DataFrame({
        "highway": ["primary", "residential", "residential", "residential"],
        "largo_m": [700.0, 100.0, 100.0, 100.0],
    }))
    base = arterias.tasa_base(t)
    assert base["n_tramos"] == 4
    assert base["n_arteriales"] == 1
    assert base["pct_tramos"] == pytest.approx(25.0)
    assert base["pct_largo"] == pytest.approx(70.0)


def test_tasa_base_exige_la_longitud_en_vez_de_inventar_un_denominador():
    t = arterias.clasificar(pd.DataFrame({"highway": ["primary"]}))
    with pytest.raises(ValueError, match="largo_m"):
        arterias.tasa_base(t)


# ─── orden y percentil ────────────────────────────────────────────────────────
def _tabla(highways: list[str], bc_length: list[float], bc_tt: list[float] | None = None):
    """Tabla de tramos clasificada, con un tramo_id legible y todos del mismo largo."""
    n = len(highways)
    return arterias.clasificar(pd.DataFrame({
        "tramo_id": [f"t{i}" for i in range(n)],
        "name": [f"Vía {i}" for i in range(n)],
        "highway": highways,
        "largo_m": [100.0] * n,
        "bc_length": bc_length,
        "bc_travel_time": bc_tt if bc_tt is not None else bc_length,
    }))


def test_ordenar_pone_primero_la_betweenness_mas_alta_y_le_da_el_percentil_100():
    t = _tabla(["primary"] * 4, [0.1, 0.4, 0.2, 0.3])
    o = arterias.ordenar(t, peso="length")
    assert list(o["tramo_id"]) == ["t1", "t3", "t2", "t0"]
    assert list(o["rango"]) == [1, 2, 3, 4]
    assert list(o["percentil_bc"]) == [100.0, 75.0, 50.0, 25.0]


def test_ordenar_empata_el_rango_y_desempata_la_fila_por_tramo_id():
    """El rango empatado es honesto; el orden de filas tiene que ser reproducible igual."""
    t = _tabla(["primary"] * 3, [0.5, 0.5, 0.1])
    o = arterias.ordenar(t.iloc[::-1], peso="length")
    assert list(o["tramo_id"]) == ["t0", "t1", "t2"]
    assert list(o["rango"]) == [1, 1, 3]


def test_ordenar_rechaza_un_peso_que_no_esta_en_la_tabla():
    with pytest.raises(ValueError, match="bc_inventado"):
        arterias.ordenar(_tabla(["primary"], [0.1]), peso="inventado")


# ─── precisión@k, tasa base y lift ────────────────────────────────────────────
def test_precision_en_k_cuenta_arteriales_declaradas_y_nada_mas():
    """La banda intermedia y el busway no son arteriales declaradas: no suman."""
    t = _tabla(["primary", "secondary", "busway", "residential"], [0.4, 0.3, 0.2, 0.1])
    r = arterias.precision_en_k(t, peso="length", k=3)
    assert r["n_arteriales"] == 1
    assert r["precision"] == pytest.approx(100 / 3)


def test_precision_en_k_lleva_la_tasa_base_y_el_lift_pegados_a_la_cifra():
    """3 de 10 tramos son arteriales; el top-2 es todo arterial: lift 100/30."""
    t = _tabla(["primary", "primary"] + ["residential"] * 7 + ["trunk"],
               [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1])
    r = arterias.precision_en_k(t, peso="length", k=2)
    assert r["precision"] == pytest.approx(100.0)
    assert r["tasa_base"] == pytest.approx(30.0)
    assert r["exceso_pp"] == pytest.approx(70.0)
    assert r["lift"] == pytest.approx(100 / 30)


def test_el_lift_vale_uno_cuando_el_top_es_indistinguible_de_la_red():
    t = _tabla(["primary"] + ["residential"] * 4, [0.5, 0.4, 0.3, 0.2, 0.1])
    r = arterias.precision_en_k(t, peso="length", k=5)
    assert r["precision"] == pytest.approx(r["tasa_base"])
    assert r["lift"] == pytest.approx(1.0)
    assert r["exceso_pp"] == pytest.approx(0.0)


def test_el_lift_no_se_inventa_si_la_red_no_tiene_ni_una_arterial():
    r = arterias.precision_en_k(_tabla(["residential"] * 3, [0.3, 0.2, 0.1]),
                                peso="length", k=2)
    assert r["precision"] == 0.0
    assert pd.isna(r["lift"])


def test_precision_en_k_rechaza_un_k_fuera_de_la_red():
    t = _tabla(["primary"] * 3, [0.3, 0.2, 0.1])
    with pytest.raises(ValueError, match="k"):
        arterias.precision_en_k(t, peso="length", k=4)
    with pytest.raises(ValueError, match="k"):
        arterias.precision_en_k(t, peso="length", k=0)


# ─── curva de coincidencia ────────────────────────────────────────────────────
def test_la_curva_recorre_los_k_para_cada_peso():
    t = _tabla(["primary", "primary"] + ["residential"] * 7 + ["trunk"],
               [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1],
               [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0])
    curva = arterias.curva_coincidencia(t, ks=(2, 5, 10))
    assert list(curva.columns) == ["peso", "k", "n_arteriales", "precision",
                                   "tasa_base", "exceso_pp", "lift"]
    por_length = curva[curva["peso"] == "length"].set_index("k")["precision"]
    assert por_length.loc[2] == pytest.approx(100.0)
    assert por_length.loc[5] == pytest.approx(40.0)
    assert por_length.loc[10] == pytest.approx(30.0)
    # Por tiempo el orden está invertido: el top-2 no tiene ninguna arterial.
    por_tiempo = curva[curva["peso"] == "travel_time"].set_index("k")["precision"]
    assert por_tiempo.loc[2] == pytest.approx(50.0)


def test_la_curva_recorta_los_k_que_no_caben_en_la_red():
    curva = arterias.curva_coincidencia(_tabla(["primary"] * 3, [0.3, 0.2, 0.1]),
                                        ks=(2, 50, 1000))
    assert list(curva["k"].unique()) == [2]


def test_la_curva_falla_si_ningun_k_cabe_en_la_red():
    with pytest.raises(ValueError, match="k"):
        arterias.curva_coincidencia(_tabla(["primary"], [0.1]), ks=(50,))


def test_la_curva_no_depende_del_orden_de_las_filas_de_entrada():
    t = _tabla(["primary", "residential", "trunk", "service"], [0.1, 0.4, 0.2, 0.3])
    pd.testing.assert_frame_equal(
        arterias.curva_coincidencia(t, ks=(2, 4)),
        arterias.curva_coincidencia(t.sample(frac=1, random_state=3), ks=(2, 4)),
    )


# ─── desacuerdo 1: corredores de hecho que la clasificación no reconoce ───────
def test_corredores_no_declarados_lista_los_no_arteriales_del_top_en_orden():
    t = _tabla(["residential", "primary", "secondary", "primary", "service"],
               [0.5, 0.4, 0.3, 0.2, 0.1])
    d = arterias.corredores_no_declarados(t, peso="length", k=3)
    assert list(d["tramo_id"]) == ["t0", "t2"]
    assert list(d["clase"]) == ["local", "intermedia"]
    assert list(d["rango"]) == [1, 3]
    assert list(d.columns) == ["peso", "tramo_id", "name", "highway", "clase",
                               "bc", "percentil_bc", "rango"]
    assert set(d["peso"]) == {"length"}


def test_corredores_no_declarados_muestra_el_busway_con_su_propia_clase():
    """Si el Metropolitano encabeza el top, tiene que verse como lo que es."""
    t = _tabla(["busway", "primary", "residential"], [0.9, 0.5, 0.1])
    d = arterias.corredores_no_declarados(t, peso="length", k=2)
    assert list(d["clase"]) == ["busway"]


# ─── desacuerdo 2: arterias declaradas con betweenness baja ───────────────────
def test_arterias_de_baja_betweenness_solo_mira_las_declaradas():
    t = _tabla(["primary", "residential", "trunk", "service"], [0.9, 0.1, 0.2, 0.3])
    d = arterias.arterias_de_baja_betweenness(t, peso="length", percentil_maximo=50.0)
    assert list(d["tramo_id"]) == ["t2"]
    assert d["percentil_bc"].iloc[0] == pytest.approx(50.0)


def test_arterias_de_baja_betweenness_ordena_de_la_peor_hacia_arriba():
    t = _tabla(["primary"] * 4, [0.4, 0.1, 0.3, 0.2])
    d = arterias.arterias_de_baja_betweenness(t, peso="length", percentil_maximo=75.0)
    assert list(d["tramo_id"]) == ["t1", "t3", "t2"]


# ─── el busway, tratado aparte y no diluido ───────────────────────────────────
def test_resumen_busway_dice_cuantos_hay_cuantos_estan_arriba_y_si_encabeza():
    t = _tabla(["busway", "primary", "busway", "residential"], [0.9, 0.5, 0.4, 0.1])
    r = arterias.resumen_busway(t, peso="length", k=2)
    assert r == {"peso": "length", "k": 2, "n_busway": 2, "n_en_top": 1, "encabeza": True}


def test_resumen_busway_no_afirma_que_encabeza_cuando_no_lo_hace():
    t = _tabla(["primary", "busway"], [0.9, 0.5])
    assert arterias.resumen_busway(t, peso="length", k=2)["encabeza"] is False


def test_resumen_busway_funciona_en_una_red_sin_busway():
    t = _tabla(["primary", "residential"], [0.9, 0.5])
    r = arterias.resumen_busway(t, peso="length", k=2)
    assert r["n_busway"] == 0 and r["n_en_top"] == 0 and r["encabeza"] is False


# ─── las cifras que main() emitirá ────────────────────────────────────────────
def _red_sintetica():
    """10 tramos: 3 arteriales declaradas, un busway y seis locales."""
    return _tabla(
        ["primary", "busway", "residential", "trunk", "service", "residential",
         "motorway_link", "residential", "service", "secondary"],
        [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1],
        [0.1, 1.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9],
    )


def test_las_cifras_solo_usan_familias_con_policy_en_el_registro():
    """`corredores.pct.*` (1 decimal) y `corredores.conteo.*` (0). Nada más."""
    claves = arterias.cifras(_red_sintetica(), k=5)
    assert claves, "cifras() no emitiría nada"
    for clave in claves:
        assert clave.startswith(("corredores.pct.", "corredores.conteo."))


def test_las_cifras_de_conteo_son_enteras_y_las_de_pct_son_porcentajes():
    for clave, (valor, _, _) in arterias.cifras(_red_sintetica(), k=5).items():
        if clave.startswith("corredores.conteo."):
            assert float(valor).is_integer(), clave
        else:
            assert -100.0 <= float(valor) <= 100.0, clave


def test_las_cifras_dicen_en_la_clave_con_que_k_y_con_que_peso_se_midieron():
    claves = set(arterias.cifras(_red_sintetica(), k=5))
    for peso in ("length", "travel_time"):
        assert f"corredores.pct.precision_top5_{peso}" in claves
        assert f"corredores.conteo.busway_en_top5_{peso}" in claves


def test_las_cifras_llevan_la_tasa_base_junto_a_cada_precision():
    c = arterias.cifras(_red_sintetica(), k=5)
    assert c["corredores.pct.arterial_declarada_tramos"][0] == pytest.approx(30.0)
    assert c["corredores.pct.arterial_declarada_largo"][0] == pytest.approx(30.0)
    # Top-5 por longitud: primary, busway, residential, trunk, service → 2 de 5.
    assert c["corredores.pct.precision_top5_length"][0] == pytest.approx(40.0)
    assert c["corredores.pct.exceso_sobre_base_top5_length"][0] == pytest.approx(10.0)
    # Por tiempo el orden se invierte: solo el motorway_link sobrevive en el top-5.
    assert c["corredores.pct.precision_top5_travel_time"][0] == pytest.approx(20.0)
    assert c["corredores.pct.exceso_sobre_base_top5_travel_time"][0] == pytest.approx(-10.0)


def test_las_cifras_miden_tambien_las_arterias_que_quedan_abajo():
    """Segundo desacuerdo: de 3 arteriales, 1 está bajo la mediana por longitud y 2 por tiempo."""
    c = arterias.cifras(_red_sintetica(), k=5)
    assert c["corredores.conteo.arterias_declaradas"][0] == 3
    assert c["corredores.pct.arterias_bajo_mediana_length"][0] == pytest.approx(100 / 3)
    assert c["corredores.pct.arterias_bajo_mediana_travel_time"][0] == pytest.approx(200 / 3)


def test_las_cifras_cuentan_el_busway_del_top_en_vez_de_esconderlo():
    c = arterias.cifras(_red_sintetica(), k=5)
    assert c["corredores.conteo.busway_en_top5_length"][0] == 1
    assert c["corredores.conteo.busway_en_top5_travel_time"][0] == 1


# ─── la unión que main() hace antes de medir ──────────────────────────────────
def _tramos_osm():
    return pd.DataFrame({
        "tramo_id": ["a", "b"],
        "highway": ["primary", "residential"],
        "largo_m": [500.0, 80.0],
        "name": ["Av. Grau", None],
        "oneway": [True, False],
    })


def test_unir_junta_los_atributos_de_osm_con_las_dos_betweenness():
    bc = pd.DataFrame({"tramo_id": ["b", "a"], "bc_length": [0.1, 0.4],
                       "bc_travel_time": [0.2, 0.3], "rango_length": [2, 1]})
    u = arterias.unir(_tramos_osm(), bc)
    assert list(u["tramo_id"]) == ["a", "b"]
    assert list(u["bc_length"]) == [0.4, 0.1]
    assert list(u["clase"]) == ["arterial", "local"]
    assert "rango_length" not in u, "el rango se recalcula acá, no se hereda"


def test_unir_no_deja_pasar_un_tramo_sin_betweenness():
    """Un NaN silencioso mandaría un corredor real al fondo del ranking."""
    bc = pd.DataFrame({"tramo_id": ["a"], "bc_length": [0.4], "bc_travel_time": [0.3]})
    with pytest.raises(ValueError, match="sin betweenness"):
        arterias.unir(_tramos_osm(), bc)


def test_unir_deja_la_geometria_fuera_aunque_le_entre_un_geodataframe():
    """El contrato de unidades prohíbe geometría en las tablas de features."""
    gpd = pytest.importorskip("geopandas")
    shapely = pytest.importorskip("shapely")
    t = gpd.GeoDataFrame(
        _tramos_osm(),
        geometry=[shapely.LineString([(0, 0), (1, 1)]) for _ in range(2)],
        crs="EPSG:32718",
    )
    bc = pd.DataFrame({"tramo_id": ["a", "b"], "bc_length": [0.4, 0.1],
                       "bc_travel_time": [0.3, 0.2]})
    u = arterias.unir(t, bc)
    assert "geometry" not in u
    assert not isinstance(u, gpd.GeoDataFrame)


def test_unir_exige_las_dos_columnas_de_peso():
    bc = pd.DataFrame({"tramo_id": ["a", "b"], "bc_length": [0.4, 0.1]})
    with pytest.raises(ValueError, match="bc_travel_time"):
        arterias.unir(_tramos_osm(), bc)


def test_la_tabla_por_tramo_lleva_rango_y_percentil_de_cada_peso_sin_geometria():
    t = _tabla(["primary", "residential", "busway", "service"],
               [0.4, 0.3, 0.2, 0.1], [0.1, 0.2, 0.3, 0.4])
    tabla = arterias.tabla_por_tramo(t)
    assert list(tabla.columns) == [
        "tramo_id", "name", "highway", "clase", "arterial", "largo_m",
        "bc_length", "rango_length", "percentil_length",
        "bc_travel_time", "rango_travel_time", "percentil_travel_time",
    ]
    fila = tabla.set_index("tramo_id").loc["t0"]
    assert fila["rango_length"] == 1 and fila["percentil_length"] == pytest.approx(100.0)
    assert fila["rango_travel_time"] == 4 and fila["percentil_travel_time"] == pytest.approx(25.0)


def test_la_tabla_por_tramo_sale_ordenada_y_sin_perder_tramos():
    t = _tabla(["primary"] * 3, [0.1, 0.3, 0.2])
    tabla = arterias.tabla_por_tramo(t)
    assert list(tabla["tramo_id"]) == ["t1", "t2", "t0"]
    assert len(tabla) == 3


def test_los_artefactos_que_main_escribe_sobreviven_un_viaje_a_parquet(tmp_path):
    """Sin correr main(): se arman sus cuatro tablas y se comprueba que son escribibles."""
    t = _red_sintetica()
    tablas = {
        "clasificacion": arterias.tabla_por_tramo(t),
        "curva": arterias.curva_coincidencia(t, ks=(5, 10)),
        "no_declarados": pd.concat(
            [arterias.corredores_no_declarados(t, peso=p, k=5) for p in arterias.PESOS],
            ignore_index=True),
        "baja_betweenness": pd.concat(
            [arterias.arterias_de_baja_betweenness(t, peso=p) for p in arterias.PESOS],
            ignore_index=True),
    }
    assert set(tablas) == set(arterias.ARTEFACTOS), "main() escribiría una tabla sin nombre"
    for nombre, tabla in tablas.items():
        ruta = tmp_path / arterias.ARTEFACTOS[nombre]
        tabla.to_parquet(ruta, index=False)
        pd.testing.assert_frame_equal(pd.read_parquet(ruta), tabla)


def test_cada_cifra_llega_con_su_unidad_y_su_estimador():
    for clave, (_, unidad, estimador) in arterias.cifras(_red_sintetica(), k=5).items():
        assert unidad and estimador, clave
