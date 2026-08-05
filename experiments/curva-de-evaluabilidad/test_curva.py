"""Tests de `curva-de-evaluabilidad`.

Los que importan corren **sin datos**: ejercitan la agregación, la comparación pareada y
la inversión del piso sobre marcos sintéticos, porque lo que este experimento no puede
romper —que la brecha se derive por semilla y no restando promedios, que la penalidad
selectiva se mida contra su brazo pareado y no contra otra corrida, y que el piso sea
monótono— es lógica, no volumen. Si un refactor las rompe, tiene que fallar en CI, donde
`data/` no existe.

Los marcados ``needs_data`` verifican los artefactos reales y se saltan solos cuando faltan.

**El loader se importa por ruta, no por `sys.path`.** Dos experimentos con un `loader.py`
cada uno colisionan bajo `import loader` — es el bug `inwatch-0ge`, que este archivo no
arrastra: `importlib` le da un nombre de módulo único y no toca el `sys.path` del proceso.
Por el mismo motivo el archivo se llama `test_curva.py` y no `test_loader.py`: pytest sin
`__init__.py` resuelve los módulos de test por nombre base, y dos `test_loader.py` en el
árbol chocan al recolectar.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_spec = importlib.util.spec_from_file_location(
    "inwatch_experimento_curva_de_evaluabilidad_loader", Path(__file__).parent / "loader.py"
)
loader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(loader)


# ─── marcos sintéticos ────────────────────────────────────────────────────────
def _crudo(rate: float, seed: int, medible: float, real: float, persistencia: float) -> dict:
    return {
        "rate": rate, "seed": seed, "medible": medible, "real": real,
        "persist": persistencia, "feat_gana": medible > persistencia,
    }


@pytest.fixture
def uniforme() -> pd.DataFrame:
    """Dos niveles × dos semillas. La brecha crece cuando la tasa baja, como en el real."""
    return pd.DataFrame(
        [
            _crudo(0.8, 0, 0.40, 0.42, 0.30),
            _crudo(0.8, 1, 0.42, 0.44, 0.32),
            _crudo(0.2, 0, 0.30, 0.40, 0.20),
            _crudo(0.2, 1, 0.32, 0.42, 0.22),
        ]
    )


@pytest.fixture
def selectivo() -> pd.DataFrame:
    """Los dos mecanismos sobre la MISMA grilla y las mismas semillas.

    El brazo uniforme reproduce la media del fixture `uniforme` en cada nivel: son dos
    corridas del mismo mecanismo y la réplica cruzada del loader exige justamente eso.
    El brazo selectivo castiga solo el ρ medible — la firma del hallazgo real.
    """
    filas = []
    for mech, castigo in (("uniforme", 0.0), ("selectivo", 0.05)):
        for rate, medible, real, persistencia in ((0.8, 0.41, 0.43, 0.31),
                                                  (0.2, 0.31, 0.41, 0.21)):
            for seed in (0, 1):
                filas.append(
                    {
                        "mechanism": mech,
                        **_crudo(rate, seed, medible - castigo, real, persistencia),
                        "cover_dist": 39.0,
                        "achieved_ret": rate,
                    }
                )
    return pd.DataFrame(filas)


def _dos_mecanismos(selectivo: pd.DataFrame) -> pd.DataFrame:
    """El CSV selectivo en forma larga, sin pasar por disco."""
    nombre = {"uniforme": loader.CURVA_PAREADA, "selectivo": loader.CURVA_SELECTIVA}
    return pd.concat(
        [loader._por_semilla(g, nombre[m]) for m, g in selectivo.groupby("mechanism")],
        ignore_index=True,
    )


@pytest.fixture
def curvas(uniforme, selectivo) -> pd.DataFrame:
    return loader.agregar(
        pd.concat(
            [loader._por_semilla(uniforme, loader.CURVA_PAPER), _dos_mecanismos(selectivo)],
            ignore_index=True,
        )
    )


# ─── las cantidades derivadas son pareadas, no diferencias de promedios ───────
def test_la_brecha_se_deriva_por_semilla(uniforme):
    """Restar promedios daría la misma media y una dispersión inventada. Acá la sd de la
    brecha es la de la diferencia pareada, que es mucho más estrecha."""
    ps = loader._por_semilla(uniforme, "x")
    assert ps["brecha"].tolist() == pytest.approx([0.02, 0.02, 0.10, 0.10])
    agg = loader.agregar(ps)
    fila = agg[agg["rate"] == 0.8].iloc[0]
    # La brecha es idéntica en las dos semillas → sd cero, aunque medible y real varían.
    assert fila["brecha_sd"] == pytest.approx(0.0, abs=1e-12)
    assert fila["medible_sd"] > 0.0


def test_la_ventaja_tambien_es_pareada(uniforme):
    ps = loader._por_semilla(uniforme, "x")
    assert ps["ventaja"].tolist() == pytest.approx([0.10, 0.10, 0.10, 0.10])


def test_el_nivel_de_una_sola_semilla_deja_sd_nan_y_no_cero():
    """Determinista y «medimos dispersión y dio cero» no son lo mismo, y el nivel base
    (83.4 %) es lo primero. Rellenar con 0 diría lo segundo."""
    ps = loader._por_semilla(pd.DataFrame([_crudo(0.834, 0, 0.46, 0.46, 0.40)]), "x")
    fila = loader.agregar(ps).iloc[0]
    assert fila["n_semillas"] == 1
    assert np.isnan(fila["medible_sd"])
    assert np.isnan(fila["brecha_sd"])


# ─── la comparación de mecanismos tiene que ser pareada ───────────────────────
def test_la_penalidad_selectiva_es_pareada_por_semilla(selectivo):
    pen = loader.penalidad_selectiva(_dos_mecanismos(selectivo)).set_index("rate")
    assert pen.loc[0.8, "d_medible"] == pytest.approx(-0.05)
    assert pen.loc[0.8, "d_real"] == pytest.approx(0.0)
    assert pen.loc[0.8, "n_semillas"] == 2


def test_la_penalidad_falla_si_no_hay_brazo_pareado(uniforme):
    """Medir la penalidad contra otra corrida mezclaría diferencia de mecanismo con
    diferencia de RNG, y el número resultante no significaría nada."""
    solo_una = loader._por_semilla(uniforme, loader.CURVA_SELECTIVA)
    with pytest.raises(ValueError, match="no hay par que restar"):
        loader.penalidad_selectiva(solo_una)


def test_la_penalidad_falla_si_los_brazos_no_comparten_semillas(selectivo):
    """Dos brazos presentes pero disjuntos darían una diferencia entre corridas distintas
    disfrazada de diferencia de mecanismo."""
    desalineado = _dos_mecanismos(selectivo)
    mask = desalineado["curva"] == loader.CURVA_SELECTIVA
    desalineado.loc[mask, "seed"] = desalineado.loc[mask, "seed"] + 100
    with pytest.raises(ValueError, match="no comparten ninguna"):
        loader.penalidad_selectiva(desalineado)


def test_leer_selectiva_exige_los_dos_mecanismos(tmp_path, selectivo):
    csv = tmp_path / "sel.csv"
    selectivo[selectivo["mechanism"] == "selectivo"].to_csv(csv, index=False)
    with pytest.raises(ValueError, match="no trae los dos mecanismos"):
        loader.leer_selectiva(csv)


# ─── la réplica cruzada es lo que permite un solo eje ─────────────────────────
def test_la_replica_pasa_cuando_las_dos_uniformes_coinciden(curvas):
    delta = loader.verificar_replica(curvas)
    assert not delta.empty
    assert (delta <= loader.TOL_REPLICA).to_numpy().all()


def test_la_replica_falla_si_las_dos_uniformes_divergen(curvas):
    """Si divergen, la diferencia entre la curva del paper y la selectiva sería en parte
    diferencia entre corridas, y ponerlas en el mismo eje mentiría."""
    roto = curvas.copy()
    mask = roto["curva"] == loader.CURVA_PAREADA
    roto.loc[mask, "medible"] = roto.loc[mask, "medible"] + 0.2
    with pytest.raises(ValueError, match="dejaron de ser réplicas"):
        loader.verificar_replica(roto)


def test_la_replica_falla_si_las_grillas_no_se_tocan(curvas):
    roto = curvas.copy()
    mask = roto["curva"] == loader.CURVA_PAREADA
    roto.loc[mask, "rate"] = roto.loc[mask, "rate"] + 0.01
    with pytest.raises(ValueError, match="no comparten ni un nivel"):
        loader.verificar_replica(roto)


# ─── el piso es la regla de diseño y no puede inventarse tramos ───────────────
@pytest.fixture
def curva_piso() -> pd.DataFrame:
    return pd.DataFrame({"rate": [0.8, 0.5, 0.2], "brecha": [0.02, 0.06, 0.10]})


def test_el_piso_interpola_entre_niveles_medidos(curva_piso):
    assert loader.piso_de_evaluabilidad(curva_piso, 0.04) == pytest.approx(0.65)


def test_el_piso_no_extrapola_fuera_del_rango_medido(curva_piso):
    """Más allá del último nivel el experimento ya no sabe nada; devolver el extremo es
    decir «hasta acá se midió», y extrapolar sería inventar el tramo."""
    assert loader.piso_de_evaluabilidad(curva_piso, 0.5) == pytest.approx(0.2)
    assert loader.piso_de_evaluabilidad(curva_piso, 0.0) == pytest.approx(0.8)


def test_el_piso_falla_si_la_brecha_no_es_monotona():
    """La inversión solo está definida sobre una brecha monótona. Si deja de serlo hay que
    mirar la curva, no reportar un piso que depende de qué rama tocó la interpolación."""
    torcida = pd.DataFrame({"rate": [0.8, 0.5, 0.2], "brecha": [0.02, 0.10, 0.06]})
    with pytest.raises(ValueError, match="dejó de ser monótona"):
        loader.piso_de_evaluabilidad(torcida, 0.05)


def test_la_tabla_de_pisos_cubre_cada_curva_y_es_monotona(curvas):
    """El notebook busca en esta tabla en vez de recalcular. Si tuviera huecos, la vista
    discreparía del `piso_geocod_tau05` que el registro declara canónico."""
    tabla = loader.tabla_de_pisos(curvas)
    assert set(tabla["curva"]) == set(curvas["curva"])
    for _, sub in tabla.groupby("curva"):
        piso = sub.sort_values("tau")["piso"].to_numpy()
        assert np.all(np.diff(piso) <= 1e-12), "más tolerancia nunca puede exigir más tasa"


# ─── contra los artefactos reales ─────────────────────────────────────────────
@pytest.fixture
def artefactos() -> dict[str, pd.DataFrame]:
    salida = {}
    for nombre in ("curvas", "penalidad", "pisos"):
        dest = loader.OUT / f"{nombre}.parquet"
        if not dest.exists():
            pytest.skip(f"falta {dest}; corre el loader")
        salida[nombre] = pd.read_parquet(dest)
    return salida


@pytest.mark.needs_data
def test_el_artefacto_trae_las_tres_curvas(artefactos):
    assert set(artefactos["curvas"]["curva"]) == {
        loader.CURVA_PAPER, loader.CURVA_PAREADA, loader.CURVA_SELECTIVA
    }


@pytest.mark.needs_data
def test_las_dos_ciudades_marcadas_son_niveles_medidos(artefactos):
    """Lima y Trujillo no se interpolan: sus tasas están en la grilla de origen. Si dejaran
    de estarlo, los marcadores del eje pasarían a ser decorativos."""
    curvas = artefactos["curvas"]
    paper = set(curvas.loc[curvas["curva"] == loader.CURVA_PAPER, "rate"])
    selectiva = set(curvas.loc[curvas["curva"] == loader.CURVA_SELECTIVA, "rate"])
    assert loader.TASA_LIMA in paper and loader.TASA_LIMA in selectiva
    assert loader.TASA_TRUJILLO in selectiva


@pytest.mark.needs_data
def test_la_brecha_es_positiva_y_crece_cuando_el_registro_empeora(artefactos):
    """El hallazgo, como test: el ρ medible nunca supera al real, y la distancia crece
    monótonamente al bajar la tasa. Si esto se rompiera, el experimento dejó de decir lo
    que su README dice."""
    for _, sub in artefactos["curvas"].groupby("curva"):
        sub = sub.sort_values("rate", ascending=False)
        assert (sub["brecha"] >= -1e-9).all()
        assert np.all(np.diff(sub["brecha"].to_numpy()) >= -1e-9)


@pytest.mark.needs_data
def test_la_señal_sobrevive_en_todos_los_niveles(artefactos):
    """Lo que colapsa es la medición, no el modelo: features gana a persistencia en el
    100 % de las semillas en todo nivel y mecanismo."""
    assert (artefactos["curvas"]["feat_gana_pct"] == 100.0).all()


@pytest.mark.needs_data
def test_la_penalidad_selectiva_castiga_mas_la_medicion_que_la_señal(artefactos):
    """La frase del README —«ensucia la medición, no tanto la señal»— es una afirmación
    sobre los datos y tiene que poder fallar."""
    pen = artefactos["penalidad"]
    degradados = pen[pen["rate"] < loader.TASA_LIMA]
    assert (degradados["d_medible"] < degradados["d_real"]).all()


@pytest.mark.needs_data
def test_el_piso_del_registro_coincide_con_la_tabla_precomputada(artefactos):
    """El notebook lee la tabla; el README cita el registro. Si discreparan, la vista
    contradiría al número canónico, que es peor que no tener registro."""
    from inwatch import canon

    pisos = artefactos["pisos"]
    for curva, variante in (
        (loader.CURVA_PAPER, "uniforme"), (loader.CURVA_SELECTIVA, "selectivo")
    ):
        fila = pisos[(pisos["curva"] == curva) & (pisos["tau"] == loader.TAU_REPORTADA)]
        registrado = canon.value(f"evaluabilidad.piso_geocod_tau05.{variante}")
        assert 100.0 * float(fila["piso"].iloc[0]) == pytest.approx(registrado, abs=1e-4)
