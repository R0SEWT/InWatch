"""Precómputo de `observado-latente`: superficie H3 cruda → dos parquets listos para presentar.

Esta capa existe porque ``marimo`` exporta a WASM sobre Pyodide, donde ``h3`` y
geopandas **no corren**. Todo lo pesado ocurre acá, una vez; el notebook solo lee.

Dos artefactos, no uno, y la separación la manda ``design/contrato-unidades.md``:
"sin geometría en las tablas de features". La tabla de features queda geometry-free y
los vértices de cada hexágono viven en un parquet aparte que la capa de presentación
mira como diccionario. El contrato dice que la geometría "se reconstruye al dibujar" —
acá se reconstruye una vez, en el loader, porque la única alternativa sería que el
notebook importe ``h3``, y ese import es exactamente lo que Pyodide no soporta.

Contrato de salida:
  - unidad ``h3_8``, clave ``h3_index`` (``str``), una fila por celda
  - las columnas de cobertura (``sin_registro``, ``ic_ancho_rel``, ``share_inestable``)
    viajan al lado de las de valor, nunca sin ellas
  - determinista: dos corridas sobre los mismos inputs dan el mismo ``inputs_sha256``
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from inwatch import canon

SLUG = "observado-latente"
UNIDAD = "h3_8"

# Read-only. El repo de origen nunca se modifica desde acá — ver CLAUDE.md, "Frontera dura".
SOURCE = Path("/home/rosewt-dell/Code/tesis/infelix/data/silver")
FUENTE = SOURCE / "crime_latent_surface.parquet"
OUT = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG

# Orden fijo y explícito: el de la figura del repo de origen, de mayor a menor peso
# observado. Sin esto la composición se reordena sola entre corridas y el gráfico
# apilado deja de ser comparable con la figura publicada.
CATEGORIAS = [
    "robo_hurto_callejero",
    "violencia_familiar_sexual",
    "extorsion",
    "secuestro",
    "estafa",
]

# Cuántas celdas del tope se comparan entre ranking observado y ranking latente.
# 50 sobre 1.593 celdas con registro: el orden de magnitud de "dónde patrullar".
TOP_N = 50


# ─── agregación ───────────────────────────────────────────────────────────────
def por_celda(largo: pd.DataFrame) -> pd.DataFrame:
    """Colapsa la tabla larga (celda × año × categoría) a una fila por celda.

    Pooled sobre 2018–2024 y sobre las cinco categorías, que es la escala a la que el
    multiplicador del repo de origen está estimado. Devuelve totales, desagregado por
    categoría para la composición, y las columnas de cobertura.
    """
    tot = (
        largo.groupby("h3_index", as_index=False)
        .agg(
            ubigeo=("ubigeo", "first"),
            observado=("observado", "sum"),
            latente=("latente", "sum"),
            latente_ic_low=("latente_ic_low", "sum"),
            latente_ic_high=("latente_ic_high", "sum"),
        )
        .sort_values("h3_index", ignore_index=True)
    )

    # Peso de las categorías marcadas inestables (r̂ < 0.05) dentro del latente de la
    # celda. Es lo que decide si la celda se puede pintar o hay que declararla no
    # evaluable: una celda cuyo latente es casi todo estafa no es un dato, es un rumor.
    inest = (
        largo.assign(lat_inest=largo["latente"].where(largo["inestable"] == 1, 0.0))
        .groupby("h3_index", as_index=False)["lat_inest"]
        .sum()
    )
    tot = tot.merge(inest, on="h3_index", how="left")
    tot["share_inestable"] = np.where(
        tot["latente"] > 0, tot["lat_inest"] / tot["latente"], np.nan
    )
    tot = tot.drop(columns="lat_inest")

    # Ancho relativo del IC. Maneja la opacidad: intervalo ancho → celda desvaída.
    tot["ic_ancho_rel"] = np.where(
        tot["latente"] > 0,
        (tot["latente_ic_high"] - tot["latente_ic_low"]) / tot["latente"],
        np.nan,
    )

    # `sin_registro` NO es "cero delito". Es "la policía no registró nada acá en siete
    # años". Se dibuja deshilachada; ver la regla dura 1 en CLAUDE.md.
    tot["sin_registro"] = tot["observado"] <= 0

    # Composición: una columna por categoría y superficie. El desagregado se queda acá
    # porque el punto del experimento es que el ranking casi no se mueve mientras la
    # composición sí — y eso solo se ve con las dos al lado.
    ancho = (
        largo.pivot_table(
            index="h3_index",
            columns="crime_cat",
            values=["observado", "latente"],
            aggfunc="sum",
            fill_value=0.0,
        )
        .reindex(columns=pd.MultiIndex.from_product([["observado", "latente"], CATEGORIAS]))
        .fillna(0.0)
    )
    ancho.columns = [f"{sup}_{cat}" for sup, cat in ancho.columns]
    tot = tot.merge(ancho.reset_index(), on="h3_index", how="left")

    for col in tot.columns:
        if tot[col].dtype == "float64":
            tot[col] = tot[col].astype("float32")
    return tot


def fronteras(indices: pd.Series) -> pd.DataFrame:
    """Vértices de cada hexágono, en formato largo: una fila por (celda, vértice).

    Formato largo y no listas anidadas a propósito: un parquet de listas de structs es
    frágil de leer entre versiones de pyarrow, y la capa de presentación necesita
    agrupar de todos modos. ``vertice`` fija el orden del anillo — sin él, un
    ``groupby`` que reordene dibuja el polígono cruzado.
    """
    # Import local a propósito: `h3` es la dependencia que Pyodide no soporta, y
    # dejarla arriba haría que importar este módulo desde un test sin el extra `geo`
    # fallara por una función que ese test no usa.
    import h3

    filas = []
    for idx in indices:
        for k, (lat, lng) in enumerate(h3.cell_to_boundary(idx)):
            filas.append((idx, k, lng, lat))
    return pd.DataFrame(filas, columns=["h3_index", "vertice", "lng", "lat"]).astype(
        {"vertice": "int16", "lng": "float64", "lat": "float64"}
    )


# ─── el hallazgo, medido ──────────────────────────────────────────────────────
def estabilidad_de_rango(celdas: pd.DataFrame, top_n: int = TOP_N) -> dict[str, float]:
    """Cuánto reordena el mapa la corrección. Spearman y solapamiento del tope.

    Se calcula **solo sobre las celdas con registro**. Incluir las 924 celdas donde
    observado y latente valen ambos cero infla la correlación con empates que no
    significan acuerdo, sino ausencia de dato en las dos superficies.
    """
    con_dato = celdas.loc[~celdas["sin_registro"], ["h3_index", "observado", "latente"]]
    rho = float(con_dato["observado"].corr(con_dato["latente"], method="spearman"))
    a = set(con_dato.nlargest(top_n, "observado")["h3_index"])
    b = set(con_dato.nlargest(top_n, "latente")["h3_index"])
    return {
        "spearman": rho,
        "top_overlap": len(a & b) / top_n,
        "n_con_registro": float(len(con_dato)),
        "n_celdas": float(len(celdas)),
    }


def composicion(largo: pd.DataFrame) -> pd.DataFrame:
    """Share porcentual de cada categoría en cada superficie, pooled sobre todo Lima.

    Índice = categoría; columnas = ``observado``, ``latente``, ``multiplicador``.
    """
    g = largo.groupby("crime_cat")[["observado", "latente"]].sum().reindex(CATEGORIAS)
    out = (g / g.sum() * 100.0).rename(columns=lambda c: f"share_{c}")
    out["multiplicador"] = g["latente"] / g["observado"]
    return out


# ─── emisión ──────────────────────────────────────────────────────────────────
def build() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Devuelve (celdas, fronteras, composición)."""
    largo = pd.read_parquet(FUENTE)
    celdas = por_celda(largo)
    return celdas, fronteras(celdas["h3_index"]), composicion(largo)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    celdas, bordes, comp = build()
    rango = estabilidad_de_rango(celdas)

    inputs = [FUENTE]
    # Todas las cifras portantes del experimento salen de acá, con procedencia. Ninguna
    # se copia a mano al README ni al notebook — ese fue el fallo que originó el
    # registro (ver el docstring de canon/registry.py).
    for cat, fila in comp.iterrows():
        canon.emit(
            f"multiplier.{cat}",
            float(fila["multiplicador"]),
            variant="victim",
            unit="latente/observado (adim.)",
            estimator=(
                "pooled Σλ*/Σy 2018-2024 sobre la superficie H3 Lima+Callao, "
                "r̂ EB victim-level"
            ),
            inputs=inputs,
            script=__file__,
        )
        for sup in ("observado", "latente"):
            canon.emit(
                f"superficie_share_{sup}.{cat}",
                float(fila[f"share_{sup}"]),
                variant="celda_pooled",
                unit="% de la superficie (5 cats, incl. violencia familiar)",
                estimator=(
                    f"Σ{sup} de la categoría / Σ{sup} total, pooled 2018-2024, "
                    "celdas H3 res-8 de Lima+Callao"
                ),
                inputs=inputs,
                script=__file__,
            )

    canon.emit(
        "multiplier.total",
        float(celdas["latente"].sum() / celdas["observado"].sum()),
        variant="victim",
        unit="latente/observado (adim.)",
        estimator="pooled Σλ*/Σy 2018-2024, las 5 categorías juntas, superficie H3 Lima+Callao",
        inputs=inputs,
        script=__file__,
    )
    canon.emit(
        "rango_espacial.spearman",
        rango["spearman"],
        variant="celda_pooled",
        unit="ρ de Spearman entre superficie observada y latente (adim.)",
        estimator=f"corr de rangos sobre las {rango['n_con_registro']:.0f} celdas con registro",
        inputs=inputs,
        script=__file__,
    )
    canon.emit(
        "rango_espacial.top_overlap",
        rango["top_overlap"],
        variant="celda_pooled",
        unit=f"fracción del top-{TOP_N} compartida entre ambos rankings (adim.)",
        estimator=f"|top{TOP_N}(observado) ∩ top{TOP_N}(latente)| / {TOP_N}, celdas con registro",
        inputs=inputs,
        script=__file__,
    )
    # La población va en la clave; la definición operativa, en el estimator. Estas tres
    # cuentan sobre la SUPERFICIE (2517 celdas), no sobre la grilla canónica (4172) que
    # usa `donde-falla-el-dato`. Y el predicado es "Σobservado > 0", que NO es el
    # "registro policial geocodificado" de `conteo.celdas_con_registro`. Reusar esa
    # palabra fue lo que hizo parecer que 1439 y 1593 se contradecían, cuando miden
    # cosas distintas sobre universos distintos.
    canon.emit(
        "conteo.celdas_superficie_sin_observado",
        rango["n_celdas"] - rango["n_con_registro"],
        variant="celda_pooled",
        unit="celdas H3 res-8 sin una sola denuncia registrada en 2018-2024",
        estimator="conteo de celdas con Σobservado == 0 sobre las 5 categorías",
        inputs=inputs,
        script=__file__,
    )
    # Se emite aunque `conteo.celdas_auditadas` valga hoy lo mismo (2517) y se haya
    # verificado que es el MISMO conjunto de h3_index, no solo el mismo total. Son dos
    # mediciones de poblaciones definidas por caminos independientes; mantenerlas
    # separadas deja la coincidencia como sensor: si un re-run las separa, la superficie
    # dejó de cubrir exactamente lo auditado y el registro lo delata. Citar una desde la
    # otra ahorraría una línea al precio de apagar esa alarma.
    canon.emit(
        "conteo.celdas_superficie",
        rango["n_celdas"],
        variant="celda_pooled",
        unit="celdas H3 res-8 de la superficie latente de origen",
        estimator="conteo de h3_index distintos en la superficie de origen",
        inputs=inputs,
        script=__file__,
    )
    canon.emit(
        "conteo.celdas_superficie_con_observado",
        rango["n_con_registro"],
        variant="celda_pooled",
        unit="celdas H3 res-8 con al menos una denuncia registrada en 2018-2024",
        estimator="conteo de celdas con Σobservado > 0 sobre las 5 categorías",
        inputs=inputs,
        script=__file__,
    )
    # El techo de la escala compartida es una cifra portante: decide cuánto del mapa
    # queda en el primer escalón de color. Si se cita en un doc, se cita desde acá.
    canon.emit(
        "escala.pico_latente",
        float(celdas["latente"].max()),
        variant="celda_pooled",
        unit="hechos latentes acumulados 2018-2024 en la celda más cargada",
        estimator="máximo de Σλ* por celda H3 res-8",
        inputs=inputs,
        script=__file__,
    )
    canon.emit(
        "escala.tope",
        float(np.quantile(celdas["latente"].to_numpy(dtype=float), 0.995)),
        variant="celda_pooled",
        unit="hechos latentes: tope de la rampa de color compartida",
        estimator="percentil 99.5 del latente por celda; la barra lleva flecha de desborde",
        inputs=inputs,
        script=__file__,
    )

    salidas = (("celdas", celdas), ("fronteras", bordes), ("composicion", comp.reset_index()))
    for nombre, df in salidas:
        dest = OUT / f"{nombre}.parquet"
        df.to_parquet(dest, index=False)
        print(f"  → {dest}  ({len(df):,} filas)")


if __name__ == "__main__":
    main()
