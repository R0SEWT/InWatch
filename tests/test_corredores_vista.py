"""Tests de la capa de presentación de `corredores-criticos` (bead inwatch-92d.6).

Todo corre **sin datos**: tablas sintéticas de cuatro filas donde el resultado correcto
se sabe a mano. Lo que se verifica es lo que el notebook no puede permitirse romper en
silencio — qué entra al top, qué se dibuja deshilachado y cómo se normaliza el color —
porque un mapa mal filtrado no falla, sale bonito y miente.

**Por qué la lógica vive en `vista.py` y no en el notebook.** El CI corre
`uv sync --extra geo`: no instala `marimo`. Un test que importara `notebook.py` se
saltaría entero allá, y un test que se salta no verifica nada — es peor que uno rojo.
Así que la lógica pura está en un módulo sin marimo, sin matplotlib y sin geopandas, y
el notebook la importa. El chequeo del notebook en sí queda al final del archivo: lo que
se puede leer de su fuente corre siempre, y lo que exige importarlo se salta solo.

Los módulos se cargan por ruta, no por `sys.path`: es el bug `inwatch-0ge`, dos
experimentos con un `loader.py` cada uno chocando bajo el mismo nombre de módulo.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_DIR = Path(__file__).resolve().parents[1] / "experiments" / "corredores-criticos"
_spec = importlib.util.spec_from_file_location("corredores_vista", _DIR / "vista.py")
vista = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vista)


# ─── jerarquía declarada por OSM ──────────────────────────────────────────────
@pytest.mark.parametrize(
    ("highway", "esperada"),
    [
        ("motorway", "arterial"),
        ("trunk_link", "arterial"),
        ("primary", "arterial"),
        ("secondary", "secundaria"),
        ("tertiary_link", "secundaria"),
        ("residential", "local"),
        ("service", "local"),
        ("busway", "busway"),
        ("Primary", "arterial"),
        ("  secondary  ", "secundaria"),
    ],
)
def test_clase_vial_mapea_la_jerarquia_osm(highway, esperada):
    assert vista.clase_vial(highway) == esperada


@pytest.mark.parametrize("vacio", [None, float("nan"), "", "   "])
def test_una_via_sin_highway_no_es_una_via_local(vacio):
    """Regla dura del repo: sin dato ≠ valor bajo. Sin `highway` es su propia clase."""
    assert vista.clase_vial(vacio) == vista.SIN_DECLARAR
    assert vista.clase_vial(vacio) != "local"


def test_clasificar_devuelve_una_clase_por_tramo_y_respeta_el_orden():
    tramos = pd.DataFrame({
        "tramo_id": ["a", "b", "c", "d"],
        "highway": ["primary", "residential", None, "busway"],
    })
    clases = vista.clasificar(tramos)
    assert list(clases) == ["arterial", "local", vista.SIN_DECLARAR, "busway"]
    assert clases.index.equals(tramos.index)


def test_clasificar_falla_si_no_existe_la_columna():
    with pytest.raises(KeyError, match="highway"):
        vista.clasificar(pd.DataFrame({"tramo_id": ["a"]}))


# ─── sin dato ≠ cero ──────────────────────────────────────────────────────────
def test_sin_dato_distingue_el_cero_medido_del_hueco():
    """Un tramo paralelo con betweenness 0 es una medición, no una ausencia.

    `a_tramos` deja en 0 las paralelas que ningún camino mínimo usa: ese 0 es el dato.
    El hueco es el NaN, y solo ese se dibuja deshilachado.
    """
    tabla = pd.DataFrame({"bc_length": [0.0, 0.5, np.nan, 0.0]})
    assert list(vista.sin_dato(tabla, "bc_length")) == [False, False, True, False]


def test_sin_dato_falla_si_no_existe_la_columna():
    with pytest.raises(KeyError, match="bc_length"):
        vista.sin_dato(pd.DataFrame({"x": [1]}), "bc_length")


# ─── el top del ranking ───────────────────────────────────────────────────────
def _tabla_bc() -> pd.DataFrame:
    return pd.DataFrame({
        "tramo_id": ["t4", "t1", "t3", "t2", "t5"],
        "bc_length": [0.1, 0.9, 0.5, 0.5, np.nan],
        "bc_travel_time": [0.9, 0.1, 0.2, 0.3, 0.4],
    })


def test_tabla_top_ordena_desc_y_numera_desde_uno():
    top = vista.tabla_top(_tabla_bc(), columna="bc_length", clave="tramo_id", top=3)
    assert list(top["tramo_id"]) == ["t1", "t2", "t3"]
    assert list(top["rango"]) == [1, 2, 3]


def test_tabla_top_desempata_por_clave_y_no_por_orden_de_filas():
    """t2 y t3 empatan en 0.5; el orden de las filas del artefacto no puede decidir."""
    tabla = _tabla_bc()
    top_a = vista.tabla_top(tabla, columna="bc_length", clave="tramo_id", top=3)
    top_b = vista.tabla_top(
        tabla.iloc[::-1].reset_index(drop=True),
        columna="bc_length", clave="tramo_id", top=3,
    )
    assert list(top_a["tramo_id"]) == list(top_b["tramo_id"])


def test_el_top_cambia_al_cambiar_el_peso():
    """Es el hallazgo del experimento: mover el peso reordena el mapa."""
    por_largo = vista.tabla_top(_tabla_bc(), columna="bc_length", clave="tramo_id", top=2)
    por_tiempo = vista.tabla_top(_tabla_bc(), columna="bc_travel_time", clave="tramo_id", top=2)
    assert list(por_largo["tramo_id"]) != list(por_tiempo["tramo_id"])


def test_tabla_top_deja_fuera_lo_que_no_tiene_dato():
    """Un NaN no es un valor bajo, pero tampoco puede colarse al top por ordenamiento."""
    top = vista.tabla_top(_tabla_bc(), columna="bc_length", clave="tramo_id", top=5)
    assert "t5" not in set(top["tramo_id"])
    assert len(top) == 4


def test_tabla_top_se_recorta_a_las_filas_que_hay():
    """El deslizador puede pedir más de lo que existe; eso no puede reventar la vista."""
    top = vista.tabla_top(_tabla_bc(), columna="bc_length", clave="tramo_id", top=99)
    assert len(top) == 4
    assert list(top["rango"]) == [1, 2, 3, 4]


def test_tabla_top_rechaza_un_top_no_positivo():
    with pytest.raises(ValueError, match="top"):
        vista.tabla_top(_tabla_bc(), columna="bc_length", clave="tramo_id", top=0)


def test_tabla_top_falla_si_no_existe_la_columna_del_peso():
    with pytest.raises(KeyError, match="bc_inventada"):
        vista.tabla_top(_tabla_bc(), columna="bc_inventada", clave="tramo_id", top=2)


# ─── normalización de color ───────────────────────────────────────────────────
def test_normalizar_lleva_el_minimo_a_cero_y_el_maximo_a_uno():
    salida = vista.normalizar(pd.Series([2.0, 4.0, 6.0]))
    assert salida[0] == pytest.approx(0.0)
    assert salida[1] == pytest.approx(0.5)
    assert salida[2] == pytest.approx(1.0)


def test_normalizar_preserva_el_hueco_en_vez_de_pintarlo_de_minimo():
    """Si el NaN saliera 0, el mapa pintaría 'no medido' con el color de 'casi nada'."""
    salida = vista.normalizar(pd.Series([1.0, np.nan, 3.0]))
    assert np.isnan(salida[1])
    assert salida[0] == pytest.approx(0.0)
    assert salida[2] == pytest.approx(1.0)


def test_normalizar_con_rango_degenerado_no_pinta_todo_de_minimo():
    """Todos iguales es 'no hay variación', no 'todos son el mínimo'."""
    salida = vista.normalizar(pd.Series([0.3, 0.3, 0.3]))
    assert np.allclose(salida, 0.5)


def test_normalizar_sin_ningun_valor_finito_devuelve_solo_huecos():
    salida = vista.normalizar(pd.Series([np.nan, np.nan]))
    assert np.isnan(salida).all()


def test_gamma_menor_que_uno_levanta_la_cola_sin_mover_los_extremos():
    """La betweenness es de cola pesada: sin gamma el mapa es negro sobre blanco."""
    valores = pd.Series([0.0, 0.25, 1.0])
    lineal = vista.normalizar(valores)
    comprimida = vista.normalizar(valores, gamma=0.4)
    assert comprimida[0] == pytest.approx(lineal[0])
    assert comprimida[2] == pytest.approx(lineal[2])
    assert comprimida[1] > lineal[1]


def test_normalizar_es_monotono():
    valores = pd.Series([0.0, 0.1, 0.4, 0.4, 2.0])
    salida = vista.normalizar(valores, gamma=0.4)
    assert list(salida) == sorted(salida)


def test_normalizar_rechaza_un_gamma_no_positivo():
    with pytest.raises(ValueError, match="gamma"):
        vista.normalizar(pd.Series([1.0, 2.0]), gamma=0.0)


# ─── barra de escala ──────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("extension_m", "esperada"),
    [
        (12_000.0, 2_000.0),   # 25 % son 3 km → el redondo que entra es 2 km
        (8_000.0, 2_000.0),
        (4_000.0, 1_000.0),
        (1_000.0, 200.0),
        (400.0, 100.0),
        (30.0, 5.0),
    ],
)
def test_longitud_barra_elige_un_redondo_que_entra_en_el_mapa(extension_m, esperada):
    barra = vista.longitud_barra(extension_m)
    assert barra == pytest.approx(esperada)
    assert barra <= 0.25 * extension_m


def test_longitud_barra_rechaza_una_extension_no_positiva():
    with pytest.raises(ValueError, match="extensión"):
        vista.longitud_barra(0.0)


# ─── capas de puntos sobre el top ─────────────────────────────────────────────
def _capas() -> pd.DataFrame:
    return pd.DataFrame({
        "tramo_id": ["t1", "t1", "t3", "t9"],
        "nombre": ["Estación Central", "Nacional", "Matute", "Angamos"],
        "capa": ["estacion", "estadio", "estadio", "estacion"],
        "dist_m": [40.0, 120.0, 80.0, 10.0],
    })


def test_nombres_cercanos_junta_las_capas_de_cada_clave():
    nombres = vista.nombres_cercanos(["t1", "t2", "t3"], _capas(), clave="tramo_id")
    assert nombres["t1"] == "Estación Central · Nacional"
    assert nombres["t3"] == "Matute"


def test_una_clave_sin_capa_cerca_queda_vacia_y_no_hereda_otro_nombre():
    nombres = vista.nombres_cercanos(["t1", "t2"], _capas(), clave="tramo_id")
    assert nombres["t2"] == ""


def test_nombres_cercanos_no_inventa_claves_que_no_se_pidieron():
    nombres = vista.nombres_cercanos(["t1"], _capas(), clave="tramo_id")
    assert set(nombres) == {"t1"}


def test_nombres_cercanos_con_una_tabla_de_capas_vacia():
    vacias = _capas().iloc[:0]
    nombres = vista.nombres_cercanos(["t1", "t2"], vacias, clave="tramo_id")
    assert nombres == {"t1": "", "t2": ""}


def test_cobertura_es_la_fraccion_del_top_con_capa_cerca():
    assert vista.cobertura(["t1", "t2", "t3", "t4"], {"t1", "t3", "t9"}) == pytest.approx(0.5)


def test_cobertura_falla_con_un_top_vacio():
    """Devolver 0 diría 'ninguno tiene capa cerca' cuando no se midió nada."""
    with pytest.raises(ValueError, match="vacío"):
        vista.cobertura([], {"t1"})


# ─── el notebook ──────────────────────────────────────────────────────────────
_NOTEBOOK = _DIR / "notebook.py"


def test_el_notebook_cita_la_limitacion_del_busway_por_clave():
    """La limitación está decidida y registrada: se cita, no se redacta a mano."""
    fuente = _NOTEBOOK.read_text(encoding="utf-8")
    for clave in ("busway_tramos", "busway_largo", "busway_bc_length", "busway_bc_travel_time"):
        assert f'canon.display("corredores.pct.{clave}")' in fuente


def test_el_notebook_saca_todas_sus_cifras_portantes_del_registro():
    """Ninguna `canon.display` puede apuntar fuera de la familia del experimento."""
    fuente = _NOTEBOOK.read_text(encoding="utf-8")
    claves = set(re.findall(r'canon\.display\(\s*"([^"]+)"', fuente))
    assert claves, "el notebook no cita ni una cifra canónica"
    assert all(k.startswith("corredores.") for k in claves), sorted(claves)


def test_el_notebook_no_escribe_nada():
    """`notebook.py` solo lee artefactos y presenta: ni emite al registro ni guarda."""
    fuente = _NOTEBOOK.read_text(encoding="utf-8")
    for prohibido in ("canon.emit", "to_parquet", "red_vial.guardar", "open("):
        assert prohibido not in fuente


def test_el_notebook_no_habla_de_flujo_observado():
    """Prohibición explícita del enunciado: sin aforos, todo es flujo potencial."""
    fuente = _NOTEBOOK.read_text(encoding="utf-8").lower()
    assert "flujo potencial" in fuente
    for prohibido in ("flujo observado", "tránsito observado", "aforo real"):
        assert prohibido not in fuente


def test_el_notebook_es_una_app_marimo_y_no_toca_disco_al_importarse():
    """Se salta donde no hay `viz`; en CI el gate real son los tests de `vista`."""
    marimo = pytest.importorskip("marimo", reason="marimo vive en el extra `viz`")
    spec = importlib.util.spec_from_file_location("corredores_notebook", _NOTEBOOK)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert isinstance(modulo.app, marimo.App)
