"""Tests del experimento `observado-latente`.

Dos capas, a propósito. Los tests de lógica corren sobre una superficie sintética
diminuta y no tocan `data/` ni el repo de origen: son los que protegen las reglas duras
(sin datos ≠ cero, el ranking se mide solo donde hay registro). Los marcados
``needs_data`` verifican el artefacto real y solo corren si el loader ya se ejecutó.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "data" / "silver" / "observado-latente"


def _cargar_loader():
    """Importa el loader por ruta: `experiments/` no es un paquete instalable."""
    ruta = ROOT / "experiments" / "observado-latente" / "loader.py"
    spec = importlib.util.spec_from_file_location("observado_latente_loader", ruta)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


loader = _cargar_loader()


@pytest.fixture
def superficie_min() -> pd.DataFrame:
    """Tres celdas: una cargada, una floja, una sin registro alguno.

    `c_mudo` es el caso que el repo entero existe para no confundir: observado 0 no
    porque no pase nada, sino porque nadie denunció.
    """
    filas = []
    casos = (("c_alto", 100.0, 10.0), ("c_bajo", 10.0, 1.0), ("c_mudo", 0.0, 0.0))
    for cel, obs_robo, obs_estafa in casos:
        filas += [
            {
                "h3_index": cel,
                "ubigeo": "150101",
                "year": 2020,
                "crime_cat": "robo_hurto_callejero",
                "observado": obs_robo,
                "latente": obs_robo * 4.0,
                "latente_ic_low": obs_robo * 3.0,
                "latente_ic_high": obs_robo * 6.0,
                "inestable": 0,
            },
            {
                "h3_index": cel,
                "ubigeo": "150101",
                "year": 2020,
                "crime_cat": "estafa",
                "observado": obs_estafa,
                "latente": obs_estafa * 80.0,
                "latente_ic_low": obs_estafa * 20.0,
                "latente_ic_high": obs_estafa * 800.0,
                "inestable": 1,
            },
        ]
    return pd.DataFrame(filas)


# ─── reglas duras ─────────────────────────────────────────────────────────────
def test_sin_registro_no_es_cero_silencioso(superficie_min):
    """Una celda sin denuncias queda marcada, no simplemente en 0.

    Si `sin_registro` no existiera, la capa visual dibujaría `c_mudo` igual que una
    celda de riesgo bajo real — que es exactamente la regla dura 1 violada.
    """
    celdas = loader.por_celda(superficie_min).set_index("h3_index")
    assert bool(celdas.loc["c_mudo", "sin_registro"]) is True
    assert not celdas.loc[["c_alto", "c_bajo"], "sin_registro"].any()
    assert celdas.loc["c_mudo", "observado"] == 0.0


def test_cobertura_viaja_con_el_valor(superficie_min):
    """El contrato de unidades exige cobertura al lado del valor, nunca sin ella."""
    celdas = loader.por_celda(superficie_min)
    for col in ("sin_registro", "ic_ancho_rel", "share_inestable"):
        assert col in celdas.columns


def test_share_inestable_pesa_la_categoria_marcada(superficie_min):
    """La estafa está marcada inestable: debe cargar su parte del latente de la celda."""
    celdas = loader.por_celda(superficie_min).set_index("h3_index")
    # c_alto: latente robo = 400, latente estafa = 800 → 800/1200
    assert celdas.loc["c_alto", "share_inestable"] == pytest.approx(800 / 1200, rel=1e-5)
    # Sin latente no hay proporción que reportar; NaN, no un 0 que mienta.
    assert pd.isna(celdas.loc["c_mudo", "share_inestable"])


def test_ic_ancho_rel_es_nan_sin_latente(superficie_min):
    celdas = loader.por_celda(superficie_min).set_index("h3_index")
    assert pd.isna(celdas.loc["c_mudo", "ic_ancho_rel"])
    assert celdas.loc["c_alto", "ic_ancho_rel"] > 0


def test_rango_ignora_las_celdas_mudas(superficie_min):
    """El Spearman se mide solo donde hay registro.

    Con dos celdas con dato el ρ es 1; incluir `c_mudo` metería un empate que no es
    acuerdo entre superficies sino ausencia de dato en las dos.
    """
    celdas = loader.por_celda(superficie_min)
    r = loader.estabilidad_de_rango(celdas, top_n=2)
    assert r["n_celdas"] == 3
    assert r["n_con_registro"] == 2
    assert r["spearman"] == pytest.approx(1.0)
    assert r["top_overlap"] == pytest.approx(1.0)


def test_composicion_suma_cien(superficie_min):
    comp = loader.composicion(superficie_min)
    assert comp["share_observado"].sum() == pytest.approx(100.0)
    assert comp["share_latente"].sum() == pytest.approx(100.0)
    # La corrección tiene que MOVER la composición: es el segundo hallazgo.
    assert comp.loc["estafa", "share_latente"] > comp.loc["estafa", "share_observado"]


def test_multiplicador_es_pooled_no_promedio_de_celdas(superficie_min):
    """Σλ*/Σy, no la media de los cocientes por celda.

    Promediar cocientes le daría a `c_bajo` el mismo peso que a `c_alto` y el
    multiplicador dejaría de ser el del repo de origen.
    """
    comp = loader.composicion(superficie_min)
    assert comp.loc["robo_hurto_callejero", "multiplicador"] == pytest.approx(4.0)
    assert comp.loc["estafa", "multiplicador"] == pytest.approx(80.0)


def test_categorias_en_orden_fijo(superficie_min):
    """El orden no puede depender del contenido: si no, la composición se reordena sola."""
    comp = loader.composicion(superficie_min)
    assert list(comp.index) == loader.CATEGORIAS


# ─── el artefacto real ────────────────────────────────────────────────────────
def _leer_artefacto(nombre: str) -> pd.DataFrame:
    """Lee un parquet del loader, o salta el test si el loader no corrió.

    `data/` es gitignored: en un worktree limpio no hay artefacto, y eso es ausencia
    de evidencia, no un fallo del experimento. Mismo patrón que `donde-falla-el-dato`
    y `curva-de-evaluabilidad`.
    """
    ruta = ART / nombre
    if not ruta.exists():
        pytest.skip(f"falta {ruta}; corre el loader de observado-latente")
    return pd.read_parquet(ruta)


@pytest.fixture
def celdas() -> pd.DataFrame:
    return _leer_artefacto("celdas.parquet")


@pytest.fixture
def fronteras() -> pd.DataFrame:
    return _leer_artefacto("fronteras.parquet")


@pytest.mark.needs_data
def test_artefactos_existen_y_cuadran(celdas, fronteras):
    assert celdas["h3_index"].is_unique
    assert not celdas["h3_index"].isna().any()
    # Un hexágono H3 tiene 6 vértices y toda celda tiene que tener los suyos.
    assert set(fronteras["h3_index"]) == set(celdas["h3_index"])
    assert (fronteras.groupby("h3_index").size() == 6).all()


@pytest.mark.needs_data
def test_sin_geometria_en_la_tabla_de_features(celdas):
    """`design/contrato-unidades.md`: sin geometría en las tablas de features."""
    prohibidas = {"geometry", "lat", "lng", "lon", "wkt", "poly", "boundary"}
    assert not prohibidas & {c.lower() for c in celdas.columns}


@pytest.mark.needs_data
def test_el_latente_domina_al_observado(celdas):
    """La corrección solo puede sumar: λ* = y / r̂ con r̂ ≤ 1."""
    assert (celdas["latente"] >= celdas["observado"] - 1e-3).all()
    assert (celdas["latente_ic_low"] <= celdas["latente_ic_high"] + 1e-3).all()


@pytest.mark.needs_data
def test_el_hallazgo_sigue_en_pie(celdas):
    """Gate sobre el resultado: si la corrección empezara a reordenar el mapa, el
    experimento entero cuenta otra historia y hay que reescribirlo, no ajustar el test."""
    r = loader.estabilidad_de_rango(celdas)
    assert r["spearman"] > 0.95
    assert r["top_overlap"] > 0.70


@pytest.mark.needs_data
def test_los_multiplicadores_coinciden_con_el_repo_de_origen():
    """Gate anti-drift. Estos valores están publicados en infelix; si el pipeline de
    acá los mueve, se rompió algo — y es justo el fallo que originó el registro."""
    from inwatch import canon

    publicados = {
        "multiplier.robo_hurto_callejero": "4.6",
        "multiplier.extorsion": "6.9",
        "multiplier.secuestro": "8.4",
        "multiplier.violencia_familiar_sexual": "11.1",
        "multiplier.estafa": "76",
    }
    for key, esperado in publicados.items():
        assert canon.display(key) == esperado, f"{key} divergió del valor publicado"
