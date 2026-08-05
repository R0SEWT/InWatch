"""Precómputo de `curva-de-evaluabilidad`: 152 corridas por semilla → dos parquets.

Este experimento no mide crimen ni cobertura. Mide **hasta qué tasa de geocodificación
un mapa sigue pudiendo evaluarse**, que es una pregunta distinta y anterior: antes de
preguntar si el modelo acierta hay que preguntar si se puede saber si acierta.

El diseño de origen adelgaza binomialmente los conteos del oráculo de Lima (base 83.4 %)
hacia tasas menores, re-entrena el modelo tabular techo sobre los targets degradados y
mide dos cosas que la práctica normal confunde en una sola:

- **ρ medible** — correlación contra el oráculo *degradado*: lo que vería un analista en
  una ciudad con ese registro. Es el número que se reportaría.
- **ρ real** — correlación contra el oráculo *completo*: lo que el modelo de verdad
  aprendió. Nadie en esa ciudad puede calcularlo, porque exigiría el dato que falta.

La brecha entre las dos es el error de medición, y es el objeto del experimento.

**Dos mecanismos de pérdida, y la diferencia importa.** El experimento original asume
pérdida ALEATORIA (MCAR): cada hecho retiene su coordenada con la misma probabilidad.
Eso es una cota optimista y el repo de origen lo declara como tal. Un segundo experimento
modela pérdida SELECTIVA —retención proporcional a la propensión de éxito del distrito ×
categoría— y encuentra que la penalidad extra cae sobre la *medición*, no sobre la señal.
Las dos curvas viajan en el mismo artefacto porque presentar solo la optimista sería
cometer, un piso más arriba, el mismo error que este repo existe para no cometer.

Contrato de salida:
  - **no hay unidad espacial**: la fila es (curva, tasa), no una celda. La unidad de
    observación subyacente es ``h3_8``, agregada a ρ intra-distrital macro; ver README.
  - las columnas de dispersión (``*_sd``, ``n_semillas``) viajan al lado de las medias,
    nunca sin ellas
  - determinista: no hay RNG acá — los seeds ya están en los CSV de origen
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from inwatch import canon

SLUG = "curva-de-evaluabilidad"

# Read-only. El repo de origen nunca se modifica desde acá — ver CLAUDE.md, "Frontera dura".
SOURCE = Path("/home/rosewt-dell/Code/tesis/infelix/data/silver")
FUENTE_UNIFORME = SOURCE / "predictions" / "geocoding_degradation.csv"
FUENTE_SELECTIVA = SOURCE / "predictions" / "selective_geocoding_degradation.csv"
OUT = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG

# Las tres curvas del artefacto. `uniforme` es la del paper (figura fig-simbig-degradation);
# `selectivo` y `uniforme_pareado` viven en el segundo CSV y comparten grilla de tasas,
# semillas y protocolo — son la ÚNICA comparación de mecanismos que es apples-to-apples.
# `uniforme` y `uniforme_pareado` son dos corridas independientes del mismo mecanismo
# sobre grillas distintas: sirven de réplica cruzada, no de comparación.
CURVA_PAPER = "uniforme"
CURVA_PAREADA = "uniforme_pareado"
CURVA_SELECTIVA = "selectivo"

# Tolerancia de la réplica cruzada, en ρ. Las dos corridas uniformes usan RNG distinto,
# así que no pueden coincidir exactamente fuera de la base determinista; 0.03 es holgado
# frente a la sd entre semillas (~0.014) y ajustado frente a la brecha que el experimento
# reporta (~0.12 a 10 %). Si se rompe, las dos corridas dejaron de medir lo mismo.
TOL_REPLICA = 0.03

# Tolerancia de error de medición con la que se reporta el piso en el README. Es un
# parámetro elegido, no una medición: cuánto ρ se está dispuesto a equivocarse antes de
# declarar que el mapa no es evaluable. El notebook lo deja mover.
TAU_REPORTADA = 0.05

# Rejilla de tolerancias precomputadas para el control del notebook. El paso es la mitad
# del paso del slider, así que toda posición del control cae exactamente sobre un punto
# medido y la búsqueda no interpola nada. El tope cubre la brecha máxima observada.
TAUS = np.round(np.arange(0.0, 0.1301, 0.0025), 4)

# Sufijo canónico por nivel de la curva del paper. Se fija acá para que el README y el
# registro no puedan desincronizarse: `r83` es la base real de Lima (83.4 %).
NIVELES_PAPER = {0.834: "r83", 0.70: "r70", 0.50: "r50", 0.25: "r25", 0.10: "r10"}

# Las dos ciudades que el experimento marca. No son ilustrativas: 83.4 % es la base sobre
# la que el adelgazamiento está calibrado y 24.9 % es un nivel MEDIDO del segundo CSV,
# puesto ahí porque es la tasa real de Trujillo.
TASA_LIMA = 0.834
TASA_TRUJILLO = 0.249

METRICAS = ("medible", "real", "persistencia")


# ─── lectura ──────────────────────────────────────────────────────────────────
def _por_semilla(df: pd.DataFrame, curva: str) -> pd.DataFrame:
    """Normaliza un CSV de origen a la forma larga común, una fila por (curva, tasa, semilla).

    Renombra ``persist`` a ``persistencia`` y deriva las dos cantidades que el experimento
    afirma. Se derivan **por semilla y no sobre las medias** porque son diferencias
    pareadas: la misma corrida produce el ρ medible y el ρ real, así que su sd es la de la
    diferencia, mucho más estrecha que la suma de las sd marginales. Restar promedios
    daría la misma media y una dispersión inventada.
    """
    out = df.rename(columns={"persist": "persistencia"}).assign(curva=curva)
    out["brecha"] = out["real"] - out["medible"]
    out["ventaja"] = out["medible"] - out["persistencia"]
    cols = ["curva", "rate", "seed", *METRICAS, "brecha", "ventaja", "feat_gana"]
    extra = [c for c in ("cover_dist", "achieved_ret") if c in out.columns]
    return out[cols + extra]


def leer_uniforme(path: Path = FUENTE_UNIFORME) -> pd.DataFrame:
    """Curva del paper: adelgazamiento uniforme, la que sostiene `fig-simbig-degradation`."""
    return _por_semilla(pd.read_csv(path), CURVA_PAPER)


def leer_selectiva(path: Path = FUENTE_SELECTIVA) -> pd.DataFrame:
    """Las dos curvas del experimento selectivo, sobre grilla y semillas compartidas."""
    df = pd.read_csv(path)
    faltan = {"uniforme", "selectivo"} - set(df["mechanism"])
    if faltan:
        raise ValueError(
            f"{path.name} no trae los dos mecanismos (falta {sorted(faltan)}); "
            "sin el brazo pareado no hay comparación válida y la penalidad selectiva "
            "quedaría medida contra otra corrida"
        )
    nombre = {"uniforme": CURVA_PAREADA, "selectivo": CURVA_SELECTIVA}
    partes = [_por_semilla(g, nombre[m]) for m, g in df.groupby("mechanism")]
    return pd.concat(partes, ignore_index=True)


# ─── agregación ───────────────────────────────────────────────────────────────
def agregar(por_semilla: pd.DataFrame) -> pd.DataFrame:
    """Colapsa las semillas: una fila por (curva, tasa), con media y sd de cada cantidad.

    ``ddof=1`` sobre un solo valor da NaN, no 0. Se deja NaN a propósito: el nivel base
    (83.4 %) es determinista por construcción —no hay adelgazamiento que aleatorizar— y en
    el CSV selectivo trae una sola semilla. Rellenarlo con 0 diría "medimos dispersión y
    dio cero", que es distinto de "no hay dispersión que medir".
    """
    agg = {}
    for col in (*METRICAS, "brecha", "ventaja"):
        agg[col] = (col, "mean")
        agg[f"{col}_sd"] = (col, "std")
    agg["feat_gana_pct"] = ("feat_gana", lambda s: 100.0 * float(s.mean()))
    agg["n_semillas"] = ("seed", "nunique")
    for col in ("cover_dist", "achieved_ret"):
        if col in por_semilla.columns:
            agg[col] = (col, "mean")

    out = (
        por_semilla.groupby(["curva", "rate"], as_index=False)
        .agg(**agg)
        .sort_values(["curva", "rate"], ascending=[True, False], ignore_index=True)
    )
    return out.rename(columns={"cover_dist": "cobertura_distritos", "achieved_ret": "retencion"})


def verificar_replica(agg: pd.DataFrame, tol: float = TOL_REPLICA) -> pd.DataFrame:
    """Las dos corridas uniformes tienen que coincidir donde sus grillas se tocan.

    Son corridas independientes del mismo mecanismo, con RNG distinto y en scripts
    distintos del repo de origen. Que coincidan no es decorativo: es lo único que permite
    poner la curva del paper y la curva selectiva en el mismo eje sin que la diferencia
    entre ellas sea, en parte, diferencia entre corridas. Si divergen, el artefacto de
    origen cambió bajo los pies del experimento y hay que enterarse acá, no en el render.
    """
    u = agg[agg["curva"] == CURVA_PAPER].set_index("rate")
    p = agg[agg["curva"] == CURVA_PAREADA].set_index("rate")
    comunes = sorted(set(u.index) & set(p.index))
    if not comunes:
        raise ValueError(
            "las dos corridas uniformes no comparten ni un nivel de tasa; "
            "no hay forma de verificar que miden lo mismo"
        )
    delta = (u.loc[comunes, list(METRICAS)] - p.loc[comunes, list(METRICAS)]).abs()
    if (delta > tol).to_numpy().any():
        peor = delta.max().max()
        raise ValueError(
            f"las dos corridas uniformes divergen hasta {peor:.4f} de ρ en los niveles "
            f"{comunes} (tolerancia {tol}); dejaron de ser réplicas y la curva del paper "
            "no se puede poner en el mismo eje que la selectiva"
        )
    return delta


def penalidad_selectiva(por_semilla: pd.DataFrame) -> pd.DataFrame:
    """Cuánto ρ extra cuesta que la pérdida sea selectiva y no aleatoria, semilla a semilla.

    Pareado por ``(rate, seed)``: los dos mecanismos corren sobre la misma grilla con las
    mismas semillas en el mismo script de origen, así que la diferencia por semilla es la
    comparación correcta. Restar las medias daría el mismo centro sin ninguna dispersión
    con la que juzgar si la penalidad es distinguible de ruido.
    """
    brazos = {CURVA_PAREADA, CURVA_SELECTIVA}
    sub = por_semilla[por_semilla["curva"].isin(brazos)]
    if faltan := sorted(brazos - set(sub["curva"])):
        raise ValueError(
            f"falta el brazo {faltan}: no hay par que restar. Medir la penalidad contra "
            "otra corrida mezclaría diferencia de mecanismo con diferencia de RNG"
        )
    ancho = sub.pivot_table(
        index=["rate", "seed"], columns="curva", values=list(METRICAS)
    ).dropna()
    if ancho.empty:
        raise ValueError(
            "los dos brazos existen pero no comparten ninguna (tasa, semilla): "
            "no hay par que restar"
        )

    d = pd.DataFrame(
        {m: ancho[(m, CURVA_SELECTIVA)] - ancho[(m, CURVA_PAREADA)] for m in METRICAS}
    ).reset_index()
    agg = {}
    for m in METRICAS:
        agg[f"d_{m}"] = (m, "mean")
        agg[f"d_{m}_sd"] = (m, "std")
    agg["n_semillas"] = ("seed", "nunique")
    return (
        d.groupby("rate", as_index=False)
        .agg(**agg)
        .sort_values("rate", ascending=False, ignore_index=True)
    )


# ─── el hallazgo, hecho regla de diseño ───────────────────────────────────────
def piso_de_evaluabilidad(curva: pd.DataFrame, tau: float) -> float:
    """Tasa mínima de geocodificación cuya brecha de medición no supera ``tau``.

    Es la consecuencia de diseño del experimento vuelta número: por debajo de este piso,
    lo correcto no es dibujar el mapa con una nota al pie, es no afirmar que se lo puede
    evaluar. Se interpola linealmente entre los niveles medidos porque la brecha es
    monótona en la tasa en las dos curvas (verificado acá, no supuesto).

    Devuelve la tasa en fracción. Fuera del rango medido devuelve el extremo — extrapolar
    una curva de degradación más allá del 10 % inventaría el tramo justamente donde el
    experimento ya no sabe nada.
    """
    c = curva.sort_values("rate")
    tasas = c["rate"].to_numpy(dtype=float)
    brechas = c["brecha"].to_numpy(dtype=float)
    if np.any(np.diff(brechas) > 0):
        raise ValueError(
            "la brecha dejó de ser monótona decreciente en la tasa; la interpolación del "
            "piso deja de estar definida y hay que mirar la curva antes de reportar nada"
        )
    if tau >= brechas[0]:
        return float(tasas[0])
    if tau <= brechas[-1]:
        return float(tasas[-1])
    # `np.interp` exige x creciente: la brecha crece cuando la tasa baja, así que ambos
    # arrays van invertidos.
    return float(np.interp(tau, brechas[::-1], tasas[::-1]))


def tabla_de_pisos(curvas: pd.DataFrame, taus: np.ndarray = TAUS) -> pd.DataFrame:
    """El piso para una rejilla de tolerancias, precomputado — una fila por (curva, τ).

    Existe para que la regla de diseño tenga **una sola implementación**. El notebook
    necesita mover τ y ver moverse el piso, pero si recalculara la inversión por su cuenta
    podría discrepar del ``evaluabilidad.piso_geocod_tau05`` que este mismo script emite al
    registro, y una vista que contradice al registro es peor que no tener registro. Acá se
    calcula una vez; allá se busca.
    """
    filas = [
        {"curva": curva, "tau": float(t), "piso": piso_de_evaluabilidad(sub, float(t))}
        for curva, sub in curvas.groupby("curva")
        for t in taus
    ]
    return pd.DataFrame(filas).sort_values(["curva", "tau"], ignore_index=True)


# ─── emisión ──────────────────────────────────────────────────────────────────
def build() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Devuelve (por_semilla, curvas agregadas, penalidad selectiva, tabla de pisos)."""
    por_semilla = pd.concat([leer_uniforme(), leer_selectiva()], ignore_index=True)
    curvas = agregar(por_semilla)
    verificar_replica(curvas)
    return por_semilla, curvas, penalidad_selectiva(por_semilla), tabla_de_pisos(curvas)


def emitir(
    curvas: pd.DataFrame,
    penalidad: pd.DataFrame,
    por_semilla: pd.DataFrame,
    script: str = __file__,
) -> None:
    """Emite al registro las cifras portantes. El README las tabula todas."""
    fuentes = [FUENTE_UNIFORME, FUENTE_SELECTIVA]

    def _emit(family: str, value: float, *, variant: str, unit: str, estimator: str) -> None:
        canon.emit(
            family, float(value), variant=variant, unit=unit, estimator=estimator,
            inputs=fuentes, script=script,
        )

    paper = curvas[curvas["curva"] == CURVA_PAPER].set_index("rate")
    faltan = set(NIVELES_PAPER) - set(paper.index)
    if faltan:
        raise ValueError(
            f"{FUENTE_UNIFORME.name} ya no trae los niveles {sorted(faltan)}; el README "
            "los tabula por sufijo canónico y quedaría citando entradas que nadie emite"
        )

    # La curva entera va al registro, no solo los extremos: el README la tabula, y una
    # cifra tabulada es tan portante como una en prosa. El drift no distingue.
    etiqueta = {
        "medible": ("rho_medible", "ρ intra-distrital macro contra el oráculo DEGRADADO"),
        "real": ("rho_real", "ρ intra-distrital macro contra el oráculo COMPLETO"),
        "persistencia": ("rho_persistencia", "ρ de la línea base de persistencia degradada"),
        "brecha": ("brecha", "ρ real − ρ medible: el error de medición"),
        "ventaja": ("ventaja", "ρ medible − ρ persistencia: lo que el analista ve ganar"),
    }
    for tasa, sufijo in NIVELES_PAPER.items():
        fila = paper.loc[tasa]
        for col, (fam, unidad) in etiqueta.items():
            _emit(
                f"evaluabilidad.{fam}_{sufijo}", fila[col],
                variant="uniforme",
                unit=f"{unidad} (adim.)",
                estimator=(
                    f"media sobre {int(fila['n_semillas'])} semillas a tasa {tasa:.1%}, "
                    f"adelgazamiento binomial uniforme desde {TASA_LIMA:.1%} "
                    f"({FUENTE_UNIFORME.name})"
                ),
            )

    # Trujillo tiene nivel propio porque su tasa está MEDIDA en el segundo CSV (24.9 %), no
    # interpolada desde el 25 % del primero. Las dos variantes se emiten y la policy elige
    # la selectiva como canónica: es la cota empírica, y citar la optimista por defecto
    # sería elegir el número más cómodo.
    for curva, variante in ((CURVA_PAREADA, "uniforme"), (CURVA_SELECTIVA, "selectivo")):
        fila = curvas[(curvas["curva"] == curva) & (curvas["rate"] == TASA_TRUJILLO)]
        if fila.empty:
            raise ValueError(
                f"la curva {curva} no trae el nivel {TASA_TRUJILLO:.1%}; es el nivel de "
                "Trujillo y el README lo cita nominalmente"
            )
        fila = fila.iloc[0]
        for col, (fam, unidad) in etiqueta.items():
            _emit(
                f"evaluabilidad.{fam}_trujillo", fila[col],
                variant=variante,
                unit=f"{unidad} (adim.)",
                estimator=(
                    f"media sobre {int(fila['n_semillas'])} semillas a la tasa real de "
                    f"Trujillo ({TASA_TRUJILLO:.1%}), pérdida {variante} "
                    f"({FUENTE_SELECTIVA.name})"
                ),
            )

    pen = penalidad[penalidad["rate"] == TASA_TRUJILLO].iloc[0]
    for col, fam in (("d_medible", "penalidad_medible"), ("d_real", "penalidad_real")):
        _emit(
            f"evaluabilidad.{fam}_trujillo", pen[col],
            variant="selectivo",
            unit="Δρ selectivo − uniforme (adim.; negativo = la cota uniforme era optimista)",
            estimator=(
                f"diferencia pareada por semilla sobre {int(pen['n_semillas'])} semillas "
                f"a {TASA_TRUJILLO:.1%}, misma grilla y mismo script de origen"
            ),
        )

    for curva, variante in ((CURVA_PAPER, "uniforme"), (CURVA_SELECTIVA, "selectivo")):
        piso = piso_de_evaluabilidad(curvas[curvas["curva"] == curva], TAU_REPORTADA)
        _emit(
            "evaluabilidad.piso_geocod_tau05", 100.0 * piso,
            variant=variante,
            unit="% de geocodificación mínimo para que la brecha no supere 0.05 de ρ",
            estimator=(
                f"interpolación lineal de la brecha entre los niveles medidos de la curva "
                f"{curva}; tolerancia elegida τ = {TAU_REPORTADA}"
            ),
        )

    for ciudad, tasa in (("lima", TASA_LIMA), ("trujillo", TASA_TRUJILLO)):
        _emit(
            f"evaluabilidad.tasa_{ciudad}", 100.0 * tasa,
            variant="ciudad",
            unit="% de hechos con coordenada",
            estimator=(
                "nivel de la grilla de degradación, tomado de la columna `rate` del CSV "
                "de origen; no se escribe a mano"
            ),
        )

    _emit(
        "evaluabilidad.pct_seeds_feat_gana", curvas["feat_gana_pct"].min(),
        variant="ambos_mecanismos",
        unit="% de semillas en que el modelo con features supera a persistencia",
        estimator="mínimo de feat_gana sobre todos los niveles y las tres curvas",
    )
    _emit(
        "evaluabilidad.conteo_semillas", por_semilla["seed"].nunique(),
        variant="diseno", unit="semillas por nivel",
        estimator="semillas distintas en los CSV de origen (el nivel base es determinista)",
    )
    _emit(
        "evaluabilidad.conteo_corridas", len(por_semilla),
        variant="diseno", unit="corridas modelo × nivel × semilla",
        estimator="filas de los dos CSV de origen juntos, una por corrida",
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    por_semilla, curvas, penalidad, pisos = build()

    emitir(curvas, penalidad, por_semilla)

    for nombre, df in (("curvas", curvas), ("penalidad", penalidad), ("pisos", pisos)):
        dest = OUT / f"{nombre}.parquet"
        df.to_parquet(dest, index=False)
        print(f"  → {dest}  ({len(df):,} filas)")

    for curva in (CURVA_PAPER, CURVA_SELECTIVA):
        piso = piso_de_evaluabilidad(curvas[curvas["curva"] == curva], TAU_REPORTADA)
        print(f"     piso τ={TAU_REPORTADA} · {curva}: {piso:.1%} de geocodificación")


if __name__ == "__main__":
    main()
