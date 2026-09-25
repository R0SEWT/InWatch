"""Chequeo posterior (literatura) de E7: ¿el reordenamiento es de LandScan o del denominador?

Existe porque Whipp et al. 2021 muestran que los proxies de población ambiente no
coinciden entre sí. Con un solo proxy, parte del reordenamiento de E7 podría venir del
modelo de LandScan. Acá se repite la métrica de reordenamiento con un segundo proxy
independiente de LandScan, y se mide cuánto coinciden los dos proxies entre sí.

En local no hay empleo, viajes ni telefonía (``inwatch-04w``). Los proxies disponibles son
de actividad y atractores, no de población:

  - ``ambiente_viirs`` (el que decide): radiancia VIIRS DNB, media 2018-2023.
  - ``ambiente_poi`` (sensibilidad): suma de las 7 categorías de POI de OSM + 1. Es
    circular con la prueba direccional de E7, por eso no decide.

Criterio y umbrales fijados en el README antes de calcular; son los del pre-registro.
Capa de loader: lee ``celdas.parquet`` (salida de ``loader.py``) y dos rasters de
``h3_features`` de infelix, read-only. **No emite al registro canónico.**
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

AQUI = Path(__file__).resolve().parent


def _loader():
    spec = importlib.util.spec_from_file_location("denominador_loader", AQUI / "loader.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _loader()

REL = {
    "h3_viirs": "data/silver/h3_features/h3_viirs.parquet",
    "h3_osm_features": "data/silver/h3_features/h3_osm_features.parquet",
}
VIIRS_ANIOS = (2018, 2023)
NUM = L.NUM_VISTA  # latente_hibrido, el numerador de la conclusión
NUMS = (NUM, "observado_geo")
PROXIES = ("ambiente_viirs", "ambiente_poi")


def _ruta(nombre: str) -> Path:
    cat = L.fuentes.cargar_catalogo(L.fuentes.load_config())
    return cat.origenes["infelix"] / REL[nombre]


def proxies_crudos(indices: pd.Series, viirs: pd.DataFrame, osm: pd.DataFrame) -> pd.DataFrame:
    """Valores crudos de los dos proxies por celda (sin reescalar)."""
    v = viirs[viirs["year"].between(*VIIRS_ANIOS)].groupby("h3_index")["dnb_mean"].mean()
    poi = osm.set_index("h3_index").filter(like="poi_count").sum(axis=1)
    return pd.DataFrame(
        {
            "h3_index": indices.to_numpy(),
            "ambiente_viirs": indices.map(v).fillna(0.0).to_numpy(),
            "ambiente_poi": indices.map(poi).fillna(0.0).to_numpy() + 1.0,
        }
    )


def reescalar(x: pd.Series, total: float) -> pd.Series:
    """Reescala para que sume ``total``. No cambia ningún ranking; solo la unidad."""
    return x * (total / x.sum())


def evaluar(u: pd.DataFrame, num: str, n_boot: int = L.N_BOOT, semilla: int = L.SEMILLA):
    """Métricas del pre-registro para cada proxy y coincidencia entre proxies.

    ``u`` es el universo evaluable (piso primario) con columnas ``pob_<proxy>``.
    """
    ids = u["h3_index"]
    base = u[f"r_{num}__{L.BASELINE}"]
    riesgos = {"ambiente": u[f"r_{num}__ambiente"], "residente_meta": u[f"r_{num}__residente_meta"]}
    for p in PROXIES:
        riesgos[p] = u[num] / u[f"pob_{p}"]
    filas = []
    for nombre, r in riesgos.items():
        filas.append(
            {
                "numerador": num,
                "tipo": "vs_residente",
                "a": "residente",
                "b": nombre,
                **L.comparar(ids, base, r),
            }
        )
    for p in PROXIES:
        filas.append(
            {
                "numerador": num,
                "tipo": "entre_riesgos",
                "a": "ambiente",
                "b": p,
                **L.comparar(ids, riesgos["ambiente"], riesgos[p]),
            }
        )
        filas.append(
            {
                "numerador": num,
                "tipo": "entre_poblaciones",
                "a": "ambiente",
                "b": p,
                **L.comparar(ids, u["pob_ambiente"], u[f"pob_{p}"]),
            }
        )
        filas.append(
            {
                "numerador": num,
                "tipo": "entre_cocientes",
                "a": "ambiente",
                "b": p,
                **L.comparar(
                    ids, u["pob_ambiente"] / u["pob_residente"], u[f"pob_{p}"] / u["pob_residente"]
                ),
            }
        )
    filas.append(
        {
            "numerador": num,
            "tipo": "entre_riesgos",
            "a": "ambiente_viirs",
            "b": "ambiente_poi",
            **L.comparar(ids, riesgos["ambiente_viirs"], riesgos["ambiente_poi"]),
        }
    )
    tabla = pd.DataFrame(filas)

    # Bootstrap del criterio: ρ(meta) − ρ(proxy), mismas celdas remuestreadas para todos.
    arr = {k: v.to_numpy() for k, v in riesgos.items()}
    b = base.to_numpy()
    rng = np.random.default_rng(semilla)
    n = len(u)
    nombres = ["ambiente", "residente_meta", *PROXIES]
    reps = np.empty((n_boot, len(nombres)))
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        rb = stats.rankdata(b[idx])
        reps[i] = [np.corrcoef(rb, stats.rankdata(arr[k][idx]))[0, 1] for k in nombres]
    boot = []
    for j, k in enumerate(nombres):
        d = reps[:, 1] - reps[:, j]
        for est, x in ((f"rho_{k}", reps[:, j]), (f"dif_meta_menos_{k}", d)):
            if est == "dif_meta_menos_residente_meta":
                continue
            lo, hi = np.quantile(x, [0.025, 0.975])
            boot.append(
                {
                    "numerador": num,
                    "estadistico": est,
                    "media": float(x.mean()),
                    "ic_low": float(lo),
                    "ic_high": float(hi),
                    "n_boot": n_boot,
                    "n": n,
                }
            )
    return tabla, pd.DataFrame(boot)


def veredicto(tabla: pd.DataFrame, boot: pd.DataFrame, proxy: str, num: str = NUM) -> str:
    """Aplica los umbrales del pre-registro a ``proxy`` (ver README)."""
    t = tabla[(tabla.numerador == num) & (tabla.tipo == "vs_residente") & (tabla.b == proxy)]
    rho, top = float(t.spearman.iloc[0]), float(t.top50.iloc[0])
    d = boot[(boot.numerador == num) & (boot.estadistico == f"dif_meta_menos_{proxy}")].iloc[0]
    if rho < 0.80 and top < 0.50 and d.media > 0.20 and d.ic_low > 0:
        return "se_sostiene"
    if rho < 0.80 and top < 0.50:
        return "se_debilita"
    if rho >= 0.80 and top >= 0.50:
        return "se_cae"
    return "ambiguo"


def direccional_viirs(u: pd.DataFrame, num: str = NUM) -> dict[str, float]:
    """ρ(Δpercentil al pasar a VIIRS, POI comerciales), como la sub-predicción de E7."""
    pr = (u[num] / u[f"pob_{L.BASELINE}"]).rank(pct=True)
    pv = (u[num] / u["pob_ambiente_viirs"]).rank(pct=True)
    rho = stats.spearmanr(pv - pr, u["poi_comercial"]).statistic
    return {"numerador": num, "rho_dpct_poi_comercial": float(rho), "n": float(len(u))}


def build() -> dict[str, pd.DataFrame]:
    celdas = pd.read_parquet(L.OUT / "celdas.parquet")
    u = celdas[celdas[f"evaluable_{L.PISO_PRIMARIO}"]].reset_index(drop=True)
    crudo = proxies_crudos(
        u["h3_index"], pd.read_parquet(_ruta("h3_viirs")), pd.read_parquet(_ruta("h3_osm_features"))
    )
    total = float(u["pob_ambiente"].sum())
    for p in PROXIES:
        u[f"pob_{p}"] = reescalar(crudo[p], total).to_numpy()
    tablas, boots = zip(*(evaluar(u, n) for n in NUMS), strict=True)
    tabla, boot = pd.concat(tablas, ignore_index=True), pd.concat(boots, ignore_index=True)
    ver = pd.DataFrame(
        [
            {"numerador": n, "proxy": p, "veredicto": veredicto(tabla, boot, p, n)}
            for n in NUMS
            for p in ("ambiente", *PROXIES)
        ]
    )
    return {
        "segundo_proxy": tabla,
        "segundo_proxy_bootstrap": boot,
        "segundo_proxy_veredicto": ver,
        "segundo_proxy_direccional": pd.DataFrame([direccional_viirs(u, n) for n in NUMS]),
    }


def main() -> None:
    for nombre, df in build().items():
        dest = L.OUT / f"{nombre}.parquet"
        df.to_parquet(dest, index=False)
        print(f"  → {dest}  ({len(df):,} filas)")


if __name__ == "__main__":
    main()
