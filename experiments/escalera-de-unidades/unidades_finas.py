"""Paneles de la escalera en ``manzana`` y ``morfologica``: de los puntos a la unidad.

Vive aparte de ``loader.py`` porque trae geopandas y pyproj, y la reproducción en
``h3_8`` no los necesita: si la parte geográfica se rompe, la cifra de origen se sigue
pudiendo rehacer.

Tres decisiones que cambian el resultado y por eso son visibles:

- **El target se rehace desde los puntos**, con la limpieza del oráculo de origen
  (``build_observed_h3_points.py``: solo denuncias, CON COORDENADA, bbox, anti-centroide
  a más de 30 por coordenada exacta). ``puntos_limpios`` agregados a H3 tienen que dar
  el oráculo **exacto**; hay un test que lo exige, porque si no, la diferencia entre
  unidades podría venir de la limpieza y no de la unidad.
- **La manzana es un centroide, no un polígono.** La capa INEI que tiene infelix trae
  solo ``_lat``/``_lng`` por manzana. Un punto se asigna a la manzana cuyo centroide
  está más cerca, hasta ``RADIO_MANZANA_M``; más lejos queda sin unidad y se cuenta.
  Es una tesselación de Voronoi implícita: aproxima la manzana, no la dibuja.
- **Los features que no existen a la escala fina se heredan.** Cada manzana y cada
  celda morfológica toma las fuentes del hexágono que la contiene (la manzana por su
  centroide, la celda por el hexágono con mayor ``frac_tess``). El bloque de manzana
  censal sí es nativo en ``manzana`` y viene de la manzana más cercana en
  ``morfologica``. Consecuencia: dentro de un hexágono, las fuentes heredadas son
  constantes y **no pueden** ordenar unidades; su escalón fino mide cuánto ayuda el
  contexto del hexágono, no la fuente a esa escala.

El distrito de evaluación es siempre el ``ubigeo`` que la matriz le da al hexágono, en
las tres unidades. Así los ρ intra-distritales se promedian sobre los mismos grupos y
lo único que cambia entre unidades es qué se ordena dentro de cada uno.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

# Sin `import loader`: ese nombre lo usan otros experimentos y, en una misma sesión de
# pytest, el primero en importarse gana. Las categorías llegan como argumento.
LOGGER = logging.getLogger("escalera-de-unidades")

CRS_METRICO = "EPSG:32718"
RADIO_MANZANA_M = 150.0
MAX_POR_COORD = 30
YEAR_MIN, YEAR_MAX = 2018, 2024
LAT_MIN, LAT_MAX = -12.45, -11.55
LNG_MIN, LNG_MAX = -77.30, -76.60
TEJIDO = Path(__file__).resolve().parents[2] / "data" / "silver" / "tejido-vs-hexagono"
SOURCE_COLS = ["solo_denuncia", "estado_coord", "id_dist_hecho", "lat_hecho", "long_hecho",
               "año_hecho", "tipo_hecho", "subtipo_hecho", "modalidad_hecho"]


def map_category(tipo: pd.Series, subtipo: pd.Series, modalidad: pd.Series) -> pd.Series:
    """Crosswalk SIDPOL → 5 categorías, copia de ``build_observed_h3_points.py``."""
    t = tipo.fillna("").str.upper()
    s = subtipo.fillna("").str.upper()
    m = modalidad.fillna("").str.upper()
    cat = pd.Series(np.nan, index=tipo.index, dtype=object)
    patrimonio = t == "PATRIMONIO (DELITO)"
    cat[patrimonio & s.isin(["ROBO", "HURTO"])] = "robo_hurto_callejero"
    cat[patrimonio & (s == "ESTAFA Y OTRAS DEFRAUDACIONES")] = "estafa"
    cat[patrimonio & (s == "EXTORSION")] = "extorsion"
    ley_mujer = t == "LEY DE VIOLENCIA CONTRA LA MUJER Y GRUPOS VULNERABLES"
    viol_sexual = (t == "LIBERTAD (DELITO)") & (s == "VIOLACION DE LA LIBERTAD SEXUAL")
    cat[ley_mujer | viol_sexual] = "violencia_familiar_sexual"
    cat[m.str.contains("SECUESTRO", na=False)] = "secuestro"
    return cat


def limpiar_puntos(df: pd.DataFrame, celdas: set[str], max_por_coord: int = MAX_POR_COORD
                   ) -> pd.DataFrame:
    """La limpieza del oráculo sobre un DataFrame con las columnas de ``SOURCE_COLS``."""
    import h3

    df = df[df["solo_denuncia"] == 1].copy()
    df["year"] = pd.to_numeric(df["año_hecho"], errors="coerce")
    df = df[(df["year"] >= YEAR_MIN) & (df["year"] <= YEAR_MAX)]
    df["year"] = df["year"].astype(int)
    df["ubigeo_hecho"] = df["id_dist_hecho"].astype(str).str.zfill(6)
    df["crime_cat"] = map_category(df["tipo_hecho"], df["subtipo_hecho"], df["modalidad_hecho"])
    df = df[df["crime_cat"].notna()]
    geo = df[df["estado_coord"].astype(str).str.upper() == "CON COORDENADA"].copy()
    geo["lat"] = pd.to_numeric(geo["lat_hecho"], errors="coerce")
    geo["lng"] = pd.to_numeric(geo["long_hecho"], errors="coerce")
    geo = geo[geo["lat"].between(LAT_MIN, LAT_MAX) & geo["lng"].between(LNG_MIN, LNG_MAX)]
    pile = geo.groupby(["lat", "lng"]).size()
    malas = pile[pile > max_por_coord].index
    if len(malas):
        idx = pd.MultiIndex.from_arrays([geo["lat"], geo["lng"]])
        geo = geo[~idx.isin(malas)]
    geo["h3_index"] = [h3.latlng_to_cell(a, b, 8) for a, b in
                       zip(geo["lat"].to_numpy(), geo["lng"].to_numpy(), strict=True)]
    geo = geo[geo["h3_index"].isin(celdas)]
    cols = ["lat", "lng", "h3_index", "ubigeo_hecho", "year", "crime_cat"]
    return geo[cols].reset_index(drop=True)


def puntos_limpios(source: Path) -> pd.DataFrame:
    """Puntos de denuncia limpios en los 4172 hexágonos de la matriz, como el oráculo."""
    import pyarrow.parquet as pq

    from inwatch import fuentes

    celdas = set(pq.read_table(fuentes.ruta("h3_feature_matrix"), columns=["h3_index"])
                 .column("h3_index").to_pylist())
    pts = limpiar_puntos(pd.read_parquet(source, columns=SOURCE_COLS), celdas)
    LOGGER.info("puntos limpios en la grilla: %d", len(pts))
    return pts


def a_metrico(lng: np.ndarray, lat: np.ndarray) -> np.ndarray:
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", CRS_METRICO, always_xy=True)
    x, y = tr.transform(lng, lat)
    return np.column_stack([x, y])


def atributos_manzana(raw: pd.DataFrame) -> pd.DataFrame:
    """El bloque de manzana por manzana, con las fórmulas de ``fetch_inei_manzana_h3.py``.

    Allá se suman sobre el hexágono; acá cada manzana es su propia fila. ``pobnbi`` es
    un porcentaje (0–100) en esta capa, no un conteo: se convierte igual que en origen.
    """
    import h3

    df = raw.dropna(subset=["_lat", "_lng"]).copy()
    for c in ["pobtotal", "pobnbi", "poph", "pobm", "vivienda"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
        df.loc[df[c] >= 9_999_999, c] = np.nan
    pop = df["pobtotal"].fillna(0)
    nbi = df["pobnbi"].where(df["pobnbi"].between(0, 100), np.nan)
    nbi_pop = (pop * nbi.fillna(0) / 100.0).fillna(0)
    total = pop.replace(0, np.nan)
    out = pd.DataFrame({
        "mzn_id": df["OBJECTID"].astype(str).to_numpy(),
        "lat": df["_lat"].to_numpy(), "lng": df["_lng"].to_numpy(),
        "mzn_pop_total": pop.to_numpy(),
        "mzn_nbi_pop": nbi_pop.to_numpy(),
        "mzn_nbi_pct": (nbi_pop / total).fillna(0.0).to_numpy(),
        "mzn_vivienda": df["vivienda"].fillna(0).to_numpy(),
        "mzn_pop_hombres_pct": (df["poph"].fillna(0) / total).fillna(0.5).to_numpy(),
    })
    out["h3_index"] = [h3.latlng_to_cell(a, b, 8) for a, b in
                       zip(out["lat"].to_numpy(), out["lng"].to_numpy(), strict=True)]
    return out


def asignar_cercano(xy_pts: np.ndarray, xy_uni: np.ndarray, radio: float | None
                    ) -> np.ndarray:
    """Índice de la unidad más cercana por punto; −1 si está a más de ``radio``."""
    from scipy.spatial import cKDTree

    d, i = cKDTree(xy_uni).query(xy_pts, k=1)
    if radio is not None:
        i = np.where(d <= radio, i, -1)
    return i


def contar(pts: pd.DataFrame, key: str, cats: list[str]) -> pd.DataFrame:
    """Conteos ancho: una fila por (unidad, año), una columna ``target__<cat>``."""
    c = (pts.groupby([key, "year", "crime_cat"]).size().unstack("crime_cat", fill_value=0)
         .reindex(columns=cats, fill_value=0))
    c.columns = [f"target__{k}" for k in c.columns]
    return c.reset_index()


def ensamblar(unidades: pd.DataFrame, key: str, feat: pd.DataFrame, nativas: list[str],
              conteos: pd.DataFrame, cats: list[str]) -> pd.DataFrame:
    """Unidad × año con features heredados del hexágono, nativos encima y targets."""
    years = sorted(feat["year"].unique())
    heredar = [c for c in feat.columns if c not in ("h3_index", "year") and c not in nativas]
    base = unidades[[key, "h3_index"] + nativas].merge(pd.DataFrame({"year": years}), how="cross")
    base = base.merge(feat[["h3_index", "year"] + heredar], on=["h3_index", "year"], how="inner")
    base = base.merge(conteos, on=[key, "year"], how="left")
    tcols = [f"target__{k}" for k in cats]
    base[tcols] = base[tcols].fillna(0).astype("float32")
    num = [c for c in base.columns if c not in (key, "h3_index", "ubigeo", "year") + tuple(tcols)]
    base[num] = base[num].astype("float32")
    return base.sort_values([key, "year"], kind="stable").reset_index(drop=True)


def panel(unidad: str, pts: pd.DataFrame, feat: pd.DataFrame, cats: list[str]
          ) -> tuple[pd.DataFrame, str, dict]:
    """Panel ancho de una unidad fina y su diagnóstico de asignación."""
    from inwatch import fuentes

    celdas = set(feat["h3_index"].unique())
    mz = atributos_manzana(pd.read_parquet(fuentes.ruta("inei_manzana_lima")))
    mz = mz[mz["h3_index"].isin(celdas)].reset_index(drop=True)
    xy_pts = a_metrico(pts["lng"].to_numpy(), pts["lat"].to_numpy())
    xy_mz = a_metrico(mz["lng"].to_numpy(), mz["lat"].to_numpy())
    nativas = ["mzn_pop_total", "mzn_nbi_pop", "mzn_nbi_pct", "mzn_vivienda", "mzn_pop_hombres_pct"]

    if unidad == "manzana":
        i = asignar_cercano(xy_pts, xy_mz, RADIO_MANZANA_M)
        p = pts.assign(mzn_id=np.where(i >= 0, mz["mzn_id"].to_numpy()[np.maximum(i, 0)], None))
        diag = {"unidades": int(len(mz)), "puntos": int(len(p)),
                "puntos_sin_unidad": int((i < 0).sum()), "radio_m": RADIO_MANZANA_M}
        p = p[p["mzn_id"].notna()]
        return (ensamblar(mz, "mzn_id", feat, nativas, contar(p, "mzn_id", cats), cats),
                "mzn_id", diag)

    if unidad == "morfologica":
        import geopandas as gpd

        geo = pd.read_parquet(TEJIDO / "tejido_geometria.parquet")
        # La geometría guardada por `tejido-vs-hexagono` está en grados (EPSG:4326),
        # aunque se construyó en métrico: se reproyecta antes de medir nada.
        tess = gpd.GeoDataFrame(geo[["tess_id"]], geometry=gpd.GeoSeries.from_wkb(
            geo["geometry_wkb"]), crs="EPSG:4326").to_crs(CRS_METRICO)
        corr = pd.read_parquet(TEJIDO / "correspondencia_h3_tejido.parquet")
        dom = (corr.sort_values(["tess_id", "frac_tess"], ascending=[True, False])
               .drop_duplicates("tess_id")[["tess_id", "h3_index"]])
        tess = tess.merge(dom, on="tess_id", how="inner")
        tess = tess[tess["h3_index"].isin(celdas)].reset_index(drop=True)
        gp = gpd.GeoDataFrame(pts[["year", "crime_cat"]].copy(),
                              geometry=gpd.points_from_xy(xy_pts[:, 0], xy_pts[:, 1]),
                              crs=CRS_METRICO)
        j = gpd.sjoin(gp, tess[["tess_id", "geometry"]], how="left", predicate="within")
        j = j[~j.index.duplicated(keep="first")]
        cen = np.column_stack([tess.geometry.centroid.x, tess.geometry.centroid.y])
        k = asignar_cercano(cen, xy_mz, None)
        uni = pd.concat([tess[["tess_id", "h3_index"]],
                         mz[nativas].iloc[k].reset_index(drop=True)], axis=1)
        diag = {"unidades": int(len(uni)), "puntos": int(len(j)),
                "puntos_sin_unidad": int(j["tess_id"].isna().sum())}
        if diag["puntos_sin_unidad"] == diag["puntos"]:
            raise RuntimeError("ningún punto cayó en el tejido: ¿CRS de la geometría?")
        p = pd.DataFrame(j[j["tess_id"].notna()][["tess_id", "year", "crime_cat"]])
        return (ensamblar(uni, "tess_id", feat, nativas, contar(p, "tess_id", cats), cats),
                "tess_id", diag)

    raise ValueError(f"unidad fina desconocida: {unidad}")


def contra_oraculo(pts: pd.DataFrame, oraculo: Path) -> dict:
    """¿Los puntos, agregados como el oráculo, dan el oráculo? Debe ser exacto."""
    cols = ["h3_index", "ubigeo", "year", "crime_cat", "obs_geo_count"]
    o = pd.read_parquet(oraculo, columns=cols)
    o["ubigeo"] = o["ubigeo"].astype(str).str.zfill(6)
    a = (pts.rename(columns={"ubigeo_hecho": "ubigeo"})
         .groupby(["h3_index", "ubigeo", "year", "crime_cat"]).size().rename("aca").reset_index())
    m = o.merge(a, on=["h3_index", "ubigeo", "year", "crime_cat"], how="outer")
    m[["obs_geo_count", "aca"]] = m[["obs_geo_count", "aca"]].fillna(0)
    return {"filas": int(len(m)), "filas_distintas": int((m["obs_geo_count"] != m["aca"]).sum()),
            "total_oraculo": int(m["obs_geo_count"].sum()), "total_aca": int(m["aca"].sum())}
