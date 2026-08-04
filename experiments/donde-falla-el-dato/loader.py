"""Precómputo de `donde-falla-el-dato`: cobertura y calidad geocodificadora por celda.

Este experimento no mide crimen. Mide **cuánto se puede creer el mapa** en cada celda,
y por eso su tabla de salida es una tabla de ausencias tanto como de presencias: la
grilla canónica entera, con las celdas sin registro presentes como filas explícitas.
Filtrarlas acá haría imposible dibujarlas deshilachadas después, que es justo lo único
que este experimento tiene que lograr.

Dos ejes de desconfianza, deliberadamente **sin colapsar en un índice**:

- **soporte** — cuántos registros geocodificados sostienen la celda.
- **calidad** — qué tan bien geocodifica el distrito al que pertenece la celda.

Combinarlos en un score ponderado sería inventar una cifra portante con pesos elegidos
a mano, exactamente lo que ``inwatch.canon`` existe para impedir. Se dejan separados y
el notebook pone un piso a cada uno.

**La calidad es distrital, no celular.** ``real_coord_ratio`` viene por fila en el
artefacto de origen, pero es constante dentro de cada ubigeo (verificado: un solo valor
distinto en los 39 distritos observados). Se propaga a todas las celdas del distrito y
se nombra ``*_distrito`` para que ningún consumidor pueda confundirlo con resolución
celular. Fingir grano celular sobre una medida distrital es el mismo error, un piso más
abajo, que el mapa de denuncias fingiendo ser un mapa de crimen.

Contrato de salida: unidad ``h3_8``, clave ``h3_index``, una fila por celda de la grilla
canónica, cobertura junto al valor, sin geometría. Ver ``design/contrato-unidades.md``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from inwatch import canon

SLUG = "donde-falla-el-dato"
# Read-only. El repo de origen nunca se modifica desde acá.
SOURCE = Path("/home/rosewt-dell/Code/tesis/infelix/data/silver")
OUT = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG

ADMIN = SOURCE / "h3_features" / "h3_admin.parquet"
OBSERVADO = SOURCE / "h3_features" / "h3_observed_geocoded.parquet"
AUDITORIA = SOURCE / "analysis" / "geocode_success_distrito.csv"
MATRIZ = SOURCE / "h3_feature_matrix.parquet"

# Ubigeos citados nominalmente en el README, por el contraste con la cifra huérfana.
UBIGEO_ATE = "150103"
UBIGEO_MIRAFLORES = "150122"

# Las tres medidas de calidad geocodificadora. NO son intercambiables: sus rangos no
# se solapan y elegir una cambia qué significa "confiable". El notebook las ofrece
# como toggle en vez de decidir por el lector.
MEDIDAS = {
    "geo_exito_distrito": "geocodificación exitosa",
    "geo_con_coord_distrito": "registro con alguna coordenada",
    "geo_coord_real_distrito": "coordenada real (no imputada)",
}

# Precedencia del motivo: de la falla más profunda a la más superficial. Una celda sin
# ubigeo no puede heredar auditoría distrital, y una sin auditoría no puede evaluarse
# aunque tenga registros — por eso `sin_auditoria` gana sobre `sin_registro`.
MOTIVOS = ("sin_ubigeo", "sin_auditoria", "sin_registro", "observado")


def leer_grilla(admin: Path = ADMIN, matriz: Path = MATRIZ) -> pd.DataFrame:
    """Grilla canónica H3 res-8 de Lima + Callao, con su adscripción administrativa.

    Verifica contra ``h3_feature_matrix`` en vez de confiar: la grilla es el
    denominador de todas las cifras de cobertura del experimento, y un denominador
    equivocado convierte cada porcentaje en una mentira precisa.
    """
    adm = pd.read_parquet(admin, columns=["h3_index", "ubigeo", "distrito", "departamento"])
    celdas_matriz = set(pd.read_parquet(matriz, columns=["h3_index"])["h3_index"])
    if set(adm["h3_index"]) != celdas_matriz:
        raise ValueError(
            f"la grilla de {admin.name} ({adm['h3_index'].nunique():,} celdas) no coincide "
            f"con la de {matriz.name} ({len(celdas_matriz):,}); "
            "no hay grilla canónica y el experimento no tiene denominador"
        )
    return adm


def leer_observado(observado: Path = OBSERVADO) -> pd.DataFrame:
    return pd.read_parquet(
        observado, columns=["h3_index", "ubigeo", "year", "crime_cat", "obs_geo_count",
                            "real_coord_ratio"]
    )


def leer_auditoria(auditoria: Path = AUDITORIA) -> pd.DataFrame:
    return pd.read_csv(auditoria, dtype={"ubigeo": str})


def resumir_soporte(obs: pd.DataFrame) -> pd.DataFrame:
    """Soporte por celda: cuántos registros, y repartidos en cuántos años y categorías.

    Los tres juntos porque no dicen lo mismo. Doscientos registros de una sola
    categoría en un solo año y doscientos repartidos en cinco años sostienen la misma
    celda con muy distinta fuerza.
    """
    return (
        obs.groupby("h3_index", as_index=False)
        .agg(
            soporte_registros=("obs_geo_count", "sum"),
            soporte_anios=("year", "nunique"),
            soporte_categorias=("crime_cat", "nunique"),
        )
    )


def calidad_distrital(obs: pd.DataFrame, aud: pd.DataFrame) -> pd.DataFrame:
    """Una fila por ubigeo con las tres medidas de calidad geocodificadora.

    ``real_coord_ratio`` sale del artefacto observado, donde viene replicado por fila;
    se verifica que sea realmente constante por distrito antes de colapsarlo, porque
    si dejara de serlo el ``first`` estaría eligiendo un valor al azar.
    """
    ratio = obs.dropna(subset=["ubigeo"]).groupby("ubigeo")["real_coord_ratio"]
    if (ratio.nunique() > 1).any():
        malos = sorted(ratio.nunique()[lambda s: s > 1].index)
        raise ValueError(
            f"real_coord_ratio dejó de ser constante por ubigeo en {malos}; "
            "ya no es una medida distrital y no se puede propagar como tal"
        )
    cal = ratio.first().rename("geo_coord_real_distrito").reset_index()

    aud = aud.assign(
        geo_exito_distrito=aud["exito_geo"],
        geo_con_coord_distrito=1.0 - aud["sin_coord"],
    )
    return aud[["ubigeo", "n_geo", "geo_exito_distrito", "geo_con_coord_distrito"]].merge(
        cal, on="ubigeo", how="outer"
    )


def construir(grilla: pd.DataFrame, obs: pd.DataFrame, aud: pd.DataFrame) -> pd.DataFrame:
    """Tabla del experimento: una fila por celda de la grilla canónica.

    `left join` sobre la grilla, preservando NaN. Un 0 de registros y un "no
    observado" son cosas distintas: el soporte se rellena con 0 porque cero registros
    ES el dato, mientras que la calidad se queda en NaN porque no medida no es cero.
    """
    # El origen usa "" para las celdas que ningún polígono distrital reclama. La
    # normalización va acá y no en el lector porque es acá donde ocurre el `merge`:
    # un string vacío se une en silencio y le regalaría auditoría distrital a una
    # celda que no pertenece a ningún distrito. NA no se une. Es la prohibición del
    # join implícito de `design/contrato-unidades.md`, aplicada donde puede violarse.
    grilla = grilla.copy()
    for col in ("ubigeo", "distrito", "departamento"):
        grilla[col] = grilla[col].replace("", pd.NA)

    soporte = resumir_soporte(obs)
    calidad = calidad_distrital(obs, aud)

    df = grilla.merge(soporte, on="h3_index", how="left").merge(calidad, on="ubigeo", how="left")

    conteos = ["soporte_registros", "soporte_anios", "soporte_categorias"]
    df[conteos] = df[conteos].fillna(0)

    df["tiene_registro"] = df["soporte_registros"] > 0
    # La auditoría distrital es lo que permite EVALUAR la calidad. Sin ella no se
    # afirma que el dato sea malo: se afirma que no se sabe, que es distinto y peor.
    df["tiene_auditoria"] = df["geo_exito_distrito"].notna()
    df["evaluable"] = df["tiene_registro"] & df["tiene_auditoria"]

    df["motivo"] = pd.Categorical(
        pd.Series("observado", index=df.index)
        .mask(~df["tiene_registro"], "sin_registro")
        .mask(~df["tiene_auditoria"], "sin_auditoria")
        .mask(df["ubigeo"].isna(), "sin_ubigeo"),
        categories=MOTIVOS,
        ordered=True,
    )

    df = df.astype(
        {
            "h3_index": "string",
            "ubigeo": "string",
            "distrito": "string",
            "departamento": "string",
            "soporte_registros": "int32",
            "soporte_anios": "int16",
            "soporte_categorias": "int16",
            "n_geo": "float32",
            **dict.fromkeys(MEDIDAS, "float32"),
        }
    )
    return df.sort_values("h3_index", ignore_index=True)


def _pct(mask: pd.Series) -> float:
    """Porcentaje de la grilla, en puntos porcentuales (no proporción)."""
    return 100.0 * float(mask.mean())


def emitir(df: pd.DataFrame, aud: pd.DataFrame, script: str = __file__) -> None:
    """Emite al registro las cifras portantes del experimento.

    Se emiten en **puntos porcentuales**, no en proporción, porque es la forma en que
    se leen en prosa. Guardar 0.345 y escribir "34,5 %" al lado reabre justo la
    rendija de divergencia que el registro cierra.
    """
    fuentes = [ADMIN, OBSERVADO, AUDITORIA]

    def _emit(family: str, value: float, *, variant: str, unit: str, estimator: str) -> None:
        canon.emit(
            family, value, variant=variant, unit=unit, estimator=estimator,
            inputs=fuentes, script=script,
        )

    n = len(df)
    # Los conteos también son cifras portantes: el README los cita para sostener los
    # porcentajes, y un denominador escrito a mano que se desincroniza es exactamente
    # el fallo del que nació este registro.
    _emit(
        "conteo.celdas_grilla", float(n),
        variant="grilla_canonica", unit="celdas H3 res-8",
        estimator=f"celdas de la grilla canónica Lima+Callao ({ADMIN.name})",
    )
    _emit(
        "conteo.celdas_con_registro", float(df["tiene_registro"].sum()),
        variant="grilla_canonica", unit="celdas H3 res-8",
        estimator="celdas con >=1 registro policial geocodificado",
    )
    _emit(
        "conteo.distritos_sin_auditoria",
        float(df.loc[~df["tiene_auditoria"], "distrito"].dropna().nunique()),
        variant="distrito", unit="distritos",
        estimator=f"distritos de la grilla ausentes de {AUDITORIA.name}",
    )
    _emit(
        "cobertura.celdas_con_registro", _pct(df["tiene_registro"]),
        variant="grilla_canonica", unit="% de celdas de la grilla canónica",
        estimator=f"celdas con >=1 registro geocodificado / {n} celdas H3 res-8 Lima+Callao",
    )
    _emit(
        "cobertura.celdas_sin_auditoria", _pct(~df["tiene_auditoria"]),
        variant="grilla_canonica", unit="% de celdas de la grilla canónica",
        estimator=f"celdas cuyo distrito no aparece en {AUDITORIA.name} / {n} celdas",
    )
    _emit(
        "cobertura.celdas_evaluables", _pct(df["evaluable"]),
        variant="grilla_canonica", unit="% de celdas de la grilla canónica",
        estimator=f"celdas con registro Y auditoría distrital / {n} celdas",
    )
    for depto, clave in (("Lima", "lima"), ("Callao", "callao")):
        sub = df[df["departamento"] == depto]
        _emit(
            f"cobertura.celdas_con_registro_{clave}", _pct(sub["tiene_registro"]),
            variant="grilla_canonica", unit="% de celdas del departamento",
            estimator=f"celdas con >=1 registro geocodificado / {len(sub)} celdas de {depto}",
        )

    _emit(
        "conteo.celdas_auditadas", float(df["tiene_auditoria"].sum()),
        variant="grilla_canonica", unit="celdas H3 res-8",
        estimator=f"celdas cuyo distrito aparece en {AUDITORIA.name}",
    )

    # Los extremos de las tres medidas, no solo de la primera: el README las tabula a
    # las tres, y una cifra tabulada es tan portante como una en prosa.
    por_distrito = df.dropna(subset=["ubigeo"]).drop_duplicates("ubigeo")
    for col, etiqueta in MEDIDAS.items():
        serie = por_distrito[col].dropna() * 100.0
        est = f"{etiqueta}: extremo sobre {len(serie)} distritos con la medida disponible"
        sufijo = col.removeprefix("geo_").removesuffix("_distrito")
        for extremo, valor in (("min", serie.min()), ("max", serie.max())):
            _emit(f"geocode.{sufijo}_{extremo}", float(valor), variant="distrito",
                  unit="% de registros del distrito", estimator=est)

    exito = aud.set_index("ubigeo")["exito_geo"] * 100.0
    est = f"tasa distrital de geocodificación exitosa, {AUDITORIA.name} ({len(aud)} distritos)"
    for family, valor in (
        ("geocode.exito_ate", exito.loc[UBIGEO_ATE]),
        ("geocode.exito_miraflores", exito.loc[UBIGEO_MIRAFLORES]),
    ):
        _emit(family, float(valor), variant="distrito", unit="% de registros del distrito",
              estimator=est)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    obs = leer_observado()
    aud = leer_auditoria()
    df = construir(leer_grilla(), obs, aud)

    emitir(df, aud)

    dest = OUT / f"{SLUG}.parquet"
    df.to_parquet(dest, index=False)
    print(f"  → {dest}  ({len(df):,} filas)")
    print("     " + " · ".join(f"{m}: {c:,}" for m, c in df["motivo"].value_counts().items()))


if __name__ == "__main__":
    main()
