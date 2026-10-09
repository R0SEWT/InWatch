"""Tests del experimento `escalera-de-unidades`.

Los sintéticos protegen lo que hace que la escalera signifique algo: que el bootstrap
sea compartido entre escalones, que Westfall-Young sea monótono, que la duplicación de
los hexágonos de borde (la que hay que replicar para reproducir origen) esté donde se
dice, y que la limpieza de puntos sea la del oráculo. Los ``needs_data`` verifican la
reproducción contra el registro de infelix y solo corren si el loader ya se ejecutó.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "escalera-de-unidades"
ART = ROOT / "data" / "silver" / "escalera-de-unidades"


def _cargar(archivo: str, nombre: str):
    """Por ruta y con nombre propio: `loader` suelto choca con otros experimentos."""
    spec = importlib.util.spec_from_file_location(nombre, EXP / archivo)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = mod
    spec.loader.exec_module(mod)
    return mod


L = _cargar("loader.py", "escalera_unidades_loader")
UF = _cargar("unidades_finas.py", "escalera_unidades_finas")


def _stats(gains: dict[str, float], n_dist: int = 30, ruido: float = 0.05, seed: int = 0):
    """ρ sintéticos por (cat, distrito): cada escalón suma ``gains[step]`` al anterior."""
    rng = np.random.default_rng(seed)
    base = rng.uniform(0.1, 0.4, size=(len(L.CATS), n_dist))
    out, acc = {}, np.zeros_like(base)
    for step in L.STEPS:
        acc = acc + gains.get(step, 0.0)
        rho = base + acc + rng.normal(0, ruido, size=base.shape)
        out[step] = pd.DataFrame({
            "crime_cat": np.repeat(L.CATS, n_dist),
            "ubigeo": np.tile([f"{i:06d}" for i in range(n_dist)], len(L.CATS)),
            "rho": rho.ravel(),
        })
    return out


def test_westfall_young_es_monotono_y_no_menor_que_el_marginal():
    rng = np.random.default_rng(1)
    t_null = rng.normal(size=(4000, 3))
    t_obs = np.array([4.0, 1.0, 2.0])
    adj = L.westfall_young(t_obs, t_null)
    marg = np.array([(1 + np.sum(np.abs(t_null[:, j]) >= abs(t_obs[j]))) / 4001 for j in range(3)])
    assert np.all(adj >= marg - 1e-12)
    orden = np.argsort(-np.abs(t_obs))
    assert np.all(np.diff(adj[orden]) >= 0)


def test_bootstrap_compartido_anula_la_diferencia_entre_escalones_identicos():
    R = np.random.default_rng(2).uniform(size=(20, 1))
    mats = {c: np.hstack([R, R, R, R]) for c in L.CATS}
    draws = L.shared_bootstrap(mats, B=200, seed=3)
    assert draws.shape == (200, 4)
    # Mismo sorteo para todos los escalones: si son iguales, las réplicas también.
    assert np.allclose(draws[:, 0], draws[:, 1])


def test_contrastes_detecta_solo_el_escalon_que_existe():
    stats = _stats({"M1b_manzana": 0.08})
    tab, fam = L.contrastes(stats, B=2000, seed=4)
    h1, h2, h3 = tab.iloc[0], tab.iloc[1], tab.iloc[2]
    assert h1["sobrevive"] and h1["sim_lo"] > 0
    assert not h2["sobrevive"] and not h3["sobrevive"]
    assert fam["c_sim"] > 1.96  # el precio de la simultaneidad
    assert fam["n_pares"] == 30 * len(L.CATS)


def test_rho_por_distrito_excluye_distritos_chicos_o_sin_variacion():
    te = pd.DataFrame({
        "crime_cat": "estafa",
        "ubigeo": ["A"] * 6 + ["B"] * 3 + ["C"] * 6,
        "target": [0, 1, 2, 3, 4, 5] + [1, 2, 3] + [1] * 6,
        "pred": [0, 1, 2, 3, 5, 4] + [1, 2, 3] + [1, 2, 3, 4, 5, 6],
    })
    r = L.per_district_rho(te)
    assert list(r["ubigeo"]) == ["A"]  # B tiene 3 < 5 unidades; C no varía en target


def _feat_y_oraculo():
    feat = pd.DataFrame({"h3_index": ["h1", "h2"] * 2, "year": [2022, 2022, 2023, 2023],
                         "ubigeo": ["150101"] * 4, "population": [1.0, 2.0, 1.0, 2.0]})
    # h1 cruza un límite: el oráculo lo trae partido en dos distritos del hecho.
    orc = pd.DataFrame({"h3_index": ["h1", "h1", "h1", "h1", "h2"],
                        "year": [2022, 2022, 2023, 2023, 2023],
                        "crime_cat": "estafa", "obs_geo_count": [3, 1, 5, 2, 7]})
    return feat, orc


def test_panel_origen_duplica_el_hexagono_de_borde_y_sumado_no():
    feat, orc = _feat_y_oraculo()
    o = L.panel_h3(feat, orc, "origen")
    s = L.panel_h3(feat, orc, "sumado")
    o_e, s_e = o[o["crime_cat"] == "estafa"], s[s["crime_cat"] == "estafa"]
    # 2023: dos filas de conteo × dos filas de rezago (2022) = 4 filas para h1.
    assert len(o_e[(o_e.h3_index == "h1") & (o_e.year == 2023)]) == 4
    assert len(s_e[(s_e.h3_index == "h1") & (s_e.year == 2023)]) == 1
    assert s_e[(s_e.h3_index == "h1") & (s_e.year == 2023)]["target"].item() == 7
    # Otra categoría sin registro: presente y en cero, nunca ausente.
    assert (s[s["crime_cat"] == "secuestro"]["target"] == 0).all()
    with pytest.raises(ValueError):
        L.panel_h3(feat, orc, "otro")


def test_fit_predict_ancho_y_largo_dan_lo_mismo():
    rng = np.random.default_rng(5)
    n = 60
    base = pd.DataFrame({"u": np.tile([f"u{i}" for i in range(n)], 5),
                         "year": np.repeat([2019, 2020, 2021, 2022, 2023], n),
                         "ubigeo": np.tile(["A", "B"] * (n // 2), 5),
                         "x": rng.normal(size=5 * n)})
    ancho = base.copy()
    largo = []
    for c in L.CATS:
        y = rng.poisson(np.exp(ancho["x"]))
        ancho[f"target__{c}"] = y
        largo.append(base.assign(crime_cat=c, target=y))
    largo = pd.concat(largo, ignore_index=True)
    a = L.fit_predict(ancho, ["x"], "u").sort_values(["crime_cat", "u"]).reset_index(drop=True)
    b = L.fit_predict(largo, ["x"], "u").sort_values(["crime_cat", "u"]).reset_index(drop=True)
    assert np.allclose(a["pred"], b["pred"])
    assert np.allclose(a["target"], b["target"])


def test_limpieza_de_puntos_es_la_del_oraculo():
    import h3

    lat, lng = -12.05, -77.03
    cel = h3.latlng_to_cell(lat, lng, 8)
    n_pila = UF.MAX_POR_COORD + 1
    df = pd.DataFrame({
        "solo_denuncia": [1, 1, 0, 1, 1] + [1] * n_pila,
        "estado_coord": ["CON COORDENADA", "SIN COORDENADA", "CON COORDENADA",
                         "CON COORDENADA", "CON COORDENADA"] + ["CON COORDENADA"] * n_pila,
        "id_dist_hecho": ["150101"] * (5 + n_pila),
        "lat_hecho": [lat, lat, lat, lat + 0.0001, 10.0] + [lat + 0.0002] * n_pila,
        "long_hecho": [lng] * 5 + [lng] * n_pila,
        "año_hecho": [2020] * (5 + n_pila),
        "tipo_hecho": (["PATRIMONIO (DELITO)"] * 3 + ["OTRO"]
                       + ["PATRIMONIO (DELITO)"] * (1 + n_pila)),
        "subtipo_hecho": ["ROBO"] * (5 + n_pila),
        "modalidad_hecho": [""] * (5 + n_pila),
    })
    out = UF.limpiar_puntos(df, {cel})
    # Sobrevive solo la primera: la 2 no tiene coordenada, la 3 no es denuncia, la 4
    # no cae en ninguna categoría, la 5 está fuera del bbox y el resto es una pila.
    assert len(out) == 1
    assert out["crime_cat"].item() == "robo_hurto_callejero"


def test_asignacion_por_cercania_respeta_el_radio():
    uni = np.array([[0.0, 0.0], [1000.0, 0.0]])
    pts = np.array([[10.0, 0.0], [990.0, 0.0], [500.0, 400.0]])
    assert list(UF.asignar_cercano(pts, uni, 150.0)) == [0, 1, -1]
    assert list(UF.asignar_cercano(pts, uni, None))[:2] == [0, 1]


@pytest.mark.needs_data
def test_reproduce_la_cifra_de_origen_en_h3():
    rep = pd.read_parquet(ART / "reproduccion_h3.parquet")
    assert np.allclose(rep["aca"], rep["origen"], atol=1e-6), rep


@pytest.mark.needs_data
def test_los_puntos_rehacen_el_oraculo_exacto():
    meta = json.loads((ART / "familias.json").read_text())
    chk = meta["diagnosticos"]["puntos_vs_oraculo"]
    assert chk["filas_distintas"] == 0
    assert chk["total_aca"] == chk["total_oraculo"]
