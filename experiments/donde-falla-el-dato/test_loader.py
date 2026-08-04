"""Tests de `donde-falla-el-dato`.

Los que importan corren **sin datos**: ejercitan `construir` sobre marcos sintéticos,
porque las reglas que este experimento tiene que no romper —preservar las celdas sin
registro, no confundir cero con no-medido, y hacer ganar `sin_auditoria` sobre
`sin_registro`— son lógica, no volumen. Si un refactor las rompe, tiene que fallar en
CI, donde `data/` no existe.

Los marcados ``needs_data`` verifican el artefacto real y se saltan solos cuando falta.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))

import loader  # noqa: E402


# ─── marcos sintéticos ────────────────────────────────────────────────────────
@pytest.fixture
def grilla() -> pd.DataFrame:
    """Cuatro celdas, una por modo de falla: observada, sin registro, sin auditoría,
    sin ubigeo."""
    return pd.DataFrame(
        {
            "h3_index": ["c_obs", "c_sin_reg", "c_sin_aud", "c_sin_ubi"],
            "ubigeo": ["150101", "150101", "070101", pd.NA],
            "distrito": ["Lima", "Lima", "Callao", pd.NA],
            "departamento": ["Lima", "Lima", "Callao", pd.NA],
        }
    )


@pytest.fixture
def obs() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "h3_index": ["c_obs", "c_obs", "c_obs", "c_sin_aud"],
            "ubigeo": ["150101", "150101", "150101", "070101"],
            "year": [2018, 2019, 2019, 2020],
            "crime_cat": ["estafa", "estafa", "extorsion", "estafa"],
            "obs_geo_count": [3, 4, 5, 9],
            "real_coord_ratio": [0.8, 0.8, 0.8, 0.5],
        }
    )


@pytest.fixture
def aud() -> pd.DataFrame:
    """Solo Lima está auditada. Callao no aparece — como en el CSV real."""
    return pd.DataFrame(
        {"ubigeo": ["150101"], "n_geo": [100], "exito_geo": [0.4], "sin_coord": [0.1]}
    )


@pytest.fixture
def tabla(grilla, obs, aud) -> pd.DataFrame:
    return loader.construir(grilla, obs, aud).set_index("h3_index")


# ─── la grilla es el denominador y no se puede perder ─────────────────────────
def test_conserva_toda_la_grilla(tabla, grilla):
    """Filtrar las celdas sin registro haría imposible dibujarlas deshilachadas."""
    assert sorted(tabla.index) == sorted(grilla["h3_index"])


def test_soporte_se_rellena_con_cero_pero_la_calidad_no(tabla):
    """Cero registros ES el dato; calidad no medida NO es calidad cero."""
    assert tabla.loc["c_sin_reg", "soporte_registros"] == 0
    assert pd.isna(tabla.loc["c_sin_aud", "geo_exito_distrito"])
    assert pd.isna(tabla.loc["c_sin_ubi", "geo_exito_distrito"])


def test_soporte_agrega_registros_anios_y_categorias(tabla):
    fila = tabla.loc["c_obs"]
    assert fila["soporte_registros"] == 12
    assert fila["soporte_anios"] == 2
    assert fila["soporte_categorias"] == 2


# ─── la precedencia del motivo es el hallazgo, no un detalle ──────────────────
def test_sin_auditoria_gana_sobre_sin_registro(tabla):
    """`c_sin_aud` TIENE registros; igual no es evaluable, porque no se puede medir
    la calidad geocodificadora de su distrito. No poder medir no es medir mal."""
    assert tabla.loc["c_sin_aud", "tiene_registro"]
    assert tabla.loc["c_sin_aud", "motivo"] == "sin_auditoria"
    assert not tabla.loc["c_sin_aud", "evaluable"]


def test_motivo_por_celda(tabla):
    assert tabla["motivo"].to_dict() == {
        "c_obs": "observado",
        "c_sin_reg": "sin_registro",
        "c_sin_aud": "sin_auditoria",
        "c_sin_ubi": "sin_ubigeo",
    }


def test_evaluable_exige_registro_y_auditoria(tabla):
    assert tabla["evaluable"].to_dict() == {
        "c_obs": True, "c_sin_reg": False, "c_sin_aud": False, "c_sin_ubi": False,
    }


def test_calidad_distrital_se_propaga_a_celdas_sin_registro(tabla):
    """La calidad es una propiedad del distrito: una celda sin denuncias igual hereda
    el techo de confianza del distrito al que pertenece."""
    assert tabla.loc["c_sin_reg", "geo_exito_distrito"] == pytest.approx(0.4)
    assert tabla.loc["c_sin_reg", "geo_con_coord_distrito"] == pytest.approx(0.9)


# ─── las guardas que impiden mentir en silencio ───────────────────────────────
def test_calidad_falla_si_el_ratio_deja_de_ser_distrital(obs, aud):
    """Si `real_coord_ratio` variara dentro de un ubigeo, `first` elegiría un valor al
    azar. Mejor romper que propagar una medida que ya no es lo que dice ser."""
    roto = obs.copy()
    roto.loc[0, "real_coord_ratio"] = 0.1
    with pytest.raises(ValueError, match="constante por ubigeo"):
        loader.calidad_distrital(roto, aud)


def test_grilla_falla_si_las_dos_fuentes_no_coinciden(tmp_path):
    """Un denominador equivocado convierte cada porcentaje en una mentira precisa."""
    admin = tmp_path / "admin.parquet"
    matriz = tmp_path / "matriz.parquet"
    pd.DataFrame(
        {"h3_index": ["a", "b"], "ubigeo": ["1", "1"], "distrito": ["x", "x"],
         "departamento": ["L", "L"]}
    ).to_parquet(admin)
    pd.DataFrame({"h3_index": ["a"]}).to_parquet(matriz)
    with pytest.raises(ValueError, match="no hay grilla canónica"):
        loader.leer_grilla(admin, matriz)


def test_ubigeo_vacio_no_se_une_como_distrito(grilla, obs, aud):
    """El origen usa "" para las celdas que ningún polígono reclama. Un string vacío
    se une silenciosamente en un merge y le regalaría auditoría a quien no la tiene."""
    g = grilla.copy()
    g.loc[3, ["ubigeo", "distrito", "departamento"]] = ""
    a = pd.concat([aud, pd.DataFrame({"ubigeo": [""], "n_geo": [1], "exito_geo": [0.9],
                                      "sin_coord": [0.0]})], ignore_index=True)
    out = loader.construir(g, obs, a).set_index("h3_index")
    assert not out.loc["c_sin_ubi", "tiene_auditoria"]


def test_es_determinista(grilla, obs, aud):
    """Dos corridas sobre los mismos inputs dan la misma tabla, o el hash de
    procedencia del registro no significa nada."""
    a = loader.construir(grilla, obs, aud)
    b = loader.construir(grilla, obs, aud)
    pd.testing.assert_frame_equal(a, b)


# ─── contra el artefacto real ─────────────────────────────────────────────────
@pytest.fixture
def artefacto() -> pd.DataFrame:
    dest = loader.OUT / f"{loader.SLUG}.parquet"
    if not dest.exists():
        pytest.skip(f"falta {dest}; corre el loader")
    return pd.read_parquet(dest)


@pytest.mark.needs_data
def test_artefacto_cubre_la_grilla_entera(artefacto):
    assert len(artefacto) == artefacto["h3_index"].nunique() == 4172


@pytest.mark.needs_data
def test_artefacto_declara_su_unidad(artefacto):
    """Contrato de `design/contrato-unidades.md`: clave declarada, sin geometría."""
    assert artefacto["h3_index"].dtype == "string"
    assert not {"geometry", "lat", "lon"} & set(artefacto.columns)


@pytest.mark.needs_data
def test_la_superficie_latente_vive_exactamente_donde_hay_auditoria(artefacto):
    """El hallazgo que cruza E2 con E1: el mapa corregido está definido justo sobre el
    subconjunto auditable. La corrección no repara el punto ciego, lo hereda — y si
    esta identidad se rompiera, ese argumento dejaría de valer y hay que enterarse."""
    latente = loader.SOURCE / "crime_latent_surface.parquet"
    if not latente.exists():
        pytest.skip(f"falta la fuente {latente}")
    celdas_latente = set(pd.read_parquet(latente, columns=["h3_index"])["h3_index"])
    auditadas = set(artefacto.loc[artefacto["tiene_auditoria"], "h3_index"])
    assert auditadas == celdas_latente
