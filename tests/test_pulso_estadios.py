"""Tests de `pulso-estadios`.

La mayoría corre sin datos: la lógica de event-time (parseo de kickoff, estimador MH,
armado del calendario y de los estratos) es aritmética pura y se ejercita con tablas
sintéticas. Sólo la réplica contra el ancla de infelix necesita artefactos, y va
marcada `needs_data` porque `data/` está gitignored y el CI la excluye.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_LOADER = Path(__file__).resolve().parents[1] / "experiments/pulso-estadios/loader.py"
_spec = importlib.util.spec_from_file_location("pulso_loader", _LOADER)
loader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(loader)


# ─── parseo de kickoff ───────────────────────────────────────────────────────
@pytest.mark.parametrize(("crudo", "esperado"), [
    ("19:30", 19.5),
    ("20:00", 20.0),
    ("09:15", 9.25),
    ("00:45", 0.75),
])
def test_parse_kickoff_convierte_a_horas_fraccionales(crudo, esperado):
    assert loader.parse_kickoff(crudo) == pytest.approx(esperado)


@pytest.mark.parametrize("crudo", [None, "", "sin hora", float("nan"), 1930])
def test_parse_kickoff_devuelve_nan_en_lo_no_parseable(crudo):
    assert math.isnan(loader.parse_kickoff(crudo))


# ─── estimador ───────────────────────────────────────────────────────────────
def test_mh_rr_es_uno_cuando_tratado_iguala_al_control_medio():
    """Sin efecto, el rate-ratio tiene que dar exactamente 1."""
    a = np.array([2.0, 3.0])       # tratado
    nc = np.array([4.0, 4.0])      # 4 controles por estrato
    c = a * nc                     # cada control aporta lo mismo que el tratado
    assert loader.mh_rr(a, c, nc) == pytest.approx(1.0)


def test_mh_rr_duplica_cuando_el_tratado_duplica_al_control():
    a = np.array([6.0])
    nc = np.array([3.0])
    c = np.array([9.0])            # media control = 3, tratado = 6
    assert loader.mh_rr(a, c, nc) == pytest.approx(2.0)


def test_mh_rr_es_nan_sin_eventos_de_control():
    assert math.isnan(loader.mh_rr(np.array([1.0]), np.array([0.0]), np.array([2.0])))


def test_boot_ci_encierra_el_puntual_con_estratos_homogeneos():
    rng = np.random.default_rng(0)
    a = np.full(40, 4.0)
    nc = np.full(40, 2.0)
    c = np.full(40, 4.0)           # media control = 2 → RR = 2
    lo, hi = loader.boot_ci(a, c, nc, 200, rng)
    assert lo <= loader.mh_rr(a, c, nc) <= hi


def test_boot_ci_es_nan_sin_estratos():
    lo, hi = loader.boot_ci(np.array([]), np.array([]), np.array([]),
                            100, np.random.default_rng(0))
    assert math.isnan(lo) and math.isnan(hi)


# ─── calendario y estratos ───────────────────────────────────────────────────
def _kev_sintetico() -> pd.DataFrame:
    """Dos partidos en `nacional`, ambos un martes del mismo mes."""
    return pd.DataFrame({
        "date": ["2019-01-08", "2019-01-15"],
        "kickoff": ["20:00", "20:00"],
        "stadium": ["nacional", "nacional"],
        "event": ["liga1", "liga1"],
        "crowd": ["full", "full"],
        "day": [7, 14],
        "kh": [20.0, 20.0],
    })


def test_calendario_marca_los_dias_con_evento_y_solo_esos():
    cal = loader.calendario(_kev_sintetico(), "nacional")
    assert len(cal) == loader.N_DAYS
    assert bool(cal.loc[cal["day"] == 7, "has_event"].iloc[0])
    assert bool(cal.loc[cal["day"] == 14, "has_event"].iloc[0])
    assert not bool(cal.loc[cal["day"] == 8, "has_event"].iloc[0])
    assert int(cal["has_event"].sum()) == 2


def test_calendario_ignora_los_eventos_de_otro_estadio():
    cal = loader.calendario(_kev_sintetico(), "matute")
    assert int(cal["has_event"].sum()) == 0


def test_calendario_marca_crowd_rank_solo_con_multitud():
    kev = _kev_sintetico()
    kev.loc[1, "crowd"] = "none"
    cal = loader.calendario(kev, "nacional")
    assert int(cal.loc[cal["day"] == 7, "crowd_rank"].iloc[0]) == 1
    assert int(cal.loc[cal["day"] == 14, "crowd_rank"].iloc[0]) == 0


def test_estratos_emparejan_controles_del_mismo_dia_de_semana_y_mes():
    kev = _kev_sintetico()
    cals = {st: loader.calendario(kev, st) for st in loader.STADIUMS}
    for st in cals:
        cals[st]["contaminado"] = False
    estratos = loader.construir_estratos(kev, cals, "full")

    assert len(estratos) == 2
    cal = cals["nacional"]
    for st, d, kh, pool in estratos:
        assert st == "nacional"
        assert kh == 20.0
        assert d not in pool                      # nunca es su propio control
        fila = cal[cal["day"] == d].iloc[0]
        emp = cal[cal["day"].isin(pool)]
        assert (emp["dow"] == fila["dow"]).all()  # mismo día de semana
        assert (emp["ym"] == fila["ym"]).all()    # mismo año-mes
        assert not emp["has_event"].any()         # controles sin evento


def test_estratos_descartan_dias_contaminados_por_un_vecino():
    kev = _kev_sintetico()
    cals = {st: loader.calendario(kev, st) for st in loader.STADIUMS}
    for st in cals:
        cals[st]["contaminado"] = False
    cals["nacional"].loc[cals["nacional"]["day"] == 7, "contaminado"] = True
    estratos = loader.construir_estratos(kev, cals, "full")
    assert [d for _, d, _, _ in estratos] == [14]


def test_estratos_vacios_para_una_variante_sin_partidos():
    kev = _kev_sintetico()
    cals = {st: loader.calendario(kev, st) for st in loader.STADIUMS}
    for st in cals:
        cals[st]["contaminado"] = False
    assert loader.construir_estratos(kev, cals, "none") == []


# ─── crosswalk de categorías ────────────────────────────────────────────────
def test_map_category_reconoce_robo_callejero_y_deja_fuera_lo_demas():
    tipo = pd.Series(["PATRIMONIO (DELITO)", "PATRIMONIO (DELITO)", "OTRA COSA"])
    sub = pd.Series(["ROBO", "ESTAFA Y OTRAS DEFRAUDACIONES", "X"])
    mod = pd.Series(["", "", ""])
    cat = loader.map_category(tipo, sub, mod)
    assert cat.iloc[0] == "robo_hurto_callejero"
    assert cat.iloc[1] == "estafa"
    assert pd.isna(cat.iloc[2])


def test_map_category_da_prioridad_a_secuestro():
    """La regla de secuestro sobre-escribe a las anteriores, y es a propósito."""
    tipo = pd.Series(["PATRIMONIO (DELITO)"])
    sub = pd.Series(["ROBO"])
    mod = pd.Series(["SECUESTRO AL PASO"])
    assert loader.map_category(tipo, sub, mod).iloc[0] == "secuestro"


# ─── invariantes de los anillos ─────────────────────────────────────────────
def test_los_anillos_son_contiguos_y_no_se_solapan():
    assert len(loader.RING_EDGES) == len(loader.RING_NAMES) + 1
    assert sorted(loader.RING_EDGES) == loader.RING_EDGES


def test_el_umbral_de_contaminacion_separa_el_par_nacional_matute():
    """Nacional y matute están a ~1.200 m: el umbral tiene que contaminarlos.

    Es el SUPUESTO DEL PORT 2/3 hecho test. Si alguien baja CROSS_CONTAM_M por debajo
    de la distancia real, este test lo detiene — el original declaraba explícitamente
    que ese par se contamina.
    """
    c = {st: np.array([ln * loader.M_PER_DEG_LNG, la * loader.M_PER_DEG_LAT])
         for st, (la, ln) in loader.STADIUMS.items()}
    d = float(np.hypot(*(c["nacional"] - c["matute"])))
    assert 1_000 < d < 1_500, f"distancia inesperada nacional-matute: {d:.0f} m"
    assert d < loader.CROSS_CONTAM_M


# ─── réplica contra el ancla (requiere artefactos) ──────────────────────────
@pytest.mark.needs_data
def test_la_replica_reproduce_el_ancla_de_infelix():
    """Criterio de cierre del hito: el port no derivó.

    Tolerancia declarada: 1% relativo en el rate-ratio. No es holgura estética — el
    bootstrap usa una semilla fija, así que la única fuente de diferencia legítima es
    aritmética de punto flotante en el reensamblado de los estratos.
    """
    art = Path(__file__).resolve().parents[1] / "data/silver/pulso-estadios/ancla.parquet"
    if not art.exists():
        pytest.skip("falta ancla.parquet — corre experiments/pulso-estadios/loader.py")
    ancla = pd.read_parquet(art)
    peor = ancla["delta_rr_rel"].max()
    assert peor < 0.01, f"la réplica derivó {peor:.2%} contra el ancla de infelix"
