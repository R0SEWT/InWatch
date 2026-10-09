"""Tests del experimento `denominador` (E7).

Los tests de lógica corren sobre celdas sintéticas y protegen tres cosas: que dividir
entre cero no fabrique riesgo (sin datos ≠ seguro), que todas las comparaciones usen la
misma población de celdas, y que el detector de circularidad detecte el reparto por
población. Los marcados ``needs_data`` verifican los artefactos reales.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "data" / "silver" / "denominador"


def _cargar_loader():
    ruta = ROOT / "experiments" / "denominador" / "loader.py"
    spec = importlib.util.spec_from_file_location("denominador_loader", ruta)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


loader = _cargar_loader()


def _celdas_sinteticas(n: int = 60, semilla: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(semilla)
    ids = [f"c{i:03d}" for i in range(n)]
    sup = pd.DataFrame(
        {
            "h3_index": ids,
            "latente": rng.gamma(2.0, 100.0, n),
            "observado": rng.gamma(2.0, 10.0, n),
            "latente_robo_hurto_callejero": rng.gamma(2.0, 30.0, n),
            "latente_violencia_familiar_sexual": rng.gamma(2.0, 30.0, n),
            "latente_hibrido": rng.gamma(2.0, 100.0, n),
            "observado_hibrido": rng.gamma(2.0, 10.0, n),
            "observado_geo": rng.poisson(5.0, n).astype(float),
        }
    )
    res = rng.uniform(0, 5000, n)
    res[:3] = 0.0  # celdas sin residentes
    pobl = {
        "h3_population": pd.DataFrame({"h3_index": ids, "population": res}),
        "h3_landscan": pd.DataFrame(
            {
                "h3_index": ids,
                "pop_landscan_2023": rng.uniform(1, 9000, n),
                "pop_landscan_2020": rng.uniform(1, 9000, n),
            }
        ),
        "h3_meta_population": pd.DataFrame({"h3_index": ids, "pop_meta_2020": res * 1.1}),
    }
    admin = pd.DataFrame(
        {
            "h3_index": ids,
            "ubigeo": [f"15{i % 4}" for i in range(n)],
            "distrito": [f"d{i % 4}" for i in range(n)],
        }
    )
    osm = pd.DataFrame({"h3_index": ids, **{c: rng.poisson(2, n) for c in loader.POI_COMERCIAL}})
    return loader.ensamblar(sup, pobl, admin, osm)


def test_sin_denominador_no_es_riesgo_cero():
    df = _celdas_sinteticas()
    sin_res = df["pob_residente"] <= 0
    assert sin_res.sum() == 3
    assert df.loc[sin_res, "r_latente__residente"].isna().all()
    assert not df.loc[sin_res, "evaluable_0"].any()


def test_poblacion_comun_exige_las_tres_fuentes():
    df = _celdas_sinteticas()
    ev = loader.poblacion_comun(df, 500)
    for den in loader.PRINCIPALES:
        assert (df.loc[ev, f"pob_{den}"] > 500).all()


def test_mismo_denominador_da_orden_identico():
    df = _celdas_sinteticas()
    m = loader.comparar(df["h3_index"], df["latente"], df["latente"] * 3.0)
    assert m["spearman"] == pytest.approx(1.0)
    assert m["top25"] == 1.0


def test_top_overlap_es_determinista_con_empates():
    ids = pd.Series(["a", "b", "c", "d"])
    a = pd.Series([1.0, 1.0, 1.0, 0.0])
    assert loader.top_overlap(ids, a, a.copy(), 2) == 1.0


def test_circularidad_detecta_reparto_por_poblacion():
    df = _celdas_sinteticas()
    # Reparto proporcional a WorldPop dentro de distrito: riesgo por residente constante.
    tasa = df["ubigeo"].map({"150": 1.0, "151": 2.0, "152": 3.0, "153": 4.0})
    df["latente"] = tasa * df["pob_residente"]
    df["r_latente__residente"] = np.where(
        df["pob_residente"] > 0,
        df["latente"] / df["pob_residente"].where(df["pob_residente"] > 0),
        np.nan,
    )
    c = loader.circularidad(df, piso=0).set_index("numerador")
    assert c.loc["latente", "var_intra_distrito"] == pytest.approx(0.0, abs=1e-12)
    assert c.loc["latente_hibrido", "var_intra_distrito"] > 0.1


def test_bootstrap_es_determinista():
    df = _celdas_sinteticas(200)
    a = loader.bootstrap(df, piso=0, n_boot=50)
    b = loader.bootstrap(df, piso=0, n_boot=50)
    pd.testing.assert_frame_equal(a, b)


def test_varianza_intra_es_cero_si_todo_es_distrito():
    v = pd.Series([10.0, 10.0, 100.0, 100.0])
    g = pd.Series(["a", "a", "b", "b"])
    assert loader.varianza_intra(v, g) == pytest.approx(0.0)


# ─── sobre los artefactos reales ──────────────────────────────────────────────
@pytest.mark.needs_data
def test_artefactos_existen():
    for n in ("celdas", "reordenamiento", "bootstrap", "circularidad", "resolucion"):
        assert (ART / f"{n}.parquet").exists()


@pytest.mark.needs_data
def test_la_superficie_de_e1_es_circular():
    c = pd.read_parquet(ART / "circularidad.parquet").set_index("numerador")
    assert c.loc["latente", "var_intra_distrito"] < 1e-9
    assert c.loc["latente_hibrido", "var_intra_distrito"] > 0.1


@pytest.mark.needs_data
def test_el_control_reordena_menos_que_el_ambiente():
    b = pd.read_parquet(ART / "bootstrap.parquet")
    fila = b[
        (b["numerador"] == "latente_hibrido")
        & (b["piso"] == loader.PISO_PRIMARIO)
        & (b["estadistico"] == "dif_meta_menos_ambiente")
    ].iloc[0]
    assert fila["ic_low"] > 0


# ─── chequeo posterior (literatura): segundo proxy ambiente ──────────────────
def _cargar_segundo_proxy():
    ruta = ROOT / "experiments" / "denominador" / "segundo_proxy.py"
    spec = importlib.util.spec_from_file_location("denominador_segundo_proxy", ruta)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_reescalar_no_cambia_el_ranking():
    sp = _cargar_segundo_proxy()
    x = pd.Series([3.0, 1.0, 2.0, 10.0])
    y = sp.reescalar(x, 1000.0)
    assert y.sum() == pytest.approx(1000.0)
    assert list(y.rank()) == list(x.rank())


def test_veredicto_aplica_los_umbrales_del_preregistro():
    sp = _cargar_segundo_proxy()

    def caso(rho, top, dif, lo):
        t = pd.DataFrame(
            [{"numerador": "n", "tipo": "vs_residente", "b": "p", "spearman": rho, "top50": top}]
        )
        b = pd.DataFrame(
            [{"numerador": "n", "estadistico": "dif_meta_menos_p", "media": dif, "ic_low": lo}]
        )
        return sp.veredicto(t, b, "p", "n")

    assert caso(0.6, 0.1, 0.25, 0.1) == "se_sostiene"
    assert caso(0.6, 0.1, 0.05, 0.01) == "se_debilita"
    assert caso(0.9, 0.8, 0.0, -0.1) == "se_cae"
    # ρ en el umbral (no < 0,80) con el tope renovado: ni una cosa ni la otra
    assert caso(0.80, 0.46, 0.04, 0.01) == "ambiguo"
