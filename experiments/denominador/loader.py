"""Precómputo de `denominador` (E7): superficie latente ÷ cuatro poblaciones → parquets.

El experimento existe porque todas las superficies del programa son conteos o densidades
por celda, y todo denominador en uso era residencial. E1 (`observado-latente`) midió que
corregir por sesgo de denuncia escala el mapa sin reordenarlo. Acá se mueve otro control
—quién cuenta como «expuesto»— y se mide con las MISMAS métricas (Spearman y
solapamiento del top-k) para que las dos respuestas queden en una sola escala.

Esta capa existe, como en todo el repo, porque ``marimo`` exporta a WASM sobre Pyodide,
donde ``h3`` no corre. Todo el cómputo ocurre acá; el notebook solo lee.

**Exploratorio: este loader NO emite al registro canónico.** Las métricas quedan en
``reordenamiento.parquet`` y compañía. Emitirlas es una decisión aparte (ver README).

El denominador correcto —persona-horas expuestas— no existe en los datos locales. El proxy
es LandScan Global (población ambiente de 24 h, ~1 km). Ver el README para sus límites.

Contrato de salida:
  - unidad ``h3_8``, clave ``h3_index`` (``str``), una fila por celda de la superficie
  - ``evaluable_<piso>`` viaja junto a cada riesgo: una celda bajo el piso de población
    en cualquiera de las tres fuentes no tiene riesgo cero, tiene riesgo **no evaluable**
  - determinista: bootstrap con semilla fija, orden de filas fijo por ``h3_index``
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from inwatch import fuentes

SLUG = "denominador"
UNIDAD = "h3_8"
OUT = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG

# Read-only. Las dos primeras están en el catálogo; las poblaciones y OSM aún no (pedir
# su alta en registry/fuentes.toml es parte del PR), así que se resuelven por el origen
# `infelix` del catálogo, nunca por una ruta de máquina escrita acá.
REL_INFELIX = {
    "h3_population": "data/silver/h3_features/h3_population.parquet",
    "h3_landscan": "data/silver/h3_features/h3_landscan.parquet",
    "h3_meta_population": "data/silver/h3_features/h3_meta_population.parquet",
    "h3_osm_features": "data/silver/h3_features/h3_osm_features.parquet",
    "crime_latent_surface_hybrid": "data/silver/crime_latent_surface_hybrid.parquet",
}

# nombre → (archivo, columna). `residente` es el baseline; el orden es el de las figuras.
DENOMINADORES = {
    "residente": ("h3_population", "population"),
    "ambiente": ("h3_landscan", "pop_landscan_2023"),
    "residente_meta": ("h3_meta_population", "pop_meta_2020"),
    "ambiente_2020": ("h3_landscan", "pop_landscan_2020"),
}
BASELINE = "residente"
# Las tres que definen la población común de celdas. `ambiente_2020` no entra: es un
# control temporal de `ambiente` y no debe achicar el universo.
PRINCIPALES = ("residente", "ambiente", "residente_meta")

# Fijados en el README antes de calcular. No se tocan después de mirar.
PISOS = (0, 200, 500, 1000, 2000)
PISO_PRIMARIO = 500
TOPS = (25, 50, 100, 200)
TOP_N = 50
N_BOOT = 1000
SEMILLA = 20260925

# Numeradores. `latente` es el pre-registrado (la superficie de E1), pero es CIRCULAR:
# esa superficie reparte el latente distrital a las celdas en proporción a WorldPop, así
# que `latente / residente` es constante dentro de cada distrito (verificado:
# max/min = 1 en los 38 distritos evaluables). Dividirlo por otro denominador reordena
# por construcción. Por eso se añadieron, DESPUÉS del pre-registro y declarado así en el
# README, dos numeradores cuyo patrón intra-distrital no sale de la población:
#   - `latente_hibrido`: superficie híbrida de infelix (slr-us4), patrón intra-distrital
#     de las denuncias geocodificadas con suavizado Dirichlet M=10 hacia la población
#   - `observado_geo`: conteo crudo de denuncias geocodificadas (sin corrección latente)
NUMERADORES = {
    "latente": "latente",
    "observado": "observado",
    "latente_robo": "latente_robo_hurto_callejero",
    "latente_vf": "latente_violencia_familiar_sexual",
    "latente_hibrido": "latente_hibrido",
    "observado_hibrido": "observado_hibrido",
    "observado_geo": "observado_geo",
}
# El control de E1 (observado ↔ latente) reconstruido sobre cada superficie.
E1_PAR = {"latente": "observado", "latente_hibrido": "observado_hibrido"}
# Los que reciben el análisis completo (bootstrap, pares, suavizado, agregación, mapa).
NUM_PRINCIPALES = ("latente", "latente_hibrido", "observado_geo")
# El numerador de la vista principal: el no circular.
NUM_VISTA = "latente_hibrido"

# POI de la sub-predicción direccional («celdas comerciales/nightlife bajan»).
POI_COMERCIAL = ("poi_count_retail", "poi_count_food", "poi_count_nightlife")

# Mesa Redonda (Cercado de Lima), el ejemplo que motiva el bead. Punto aproximado del
# damero comercial entre Jr. Andahuaylas y Jr. Cuzco.
MESA_REDONDA = (-12.0512, -77.0268)


# ─── fuentes ──────────────────────────────────────────────────────────────────
def _ruta_infelix(nombre: str) -> Path:
    cat = fuentes.cargar_catalogo(fuentes.load_config())
    return cat.origenes["infelix"] / REL_INFELIX[nombre]


def rutas_de_entrada() -> dict[str, Path]:
    r = {n: _ruta_infelix(n) for n in REL_INFELIX}
    r["crime_latent_surface"] = fuentes.ruta("crime_latent_surface")
    r["h3_admin"] = fuentes.ruta("h3_admin")
    r["h3_observed_geocoded"] = fuentes.ruta("h3_observed_geocoded")
    return r


# ─── ensamblado ───────────────────────────────────────────────────────────────
def superficie_por_celda(largo: pd.DataFrame) -> pd.DataFrame:
    """Pooled 2018-2024: total latente, observado, y latente de dos categorías."""
    tot = largo.groupby("h3_index", as_index=False)[["latente", "observado"]].sum()
    por_cat = largo.pivot_table(
        index="h3_index", columns="crime_cat", values="latente", aggfunc="sum", fill_value=0.0
    )
    for cat in ("robo_hurto_callejero", "violencia_familiar_sexual"):
        serie = por_cat[cat] if cat in por_cat.columns else pd.Series(dtype=float)
        tot[f"latente_{cat}"] = tot["h3_index"].map(serie).fillna(0.0)
    return tot.sort_values("h3_index", ignore_index=True)


def ensamblar(
    sup: pd.DataFrame, pobl: dict[str, pd.DataFrame], admin: pd.DataFrame, osm: pd.DataFrame
) -> pd.DataFrame:
    """Una fila por celda de la superficie, con las cuatro poblaciones y los riesgos.

    El riesgo se deja en NaN —no en cero, no en infinito— donde el denominador es 0. Qué
    celdas son evaluables lo decide ``evaluable_<piso>``, no el valor del riesgo.
    """
    df = sup.merge(admin[["h3_index", "ubigeo", "distrito"]], on="h3_index", how="left")
    for nombre, (archivo, col) in DENOMINADORES.items():
        p = pobl[archivo][["h3_index", col]].rename(columns={col: f"pob_{nombre}"})
        df = df.merge(p, on="h3_index", how="left")
        df[f"pob_{nombre}"] = df[f"pob_{nombre}"].fillna(0.0)
    df["poi_comercial"] = (
        df[["h3_index"]]
        .merge(osm[["h3_index", *POI_COMERCIAL]], on="h3_index", how="left")[list(POI_COMERCIAL)]
        .fillna(0)
        .sum(axis=1)
        .to_numpy()
    )
    for num, col in NUMERADORES.items():
        for den in DENOMINADORES:
            p = df[f"pob_{den}"]
            df[f"r_{num}__{den}"] = np.where(p > 0, df[col] / p.where(p > 0), np.nan)
    for piso in PISOS:
        df[f"evaluable_{piso}"] = poblacion_comun(df, piso)
    df["cociente_amb_res"] = np.where(
        df["pob_residente"] > 0,
        df["pob_ambiente"] / df["pob_residente"].where(df["pob_residente"] > 0),
        np.nan,
    )
    return df.sort_values("h3_index", ignore_index=True)


def poblacion_comun(df: pd.DataFrame, piso: float) -> pd.Series:
    """Celdas con denominador > piso (y > 0) en las tres fuentes principales.

    La misma población para todas las comparaciones: si cada denominador eligiera sus
    propias celdas, la ρ mezclaría reordenamiento con cambio de universo.
    """
    m = pd.Series(True, index=df.index)
    for den in PRINCIPALES:
        m &= df[f"pob_{den}"] > max(piso, 0)
    return m


# ─── las métricas de reordenamiento (las de E1) ───────────────────────────────
def top_overlap(ids: pd.Series, a: pd.Series, b: pd.Series, k: int) -> float:
    """|topk(a) ∩ topk(b)| / k. Empates resueltos por h3_index para ser deterministas."""
    d = pd.DataFrame({"id": ids.to_numpy(), "a": a.to_numpy(), "b": b.to_numpy()})
    ta = set(d.sort_values(["a", "id"], ascending=[False, True]).head(k)["id"])
    tb = set(d.sort_values(["b", "id"], ascending=[False, True]).head(k)["id"])
    return len(ta & tb) / k


def comparar(ids: pd.Series, a: pd.Series, b: pd.Series, tops=TOPS) -> dict[str, float]:
    """Spearman, Kendall τ-b y solapamiento del top-k entre dos rankings de las mismas celdas."""
    out = {
        "spearman": float(stats.spearmanr(a, b).statistic),
        "kendall": float(stats.kendalltau(a, b).statistic),
        "n": float(len(a)),
    }
    for k in tops:
        out[f"top{k}"] = top_overlap(ids, a, b, k) if len(a) >= k else np.nan
    return out


def reordenamiento(df: pd.DataFrame) -> pd.DataFrame:
    """Tabla larga: piso × numerador × contraste → métricas.

    Contrastes, todos sobre la misma población de celdas del piso:
      - ``<den>``: riesgo por ``den`` contra riesgo por residente (el baseline)
      - ``correccion_sesgo``: E1 en la misma población —observado vs latente, ambos por
        residente—, para que el «no reordena» de E1 y esto se lean en la misma escala
      - ``conteo``: riesgo por residente contra el conteo latente crudo (cuánto reordena
        dividir, a secas)
    """
    filas = []
    for piso in PISOS:
        sub = df[df[f"evaluable_{piso}"]]
        for num in NUMERADORES:
            base = sub[f"r_{num}__{BASELINE}"]
            for den in DENOMINADORES:
                if den == BASELINE:
                    continue
                filas.append(
                    {
                        "piso": piso,
                        "numerador": num,
                        "contraste": den,
                        **comparar(sub["h3_index"], base, sub[f"r_{num}__{den}"]),
                    }
                )
            if num in E1_PAR:
                obs = E1_PAR[num]
                filas.append(
                    {
                        "piso": piso,
                        "numerador": num,
                        "contraste": "correccion_sesgo",
                        **comparar(sub["h3_index"], sub[f"r_{obs}__{BASELINE}"], base),
                    }
                )
                filas.append(
                    {
                        "piso": piso,
                        "numerador": num,
                        "contraste": "conteo",
                        **comparar(sub["h3_index"], sub[NUMERADORES[num]], base),
                    }
                )
    return pd.DataFrame(filas)


def _spearman_rapido(ra: np.ndarray, rb: np.ndarray) -> float:
    return float(np.corrcoef(ra, rb)[0, 1])


def bootstrap(
    df: pd.DataFrame,
    piso: int = PISO_PRIMARIO,
    n_boot: int = N_BOOT,
    semilla: int = SEMILLA,
    num: str = "latente",
) -> pd.DataFrame:
    """IC 95 % por remuestreo de celdas para ρ(ambiente), ρ(residente_meta) y su diferencia.

    Es el test de la falsificación incorporada: si el control residencial reordena tanto
    como el ambiente, la diferencia cruza cero y la conclusión se cae.
    """
    sub = df[df[f"evaluable_{piso}"]]
    base = sub[f"r_{num}__{BASELINE}"].to_numpy()
    amb = sub[f"r_{num}__ambiente"].to_numpy()
    met = sub[f"r_{num}__residente_meta"].to_numpy()
    rng = np.random.default_rng(semilla)
    n = len(sub)
    reps = np.empty((n_boot, 3))
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        rb, ra, rm = (stats.rankdata(x[idx]) for x in (base, amb, met))
        r_amb, r_met = _spearman_rapido(rb, ra), _spearman_rapido(rb, rm)
        reps[i] = (r_amb, r_met, r_met - r_amb)
    filas = []
    for j, nombre in enumerate(("rho_ambiente", "rho_residente_meta", "dif_meta_menos_ambiente")):
        lo, hi = np.quantile(reps[:, j], [0.025, 0.975])
        filas.append(
            {
                "piso": piso,
                "numerador": num,
                "estadistico": nombre,
                "media": float(reps[:, j].mean()),
                "ic_low": float(lo),
                "ic_high": float(hi),
                "n_boot": n_boot,
                "n": n,
            }
        )
    return pd.DataFrame(filas)


def pares(df: pd.DataFrame, piso: int = PISO_PRIMARIO, num: str = "latente") -> pd.DataFrame:
    """Matriz completa denominador × denominador (Spearman y top-50) en el piso primario.

    Incluye los controles que el baseline no muestra: LandScan 2020 vs 2023 (ruido
    temporal del mismo producto) y ambiente vs el OTRO residencial.
    """
    sub = df[df[f"evaluable_{piso}"]]
    filas = []
    dens = list(DENOMINADORES)
    for i, a in enumerate(dens):
        for b in dens[i + 1 :]:
            m = comparar(sub["h3_index"], sub[f"r_{num}__{a}"], sub[f"r_{num}__{b}"], tops=(TOP_N,))
            filas.append({"piso": piso, "numerador": num, "a": a, "b": b, **m})
    return pd.DataFrame(filas)


def suavizado(df: pd.DataFrame, previas=(100, 500, 2000), num: str = "latente") -> pd.DataFrame:
    """Alternativa al piso: riesgo = latente / (pob + m), sin descartar celdas.

    Un prior aditivo encoge hacia cero los riesgos de celdas con poca población en vez de
    sacarlas del universo. Si el reordenamiento dependiera de qué celdas deja fuera el
    piso, acá se vería. Universo: celdas con población > 0 en las tres fuentes.
    """
    sub = df[df["evaluable_0"]]
    filas = []
    for m in previas:
        r = {d: sub[NUMERADORES[num]] / (sub[f"pob_{d}"] + m) for d in DENOMINADORES}
        for d in DENOMINADORES:
            if d == BASELINE:
                continue
            filas.append(
                {
                    "previa": m,
                    "numerador": num,
                    "contraste": d,
                    **comparar(sub["h3_index"], r[BASELINE], r[d], tops=(TOP_N,)),
                }
            )
    return pd.DataFrame(filas)


def agregado(df: pd.DataFrame, nivel: str, num: str = "latente") -> pd.DataFrame:
    """Las mismas métricas a unidades más gruesas: H3 res-7 (~5 km²) y distrito.

    Es el complemento del kill-criterion: si el desacuerdo ambiente-vs-residente fuera
    solo desalineación entre el píxel de ~1 km y el hexágono de ~0,7 km², debería
    evaporarse al agregar. Pisos escalados a la unidad (×7 para res-7).
    """
    cols = [NUMERADORES[num], *(f"pob_{d}" for d in DENOMINADORES)]
    if nivel == "h3_7":
        import h3

        clave = df["h3_index"].map(lambda c: h3.cell_to_parent(c, 7))
        pisos = (0, 3500)
    else:
        clave = df["ubigeo"]
        pisos = (0, 10000)
    g = df.assign(_u=clave).groupby("_u", as_index=False)[cols].sum().sort_values("_u")
    filas = []
    for piso in pisos:
        m = pd.Series(True, index=g.index)
        for d in PRINCIPALES:
            m &= g[f"pob_{d}"] > max(piso, 0)
        sub = g[m]
        r = {d: sub[NUMERADORES[num]] / sub[f"pob_{d}"] for d in DENOMINADORES}
        tops = (10,) if nivel == "distrito" else (TOP_N,)
        for d in DENOMINADORES:
            if d == BASELINE:
                continue
            filas.append(
                {
                    "nivel": nivel,
                    "piso": piso,
                    "numerador": num,
                    "contraste": d,
                    **comparar(sub["_u"], r[BASELINE], r[d], tops=tops),
                }
            )
    return pd.DataFrame(filas)


# ─── kill-criterion de resolución ─────────────────────────────────────────────
def varianza_intra(valores: pd.Series, grupos: pd.Series) -> float:
    """Fracción de la varianza de ``log1p(valores)`` que queda dentro de los grupos."""
    x = np.log1p(valores.astype(float))
    total = float(((x - x.mean()) ** 2).sum())
    if total == 0:
        return np.nan
    dentro = float(((x - x.groupby(grupos).transform("mean")) ** 2).sum())
    return dentro / total


def auditoria_resolucion(df: pd.DataFrame, vecinos: pd.DataFrame | None = None) -> pd.DataFrame:
    """¿LandScan a ~1 km conserva contraste intra-distrital en celdas de ~0,7 km²?

    Por fuente: fracción de valores distintos, varianza intra-distrital de log(1+pob), y
    —si se pasan vecinos— fracción de celdas que repiten exactamente el valor de algún
    vecino (la huella del píxel de 1 km partido en varios hexágonos).
    """
    filas = []
    pos = df[df["pob_residente"].gt(0) | df["pob_ambiente"].gt(0)]
    for den in DENOMINADORES:
        col = f"pob_{den}"
        f = {
            "denominador": den,
            "n_celdas": float(len(df)),
            "frac_distintos": df[col].nunique() / len(df),
            "frac_cero": float((df[col] <= 0).mean()),
            "var_intra_distrito": varianza_intra(df[col], df["ubigeo"]),
            "var_intra_distrito_pobladas": varianza_intra(pos[col], pos["ubigeo"]),
        }
        if vecinos is not None:
            v = dict(zip(df["h3_index"], df[col], strict=True))
            rep = vecinos.assign(a=vecinos["h3_index"].map(v), b=vecinos["vecino"].map(v))
            rep = rep[(rep["a"] > 0)]
            f["frac_repite_vecino"] = float(
                rep.assign(eq=np.isclose(rep["a"], rep["b"])).groupby("h3_index")["eq"].any().mean()
            )
        filas.append(f)
    return pd.DataFrame(filas)


def vecinos_de(indices: pd.Series) -> pd.DataFrame:
    import h3  # local: Pyodide no lo soporta (ver docstring del módulo)

    ids = set(indices)
    filas = [(c, n) for c in indices for n in h3.grid_disk(c, 1) if n != c and n in ids]
    return pd.DataFrame(filas, columns=["h3_index", "vecino"])


# ─── dónde diverge ────────────────────────────────────────────────────────────
def cambio_de_rango(
    df: pd.DataFrame, piso: int = PISO_PRIMARIO, num: str = NUM_VISTA
) -> pd.DataFrame:
    """Percentil de riesgo por residente y por ambiente, y su diferencia, por celda evaluable.

    ``delta_rango > 0``: la celda SUBE en riesgo al contar a los expuestos en vez de los
    residentes.
    """
    sub = df[df[f"evaluable_{piso}"]].copy()
    sub["pct_residente"] = sub[f"r_{num}__{BASELINE}"].rank(pct=True)
    sub["pct_ambiente"] = sub[f"r_{num}__ambiente"].rank(pct=True)
    sub["delta_rango"] = sub["pct_ambiente"] - sub["pct_residente"]
    sub["numerador"] = num
    return sub[
        [
            "numerador",
            "h3_index",
            "ubigeo",
            "distrito",
            "pct_residente",
            "pct_ambiente",
            "delta_rango",
            "poi_comercial",
            "cociente_amb_res",
        ]
    ].reset_index(drop=True)


def circularidad(df: pd.DataFrame, piso: int = PISO_PRIMARIO) -> pd.DataFrame:
    """Cuánto del riesgo por residente es solo distrito, por numerador.

    ``var_intra_distrito`` de log(riesgo por residente) = 0 significa que el riesgo es
    constante dentro de cada distrito: el numerador fue repartido con WorldPop y el mapa
    por residente es una coropleta distrital disfrazada de hexágonos.
    """
    sub = df[df[f"evaluable_{piso}"]]
    filas = []
    for num in NUMERADORES:
        x = sub[f"r_{num}__{BASELINE}"]
        ok = x > 0
        filas.append(
            {
                "numerador": num,
                "piso": piso,
                "var_intra_distrito": varianza_intra(
                    np.expm1(np.log(x[ok])), sub.loc[ok, "ubigeo"]
                ),
                "frac_ceros": float((~ok).mean()),
            }
        )
    return pd.DataFrame(filas)


def intra_distrito(
    df: pd.DataFrame, piso: int = PISO_PRIMARIO, min_celdas: int = 10
) -> pd.DataFrame:
    """ρ residente-vs-ambiente DENTRO de cada distrito, mediana ponderada por celdas.

    Separa las dos escalas del reordenamiento: entre distritos (la que el numerador
    circular sí puede mostrar) y entre celdas de un mismo distrito.
    """
    sub = df[df[f"evaluable_{piso}"]]
    filas = []
    for num in NUM_PRINCIPALES:
        for den in ("ambiente", "residente_meta"):
            rhos, ns = [], []
            for _, g in sub.groupby("ubigeo"):
                if len(g) < min_celdas:
                    continue
                a, b = g[f"r_{num}__{BASELINE}"], g[f"r_{num}__{den}"]
                if a.nunique() < 2 or b.nunique() < 2:
                    rhos.append(np.nan)
                else:
                    rhos.append(float(stats.spearmanr(a, b).statistic))
                ns.append(len(g))
            r = np.array(rhos, dtype=float)
            w = np.array(ns, dtype=float)
            ok = ~np.isnan(r)
            filas.append(
                {
                    "numerador": num,
                    "contraste": den,
                    "n_distritos": int(len(r)),
                    "n_distritos_definidos": int(ok.sum()),
                    "rho_media_ponderada": float(np.average(r[ok], weights=w[ok]))
                    if ok.any()
                    else np.nan,
                }
            )
    return pd.DataFrame(filas)


def direccional(cambio: pd.DataFrame, n_boot: int = N_BOOT, semilla: int = SEMILLA) -> pd.DataFrame:
    """La sub-predicción: ρ(Δrango, POI comerciales) debería ser negativa. Con IC bootstrap."""
    rng = np.random.default_rng(semilla + 1)
    x = cambio["delta_rango"].to_numpy()
    y = cambio["poi_comercial"].to_numpy()
    rho = float(stats.spearmanr(x, y).statistic)
    n = len(x)
    reps = []
    for _ in range(n_boot):
        i = rng.integers(0, n, n)
        reps.append(_spearman_rapido(stats.rankdata(x[i]), stats.rankdata(y[i])))
    lo, hi = np.quantile(reps, [0.025, 0.975])
    con_poi = cambio["poi_comercial"] > 0
    return pd.DataFrame(
        [
            {
                "numerador": cambio["numerador"].iloc[0],
                "rho_delta_vs_poi": rho,
                "ic_low": float(lo),
                "ic_high": float(hi),
                "n": n,
                "delta_medio_con_poi": float(cambio.loc[con_poi, "delta_rango"].mean()),
                "delta_medio_sin_poi": float(cambio.loc[~con_poi, "delta_rango"].mean()),
                "n_con_poi": int(con_poi.sum()),
            }
        ]
    )


def por_distrito(cambio: pd.DataFrame) -> pd.DataFrame:
    g = cambio.groupby(["numerador", "ubigeo", "distrito"], as_index=False).agg(
        n=("h3_index", "size"),
        delta_mediano=("delta_rango", "median"),
        cociente_mediano=("cociente_amb_res", "median"),
        poi_total=("poi_comercial", "sum"),
    )
    return g.sort_values(["numerador", "delta_mediano"], ignore_index=True)


def celda_de(lat: float, lng: float) -> str:
    import h3

    return h3.latlng_to_cell(lat, lng, 8)


def fronteras(indices: pd.Series) -> pd.DataFrame:
    """Vértices de cada hexágono en formato largo (mismo contrato que `observado-latente`)."""
    import h3

    filas = []
    for idx in indices:
        for k, (lat, lng) in enumerate(h3.cell_to_boundary(idx)):
            filas.append((idx, k, lng, lat))
    return pd.DataFrame(filas, columns=["h3_index", "vertice", "lng", "lat"]).astype(
        {"vertice": "int16"}
    )


# ─── orquestación ─────────────────────────────────────────────────────────────
def build() -> dict[str, pd.DataFrame]:
    r = rutas_de_entrada()
    sup = superficie_por_celda(pd.read_parquet(r["crime_latent_surface"]))
    hib = superficie_por_celda(pd.read_parquet(r["crime_latent_surface_hybrid"]))
    for col in ("latente", "observado"):
        sup[f"{col}_hibrido"] = sup["h3_index"].map(hib.set_index("h3_index")[col]).fillna(0.0)
    # Universo = celdas de la superficie. Denuncias geocodificadas fuera de ella no entran,
    # para que los tres numeradores se comparen sobre las mismas celdas.
    geo = pd.read_parquet(r["h3_observed_geocoded"]).groupby("h3_index")["obs_geo_count"].sum()
    sup["observado_geo"] = sup["h3_index"].map(geo).fillna(0.0).astype(float)
    pobl = {
        n: pd.read_parquet(r[n]) for n in ("h3_population", "h3_landscan", "h3_meta_population")
    }
    admin = pd.read_parquet(r["h3_admin"])
    osm = pd.read_parquet(r["h3_osm_features"])
    celdas = ensamblar(sup, pobl, admin, osm)
    cambio = pd.concat([cambio_de_rango(celdas, num=n) for n in NUM_PRINCIPALES], ignore_index=True)

    # La auditoría de resolución se hace sobre la GRILLA completa (4172), no solo sobre
    # la superficie: el kill-criterion es sobre el raster, no sobre el delito.
    grilla = admin[["h3_index", "ubigeo"]].copy()
    for nombre, (archivo, col) in DENOMINADORES.items():
        grilla[f"pob_{nombre}"] = (
            grilla["h3_index"].map(pobl[archivo].set_index("h3_index")[col]).fillna(0.0)
        )
    grilla = grilla.sort_values("h3_index", ignore_index=True)

    mr = celda_de(*MESA_REDONDA)
    ev = celdas[celdas[f"evaluable_{PISO_PRIMARIO}"]]
    mesa = []
    if mr in set(ev["h3_index"]):
        for num in NUM_PRINCIPALES:
            for den in DENOMINADORES:
                pct = ev[f"r_{num}__{den}"].rank(pct=True)[ev["h3_index"] == mr].iloc[0]
                mesa.append(
                    {
                        "h3_index": mr,
                        "numerador": num,
                        "denominador": den,
                        "poblacion": float(ev.loc[ev["h3_index"] == mr, f"pob_{den}"].iloc[0]),
                        "percentil_riesgo": float(pct),
                    }
                )
    mesa = pd.DataFrame(
        mesa, columns=["h3_index", "numerador", "denominador", "poblacion", "percentil_riesgo"]
    )

    def por_num(f):
        return pd.concat([f(celdas, num=n) for n in NUM_PRINCIPALES], ignore_index=True)

    return {
        "celdas": celdas,
        "fronteras": fronteras(celdas["h3_index"]),
        "reordenamiento": reordenamiento(celdas),
        "bootstrap": pd.concat(
            [bootstrap(celdas, p, num=n) for n in NUM_PRINCIPALES for p in PISOS if p > 0],
            ignore_index=True,
        ),
        "pares": por_num(pares),
        "suavizado": por_num(suavizado),
        "agregado": pd.concat(
            [agregado(celdas, nv, num=n) for n in NUM_PRINCIPALES for nv in ("h3_7", "distrito")],
            ignore_index=True,
        ),
        "circularidad": circularidad(celdas),
        "intra_distrito": intra_distrito(celdas),
        "resolucion": auditoria_resolucion(grilla, vecinos_de(grilla["h3_index"])),
        "cambio_rango": cambio,
        "direccional": pd.concat(
            [direccional(g) for _, g in cambio.groupby("numerador", sort=True)], ignore_index=True
        ),
        "por_distrito": por_distrito(cambio),
        "mesa_redonda": mesa,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for nombre, df in build().items():
        dest = OUT / f"{nombre}.parquet"
        df.to_parquet(dest, index=False)
        print(f"  → {dest}  ({len(df):,} filas)")


if __name__ == "__main__":
    main()
