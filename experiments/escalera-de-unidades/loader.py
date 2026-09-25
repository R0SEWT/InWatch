"""Precómputo de `escalera-de-unidades`: ¿el escalón de manzana sobrevive a cambiar de unidad?

La escalera de atribución del trabajo de origen (``exp_ladder_multiplicity.py`` en
infelix) midió once fuentes de datos, agregadas a hexágonos H3 res-8, y encontró **un
solo escalón significativo**: agregar la manzana censal INEI sobre la demografía
distrital. Sobrevivió corrección Westfall-Young con B=20000. Ese hallazgo es el que
justifica que en este repo la unidad espacial sea un parámetro: si la señal vive en la
manzana, el hexágono podría estar escondiéndola o inventándola.

Pero la escalera se midió **en una sola unidad**. La pregunta de este loader es la que
el trabajo de origen no se hizo: si la misma escalera, con el mismo protocolo, se corre
con la manzana o con la celda morfológica como unidad de evaluación, ¿el escalón sigue
ahí?

Por eso el loader hace dos cosas en este orden, y la primera condiciona a la segunda:

1. **Reproduce la cifra de origen en ``h3_8``.** Mismo panel, mismos modelos, mismo
   bootstrap compartido y misma semilla. Si no la reproduce, las otras unidades no
   significan nada: estarían comparando contra un número que no sabemos rehacer.
   ``reproduccion_h3.parquet`` pone lado a lado lo que dio acá y lo que dice el registro
   de infelix.
2. **Corre la escalera en ``manzana`` y ``morfologica``.** El target se reconstruye
   desde los puntos de denuncia con la misma limpieza que el oráculo de origen, y cada
   punto cae en la unidad que le toca. Los features que no existen a esa escala se
   **heredan** del hexágono que contiene la unidad, y eso se declara: una fuente
   heredada no puede aportar variación dentro del hexágono, así que su escalón en una
   unidad fina mide otra cosa que en ``h3_8``. Ver ``README.md``.

El protocolo estadístico es el de origen sin cambios: ρ de Spearman intra-distrital por
(categoría, distrito), macro sobre categorías, bootstrap **compartido** sobre distritos
(el mismo sorteo alimenta todos los escalones) y Westfall-Young step-down max-t sobre la
familia primaria de tres contrastes. Las funciones son puras y viven arriba; lo que lee
datos vive abajo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

SLUG = "escalera-de-unidades"
OUT = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG

ALPHA = 0.05
SEED = 20260731  # la de origen: sin ella no hay reproducción bit a bit del bootstrap
B_ORIGEN = 20000
TRAIN_YEARS = [2019, 2020, 2021, 2022]
TEST_YEAR = 2023
MIN_CELLS = 5

CATS = [
    "robo_hurto_callejero",
    "extorsion",
    "estafa",
    "violencia_familiar_sexual",
    "secuestro",
]
STEPS = ["M1_demografia", "M1b_manzana", "M2_osm", "M4c_transporte"]
FAMILY_PRIMARY = [
    ("H1 manzana censal", "M1_demografia", "M1b_manzana"),
    ("H2 forma urbana OSM", "M1b_manzana", "M2_osm"),
    ("H3 ocho fuentes (conjunto)", "M1b_manzana", "M4c_transporte"),
]
FAMILY_EXTRA = [("H4 transporte sobre OSM", "M2_osm", "M4c_transporte")]

LOGGER = logging.getLogger(SLUG)

# ─── grupos de features: copia literal de eval_modality_ladder.py (infelix) ────
DEMOGRAPHIC = ["population", "pop_density_km2", "nbi_pct", "poverty_decile", "avg_household_size"]
MANZANA = ["mzn_pop_total", "mzn_nbi_pct", "mzn_nbi_pop", "mzn_vivienda",
           "mzn_pop_hombres_pct", "mzn_n_manzanas"]
OSM = ["road_density_km_km2", "intersection_count", "poi_count_retail", "poi_count_food",
       "poi_count_finance", "poi_count_transport", "poi_count_healthcare",
       "poi_count_education", "poi_count_nightlife", "dist_police_km", "dist_metro_km",
       "dist_brt_km"]
OSM_CENTRALITY = ["road_node_count", "road_edge_count", "road_dead_end_count",
                  "road_dead_end_ratio", "road_articulation_count", "road_articulation_ratio",
                  "road_node_degree_mean", "road_node_degree_max", "road_weighted_degree_km_mean",
                  "road_pagerank_sum", "road_pagerank_mean", "road_pagerank_max",
                  "road_betweenness_approx_mean", "road_betweenness_approx_max",
                  "road_major_edge_count", "road_major_edge_share", "commercial_poi_count",
                  "commercial_corridor_index"]
COFOPRI = ["pcdpi_lotes_count", "pcdpi_niveles_median", "pcdpi_fai", "pcdpi_pct_agua",
           "pcdpi_pct_luz", "pcdpi_pct_desague", "pcdpi_pct_comercial", "pcdpi_pct_residencial",
           "pcdpi_unidades_sum", "cofopri_formalizacion_lotes_count"]
LICENCIAS = ["lic_comercial_total", "lic_restaurantes", "lic_bares", "lic_bancos_financieras",
             "lic_mercados", "lic_nocturno", "lic_talleres", "lic_farmacias"]
MERCADOS = ["mercado_count", "mercado_puestos_fijos_sum", "mercado_puestos_func_sum",
            "mercado_socios_sum", "mercado_puestos_total_sum", "mercado_abarrotes_puestos_sum",
            "mercado_comidas_puestos_sum", "mercado_mayorista_count", "mercado_mixto_count",
            "mercado_licencia_count", "dist_mercado_km"]
EDUCACION = ["edu_service_count", "edu_local_count", "edu_inicial_count", "edu_primaria_count",
             "edu_secundaria_count", "edu_basica_alt_count", "edu_especial_count",
             "edu_superior_count", "edu_cetpro_count", "edu_publica_count", "edu_privada_count",
             "edu_escolarizada_count", "edu_urbana_count", "dist_edu_km", "dist_edu_basica_km",
             "dist_edu_superior_km"]
REMOTE = ["elevation_m", "slope_deg", "elevation_std", "lc_builtup", "lc_bare", "lc_water",
          "lc_trees", "lc_grass", "s2_ndvi_median", "s2_ndbi_median", "s2_valid_pixel_ratio",
          "dnb_mean", "dnb_std"]
META = ["pop_meta_2020", "pop_meta_density_km2"]
SALUD = ["salud_count", "salud_hospital_count", "salud_sin_intern_count", "salud_nivel1_count",
         "salud_nivel2_count", "salud_nivel3_count", "salud_publico_count",
         "salud_privado_count", "dist_salud_km", "dist_hospital_km"]
SEGURIDAD = ["seg_comisaria_count", "seg_camara_count", "seg_serenazgo_count",
             "seg_total_count", "dist_comisaria_km", "dist_camara_km"]
TRANSPORTE = ["trans_paradero_count", "trans_estacion_count", "trans_metro_count",
              "trans_total_count", "dist_paradero_km", "dist_estacion_km"]

_FULL_URBAN = (DEMOGRAPHIC + MANZANA + OSM + OSM_CENTRALITY + COFOPRI + LICENCIAS + MERCADOS
               + EDUCACION + REMOTE + META)
FEATURE_SETS = {
    "M1_demografia": DEMOGRAPHIC,
    "M1b_manzana": DEMOGRAPHIC + MANZANA,
    "M2_osm": DEMOGRAPHIC + MANZANA + OSM,
    "M4c_transporte": _FULL_URBAN + SALUD + SEGURIDAD + TRANSPORTE,
}
ALL_FEATURES = sorted(set(_FULL_URBAN + SALUD + SEGURIDAD + TRANSPORTE))


# ═══ estadística pura (testeable con datos sintéticos) ═════════════════════════
def per_district_rho(te: pd.DataFrame, min_cells: int = MIN_CELLS) -> pd.DataFrame:
    """ρ de Spearman intra-distrital por (categoría, distrito), como en origen.

    Un distrito entra si tiene al menos ``min_cells`` unidades y variación tanto en el
    target como en la predicción: sin variación el ranking no está definido.
    """
    from scipy.stats import spearmanr

    rows = []
    for (cat, ub), g in te.groupby(["crime_cat", "ubigeo"], sort=True):
        if len(g) < min_cells or g["target"].nunique() < 2 or g["pred"].nunique() < 2:
            continue
        rho, _ = spearmanr(g["pred"].to_numpy(float), g["target"].to_numpy(float))
        rows.append({"crime_cat": cat, "ubigeo": ub, "rho": rho, "n_unidades": len(g)})
    return pd.DataFrame(rows, columns=["crime_cat", "ubigeo", "rho", "n_unidades"])


def aligned_rho_matrix(stats: dict[str, pd.DataFrame], steps: list[str] = STEPS
                       ) -> tuple[dict[str, np.ndarray], pd.DataFrame]:
    """Por categoría, matriz (n_distritos × n_escalones) con los distritos comunes a todos."""
    merged = None
    for step in steps:
        s = stats[step][["crime_cat", "ubigeo", "rho"]].rename(columns={"rho": step})
        merged = s if merged is None else merged.merge(s, on=["crime_cat", "ubigeo"], how="inner")
    merged = merged.dropna(subset=steps)
    return {cat: g[steps].to_numpy(float) for cat, g in merged.groupby("crime_cat")}, merged


def shared_bootstrap(mats: dict[str, np.ndarray], B: int, seed: int) -> np.ndarray:
    """(B × n_escalones) del macro-ρ, sorteando distritos UNA vez por réplica y categoría.

    El orden de iteración de ``mats`` es el de ``groupby`` (alfabético por categoría),
    igual que en origen: cambiarlo cambia el sorteo y rompe la reproducción.
    """
    rng = np.random.default_rng(seed)
    n_steps = next(iter(mats.values())).shape[1]
    acc = np.zeros((B, n_steps))
    for R in mats.values():
        n = R.shape[0]
        idx = rng.integers(0, n, size=(B, n))
        acc += R[idx].mean(axis=1)
    return acc / len(mats)


def macro_point(mats: dict[str, np.ndarray]) -> np.ndarray:
    return np.mean([R.mean(axis=0) for R in mats.values()], axis=0)


def westfall_young(t_obs: np.ndarray, t_null: np.ndarray) -> np.ndarray:
    """p ajustados step-down max-t, con monotonía impuesta (sin ella no controla FWER)."""
    k = len(t_obs)
    order = np.argsort(-np.abs(t_obs))
    adj = np.empty(k)
    for pos, j in enumerate(order):
        maxnull = np.abs(t_null[:, order[pos:]]).max(axis=1)
        adj[j] = (1 + np.sum(maxnull >= abs(t_obs[j]))) / (len(t_null) + 1)
    running = 0.0
    for j in order:
        running = max(running, adj[j])
        adj[j] = running
    return adj


def contrastes(stats: dict[str, pd.DataFrame], B: int, seed: int = SEED
               ) -> tuple[pd.DataFrame, dict]:
    """La familia de contrastes con CIs marginal y simultáneo y p Westfall-Young.

    Devuelve una fila por contraste y un dict con los escalares de la familia (c max-t,
    pares alineados, piso del p).
    """
    mats, merged = aligned_rho_matrix(stats)
    point = macro_point(mats)
    draws = shared_bootstrap(mats, B, seed)
    ix = {s: i for i, s in enumerate(STEPS)}
    fam = FAMILY_PRIMARY + FAMILY_EXTRA
    d_obs = np.array([point[ix[a]] - point[ix[b]] for _, b, a in fam])
    d_draws = np.stack([draws[:, ix[a]] - draws[:, ix[b]] for _, b, a in fam], axis=1)
    se = d_draws.std(axis=0, ddof=1)
    t_obs = d_obs / se
    t_null = (d_draws - d_obs) / se
    k = len(FAMILY_PRIMARY)
    p_marg = np.array([(1 + np.sum(np.abs(t_null[:, j]) >= abs(t_obs[j]))) / (B + 1)
                       for j in range(len(fam))])
    p_wy_prim = westfall_young(t_obs[:k], t_null[:, :k])
    p_wy_full = westfall_young(t_obs, t_null)
    c_sim = float(np.percentile(np.abs(t_null[:, :k]).max(axis=1), 100 * (1 - ALPHA)))
    lo_marg = np.percentile(d_draws, 100 * ALPHA / 2, axis=0)
    hi_marg = np.percentile(d_draws, 100 * (1 - ALPHA / 2), axis=0)
    rows = []
    for j, (lab, base, adv) in enumerate(fam):
        prim = j < k
        rows.append({
            "contraste": lab, "base": base, "escalon": adv, "familia_primaria": prim,
            "delta": d_obs[j], "se": se[j],
            "ci_lo": lo_marg[j], "ci_hi": hi_marg[j],
            "sim_lo": d_obs[j] - c_sim * se[j] if prim else np.nan,
            "sim_hi": d_obs[j] + c_sim * se[j] if prim else np.nan,
            "p_marginal": p_marg[j],
            "p_wy": p_wy_prim[j] if prim else p_wy_full[j],
            "p_en_piso": bool(p_marg[j] <= 1 / (B + 1)),
        })
    out = pd.DataFrame(rows)
    out["sobrevive"] = out["familia_primaria"] & (out["p_wy"] < ALPHA)
    fam_info = {"c_sim": c_sim, "n_pares": int(len(merged)), "B": B, "seed": seed,
                "p_piso": 1 / (B + 1),
                "rho_macro": dict(zip(STEPS, point.tolist(), strict=True))}
    return out, fam_info


def fit_predict(panel: pd.DataFrame, feats: list[str], key: str, random_state: int = 42
                ) -> pd.DataFrame:
    """HGB por categoría con los hiperparámetros del ladder de origen.

    ``random_state`` es el único que se deja mover, y se deja mover a propósito: con
    más de 10 000 filas HGB activa early stopping con un split de validación aleatorio,
    así que la semilla decide cuántas iteraciones entrena cada modelo. Origen usa 42.
    """
    from sklearn.ensemble import HistGradientBoostingRegressor

    ancho = "crime_cat" not in panel.columns
    parts = []
    for cat in CATS:
        # Panel largo (h3, como en origen) o ancho (una columna target__<cat> por
        # categoría, para las unidades finas: evita copiar 120 features cinco veces).
        d = panel if ancho else panel[panel["crime_cat"] == cat]
        y = d[f"target__{cat}"] if ancho else d["target"]
        tr_m = d["year"].isin(TRAIN_YEARS).to_numpy()
        te_m = (d["year"] == TEST_YEAR).to_numpy()
        tr = d.loc[tr_m, feats]
        med = tr.median(numeric_only=True)
        m = HistGradientBoostingRegressor(
            max_iter=140, max_leaf_nodes=15, min_samples_leaf=20,
            learning_rate=0.06, l2_regularization=0.05, random_state=random_state,
        )
        m.fit(tr.fillna(med).to_numpy(), np.log1p(y[tr_m].to_numpy(float)))
        te = pd.DataFrame({key: d.loc[te_m, key].to_numpy(),
                           "ubigeo": d.loc[te_m, "ubigeo"].to_numpy(),
                           "crime_cat": cat, "target": y[te_m].to_numpy(float)})
        te["pred"] = np.expm1(np.maximum(m.predict(d.loc[te_m, feats].fillna(med).to_numpy()), 0.0))
        parts.append(te)
    return pd.concat(parts, ignore_index=True)


def escalera(panel: pd.DataFrame, key: str, B: int, seed: int = SEED, random_state: int = 42
             ) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """Corre los cuatro escalones sobre un panel y devuelve (contrastes, familia, ρ)."""
    stats = {}
    for step in STEPS:
        feats = [c for c in FEATURE_SETS[step] if c in panel.columns]
        t0 = time.time()
        stats[step] = per_district_rho(fit_predict(panel, feats, key, random_state))
        LOGGER.info("  %s: %d features, %d pares (cat, distrito), %.0fs",
                    step, len(feats), len(stats[step]), time.time() - t0)
    tab, fam = contrastes(stats, B, seed)
    rho = pd.concat([s.assign(escalon=k) for k, s in stats.items()], ignore_index=True)
    fam["features"] = {s: len([c for c in FEATURE_SETS[s] if c in panel.columns]) for s in STEPS}
    return tab, fam, rho


# ═══ datos ═════════════════════════════════════════════════════════════════════
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cargar_matriz() -> pd.DataFrame:
    """Features por (h3_index, year), como en ``load_panel`` de origen."""
    import pyarrow.parquet as pq

    from inwatch import fuentes

    path = fuentes.ruta("h3_feature_matrix")
    cols = [c for c in ALL_FEATURES if c in pq.read_schema(path).names]
    feat = pd.read_parquet(path, columns=["h3_index", "year", "ubigeo"] + cols)
    feat = feat[feat["ubigeo"].notna() & (feat["ubigeo"].astype(str) != "")].copy()
    feat["ubigeo"] = feat["ubigeo"].astype(str).str.zfill(6)
    return feat


def panel_h3(feat: pd.DataFrame, oracle: pd.DataFrame, modo: str = "origen") -> pd.DataFrame:
    """Panel largo (h3 × año × categoría) con target = conteo geocodificado del oráculo.

    ``modo="origen"`` replica ``load_panel`` de infelix **con su duplicación**, y hay que
    entender por qué existe para no confundirla con un detalle. El oráculo agrupa por
    ``(h3_index, ubigeo, year, crime_cat)``: un hexágono que cruza un límite distrital
    sale en dos filas, una por distrito del hecho, cada una con su conteo parcial. El
    ``merge`` contra la matriz (que tiene una sola fila por hexágono y año) las conserva
    como dos observaciones del mismo hexágono, y el ``merge`` del rezago
    (``persist``, año − 1) las vuelve a multiplicar, 2 × 2. Los escalones de la familia
    no usan ``persist`` como feature, pero ese segundo ``merge`` **sí cambia qué filas
    hay**, y con eso el split de validación del early stopping de HGB y el ρ de cada
    distrito. Sin replicarlo, la cifra de origen no se reproduce (``inwatch-uiv``).

    ``modo="sumado"`` es la versión sin duplicación: una fila por hexágono, con el conteo
    sumado sobre los distritos del hecho. Es la que usan las comparaciones entre
    unidades, porque las unidades finas se construyen así.

    ``modo="propio"`` también deja una fila por hexágono, pero cuenta solo los puntos
    cuyo distrito del hecho coincide con el del hexágono en la matriz (necesita la
    columna ``ubigeo`` en ``oracle``). Es la tercera lectura razonable del borde.
    """
    if modo not in ("origen", "sumado", "propio"):
        raise ValueError(f"modo desconocido: {modo}")
    if modo == "propio":
        # Solo los puntos cuyo distrito del hecho es el que la matriz le da al hexágono:
        # el borde deja de aportar puntos de otro distrito, en vez de sumarlos.
        own = oracle.assign(ubigeo=oracle["ubigeo"].astype(str).str.zfill(6))
        own = own.merge(feat[["h3_index", "year", "ubigeo"]], on=["h3_index", "year", "ubigeo"])
        oracle, modo = own, "sumado"
    panels = []
    for cat in CATS:
        oc = oracle[oracle["crime_cat"] == cat][["h3_index", "year", "obs_geo_count"]]
        if modo == "sumado":
            oc = oc.groupby(["h3_index", "year"], as_index=False, sort=False)["obs_geo_count"].sum()
        b = feat.merge(oc, on=["h3_index", "year"], how="left")
        b["target"] = b["obs_geo_count"].fillna(0.0)
        if modo == "origen":
            lag = oc.assign(year=oc["year"] + 1).rename(columns={"obs_geo_count": "persist"})
            b = b.merge(lag, on=["h3_index", "year"], how="left")
            b = b.drop(columns=["persist"])
        b["crime_cat"] = cat
        panels.append(b.drop(columns=["obs_geo_count"]))
    return pd.concat(panels, ignore_index=True)


def canon_origen() -> dict[str, float]:
    """Las cifras ``ladder_mult.*`` del registro de infelix, leídas (nunca escritas)."""
    from inwatch import fuentes

    raiz = fuentes.ruta("h3_feature_matrix").parents[2]  # <infelix>/data/silver/…
    reg = json.loads((raiz / "analysis" / "canonical_numbers.json").read_text())
    return {k.split(".")[1]: float(v["value"]) for k, v in reg["entries"].items()
            if k.startswith("ladder_mult.") and k.endswith(".shared_boot")}


def reproduccion(tab: pd.DataFrame, fam: dict, origen: dict[str, float]) -> pd.DataFrame:
    """Lado a lado: lo que dio acá contra lo que dice el registro de origen."""
    h1, h2, h3_ = (tab.iloc[i] for i in range(3))
    pares = [
        ("manzana_delta", h1["delta"]),
        ("manzana_sim_lo", h1["sim_lo"]),
        ("manzana_sim_hi", h1["sim_hi"]),
        ("manzana_p_wy", h1["p_wy"]),
        ("osm_p_wy", h2["p_wy"]),
        ("ocho_fuentes_p_wy", h3_["p_wy"]),
        ("simultaneous_crit", fam["c_sim"]),
    ]
    rows = [{"clave": f"ladder_mult.{k}", "origen": origen.get(k, np.nan), "aca": float(v)}
            for k, v in pares]
    out = pd.DataFrame(rows)
    out["dif"] = out["aca"] - out["origen"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--B", type=int, default=B_ORIGEN)
    ap.add_argument("--unidades", default="h3_8,manzana,morfologica")
    ap.add_argument("--semillas", default="0,1,2,3,7",
                    help="random_state de HGB para la sensibilidad ('' la apaga)")
    ap.add_argument("--B-semillas", type=int, default=2000)
    args = ap.parse_args()
    semillas = [int(x) for x in args.semillas.split(",") if x != ""]
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from inwatch import fuentes

    OUT.mkdir(parents=True, exist_ok=True)
    unidades = args.unidades.split(",")
    feat = cargar_matriz()
    tablas, familias, rhos, diagnosticos, sens = [], {}, [], {}, []

    def _correr(unidad: str, panel: pd.DataFrame, key: str) -> None:
        LOGGER.info("unidad %s: %d filas de panel", unidad, len(panel))
        tab, fam, rho = escalera(panel, key, args.B)
        tablas.append(tab.assign(unidad=unidad))
        familias[unidad] = fam
        rhos.append(rho.assign(unidad=unidad))
        for _, r in tab.iterrows():
            LOGGER.info("  %-28s Δ=%+.4f  CI[%+.4f,%+.4f]  p_WY=%.5f",
                        r["contraste"], r["delta"], r["ci_lo"], r["ci_hi"], r["p_wy"])
        for rs in semillas:
            t_s, _, _ = escalera(panel, key, args.B_semillas, random_state=rs)
            sens.append(t_s.assign(unidad=unidad, random_state=rs))
            LOGGER.info("  semilla %d: %s", rs, "  ".join(
                f"{d:+.3f}(p{p:.3f})" for d, p in zip(t_s["delta"], t_s["p_wy"], strict=True)))

    if "h3_8" in unidades:
        oracle = pd.read_parquet(fuentes.ruta("h3_observed_geocoded"),
                                 columns=["h3_index", "year", "crime_cat", "obs_geo_count"])
        _correr("h3_8_origen", panel_h3(feat, oracle, "origen"), "h3_index")
        rep = reproduccion(tablas[-1], familias["h3_8_origen"], canon_origen())
        rep.to_parquet(OUT / "reproduccion_h3.parquet", index=False)
        print(rep.to_string(index=False))
        _correr("h3_8", panel_h3(feat, oracle, "sumado"), "h3_index")
        oracle_ub = pd.read_parquet(fuentes.ruta("h3_observed_geocoded"),
                                    columns=["h3_index", "ubigeo", "year", "crime_cat",
                                             "obs_geo_count"])
        _correr("h3_8_propio", panel_h3(feat, oracle_ub, "propio"), "h3_index")

    finas = [u for u in unidades if u != "h3_8"]
    if finas:
        import unidades_finas  # noqa: PLC0415  (vecino de este archivo; trae geopandas)

        puntos = unidades_finas.puntos_limpios(fuentes.ruta("denuncias_lima"))
        chequeo = unidades_finas.contra_oraculo(puntos, fuentes.ruta("h3_observed_geocoded"))
        LOGGER.info("puntos vs oráculo: %s", chequeo)
        diagnosticos["puntos_vs_oraculo"] = chequeo
        for u in finas:
            panel, key, diag = unidades_finas.panel(u, puntos, feat)
            diagnosticos[u] = diag
            LOGGER.info("  asignación %s: %s", u, diag)
            _correr(u, panel, key)
            del panel

    pd.concat(tablas, ignore_index=True).to_parquet(OUT / "contrastes.parquet", index=False)
    pd.concat(rhos, ignore_index=True).to_parquet(OUT / "rho_por_distrito.parquet", index=False)
    if sens:
        pd.concat(sens, ignore_index=True).to_parquet(OUT / "semillas.parquet", index=False)
    meta = {
        "B": args.B, "seed": SEED, "familias": familias, "diagnosticos": diagnosticos,
        "semillas": semillas, "B_semillas": args.B_semillas,
        "inputs_sha256": {n: _sha256(fuentes.ruta(n))
                          for n in ("h3_feature_matrix", "h3_observed_geocoded",
                                    "denuncias_lima", "inei_manzana_lima")},
    }
    (OUT / "familias.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"  → {OUT}")


if __name__ == "__main__":
    main()
