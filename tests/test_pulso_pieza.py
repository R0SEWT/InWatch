"""Tests de la cámara de la pieza de `pulso-estadios`.

Sin marcador `needs_data` a propósito: `camara.py` es aritmética pura —la interpolación
de van Wijk & Nuij (2003)— así que el CI, que excluye los tests con datos, acá sí verifica
algo. El resto de la pieza (hornear el suelo, leer el perfil, capturar frames) necesita el
parquet, el gpkg de OSM y un navegador, y no tiene sentido pedirle eso al CI.

El test de ida y vuelta del mercator es una **regresión de un fallo real**: la inversa
llevaba un factor 4π en vez de 2π, la cámara apuntaba once grados al sur del destino y el
mapa salía vacío. Es el tipo de error que no rompe nada, no lanza excepción y solo se ve
mirando el render.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CAMARA = RAIZ / "experiments" / "pulso-estadios" / "pieza" / "camara.py"

# Matute y el Estadio Nacional: 1,2 km, el salto más corto del recorrido y el que destapó
# la necesidad de un piso de duración.
MATUTE = {"lat": -12.06850, "lng": -77.02293, "zoom": 12.30, "pitch": 46, "bearing": -26}
NACIONAL = {"lat": -12.06707, "lng": -77.03386, "zoom": 12.30, "pitch": 46, "bearing": -19}
MONUMENTAL = {"lat": -12.05565, "lng": -76.93533, "zoom": 12.30, "pitch": 46, "bearing": -12}
PANORAMICA = {"lat": -12.06, "lng": -76.98, "zoom": 11.15, "pitch": 44, "bearing": -20}


@pytest.fixture(scope="module")
def camara():
    """Carga el módulo bajo un nombre único, no como `import camara`.

    Con `--import-mode=importlib` y varios experimentos que nombran igual sus archivos,
    un `import` desnudo elige el del vecino sin avisar.
    """
    spec = importlib.util.spec_from_file_location("pulso_pieza_camara", CAMARA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.mark.parametrize(
    ("lat", "lng"),
    [(-12.06850, -77.02293), (-12.05565, -76.93533), (0.0, 0.0), (51.5, -0.12), (-33.4, 18.4)],
)
def test_mercator_ida_y_vuelta_devuelve_el_mismo_punto(camara, lat, lng):
    """Regresión: con el factor 4π la inversa se iba once grados al sur."""
    lat2, lng2 = camara.inv_mercator(*camara.mercator(lat, lng))
    assert lat2 == pytest.approx(lat, abs=1e-9)
    assert lng2 == pytest.approx(lng, abs=1e-9)


def test_el_vuelo_arranca_en_el_origen_y_no_emite_el_destino(camara):
    """El destino lo pone la parada, no el vuelo: emitirlo dos veces congela un frame."""
    vuelo = camara.volar(MATUTE, NACIONAL, 12, 1.35)
    assert vuelo[0]["lat"] == pytest.approx(MATUTE["lat"], abs=1e-7)
    assert vuelo[0]["lng"] == pytest.approx(MATUTE["lng"], abs=1e-7)
    assert vuelo[0]["zoom"] == pytest.approx(MATUTE["zoom"], abs=1e-9)
    # El último frame está cerca del destino pero no es el destino.
    assert vuelo[-1]["lat"] != pytest.approx(NACIONAL["lat"], abs=1e-9)
    assert abs(vuelo[-1]["lat"] - NACIONAL["lat"]) < 1e-3


def test_un_salto_corto_recibe_el_piso_de_duracion(camara):
    """Sin piso, 1,2 km dan cuatro frames y el vuelo se siente como un corte.

    En el recorrido de la pieza el piso gobierna TRES de los cuatro vuelos: solo el salto
    del Nacional al Monumental —unos 9,5 km— dura más por su propio camino. O sea que
    `seg_por_unidad` casi no interviene, y bajar el piso acorta la pieza de verdad.
    """
    fps, minimo = 12, 1.3
    corto = camara.volar(MATUTE, NACIONAL, fps, 1.35, minimo_seg=minimo)
    assert len(corto) == round(minimo * fps)
    # El piso no recorta el vuelo que ya dura más por su camino.
    largo = camara.volar(NACIONAL, MONUMENTAL, fps, 1.35, minimo_seg=minimo)
    assert len(largo) > len(corto)
    # Y un vuelo intermedio también cae al piso: es el caso que confundió al primer test.
    intermedio = camara.volar(PANORAMICA, MATUTE, fps, 1.35, minimo_seg=minimo)
    assert len(intermedio) == round(minimo * fps)


def test_pitch_y_bearing_interpolan_de_forma_monotona(camara):
    vuelo = camara.volar(MATUTE, NACIONAL, 12, 1.35)
    bearings = [v["bearing"] for v in vuelo]
    assert bearings[0] == pytest.approx(MATUTE["bearing"])
    assert bearings == sorted(bearings)          # −26 → −19: crece
    assert max(bearings) < NACIONAL["bearing"]   # nunca pasa del destino
    assert all(v["pitch"] == pytest.approx(MATUTE["pitch"]) for v in vuelo)


def test_un_movimiento_de_zoom_puro_no_mueve_el_centro(camara):
    """La rama de distancia nula: si no hay traslación, solo cambia la escala."""
    destino = dict(MATUTE, zoom=MATUTE["zoom"] + 1.5)
    vuelo = camara.volar(MATUTE, destino, 12, 1.35)
    assert all(v["lat"] == pytest.approx(MATUTE["lat"], abs=1e-9) for v in vuelo)
    assert all(v["lng"] == pytest.approx(MATUTE["lng"], abs=1e-9) for v in vuelo)
    zooms = [v["zoom"] for v in vuelo]
    assert zooms == sorted(zooms)
    assert zooms[0] == pytest.approx(MATUTE["zoom"], abs=1e-9)


def test_el_camino_arquea_el_zoom_hacia_afuera(camara):
    """Lo que van Wijk hace y una interpolación lineal no: alejarse para viajar.

    Entre dos vistas al mismo zoom, el punto medio del camino tiene que estar MÁS lejos
    —zoom menor— que los extremos. Si alguien reemplaza esto por un lerp, este test cae.
    """
    vuelo = camara.volar(PANORAMICA, dict(MATUTE, zoom=PANORAMICA["zoom"]), 12, 1.35)
    medio = vuelo[len(vuelo) // 2]["zoom"]
    assert medio < PANORAMICA["zoom"]


def test_van_wijk_devuelve_una_longitud_de_camino_positiva(camara):
    S, f = camara.van_wijk(PANORAMICA, MATUTE)
    assert S > 0
    assert math.isfinite(S)
    x0, y0, w0 = f(0.0)
    assert (x0, y0) == pytest.approx(camara.mercator(PANORAMICA["lat"], PANORAMICA["lng"]))
    assert w0 == pytest.approx(1.0 / 2 ** PANORAMICA["zoom"])
