"""Chequeo posterior (literatura) de E8: heaping por modalidad y tipos en subconjuntos.

Existe por dos papers que la revisión de literatura puso enfrente del resultado:

1. Taylor, Di Marzio, Fensore & Passamonti 2026 (*JRSS C*): la probabilidad de redondear
   la hora depende del tipo de delito. El re-sorteo de ``loader.auditar_heaping`` usa la
   misma ventana para todos. Acá se estiman por EM las probabilidades de redondeo
   π_r (r ∈ {60, 30, 15, 5, 1} min) por modalidad —y por modalidad × turno— a partir de
   los minutos pasada la hora, y cada evento se re-sortea con la resolución que le toca.
2. Corcoran et al. 2019 y Ratcliffe 2002: sí hay tipos temporales, pero dentro de hot
   spots o de zonas comerciales. Acá se repite el clustering de ``loader`` en esos dos
   subconjuntos, con el mismo criterio de elección de k.

Criterios fijados en el README antes de calcular; son los de arriba. Capa de loader:
lee SIDPOL por ``loader.cargar_eventos`` y los POI de ``h3_feature_matrix``.
**No emite al registro canónico.**
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

AQUI = Path(__file__).resolve().parent


def _loader():
    spec = importlib.util.spec_from_file_location("reloj_loader", AQUI / "loader.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _loader()

SEMILLA = 20260925
RESOLUCIONES = np.array([60, 30, 15, 5, 1])
N_MIN_GRUPO = 2000  # modalidades más chicas usan las tasas de su categoría
N_REPLICAS = 20
VENTANAS = ("cercano", "truncado", "hacia_arriba")
# Las fijadas en el README antes de calcular; ``hacia_arriba`` es una prueba de estrés
# añadida después y no entra al veredicto.
VENTANAS_PREREGISTRADAS = ("cercano", "truncado")
POI_COMERCIAL = ("poi_count_retail", "poi_count_food", "poi_count_nightlife")
Q_HOTSPOT = 0.80  # quintil superior por eventos
Q_COMERCIAL = 0.75  # cuartil superior de POI comerciales


# ─── pura: el modelo de redondeo ─────────────────────────────────────────────
def verosimilitud_minuto() -> np.ndarray:
    """P(minuto | r): matriz 60 × len(RESOLUCIONES). Redondear a r deja múltiplos de r."""
    m = np.arange(60)[:, None]
    r = RESOLUCIONES[None, :]
    return np.where(m % r == 0, r / 60.0, 0.0)


def em_redondeo(hist_min: np.ndarray, n_iter: int = 500, tol: float = 1e-10) -> np.ndarray:
    """π_r por EM a partir del histograma de minutos (60 bins). Suma 1."""
    lik = verosimilitud_minuto()
    pi = np.full(len(RESOLUCIONES), 1.0 / len(RESOLUCIONES))
    h = np.asarray(hist_min, dtype=float)
    for _ in range(n_iter):
        w = lik * pi
        w /= np.maximum(w.sum(1, keepdims=True), 1e-300)
        nuevo = (w * h[:, None]).sum(0) / h.sum()
        if np.abs(nuevo - pi).max() < tol:
            return nuevo
        pi = nuevo
    return pi


def posterior_resolucion(pi: np.ndarray) -> np.ndarray:
    """P(r | minuto), 60 × len(RESOLUCIONES)."""
    w = verosimilitud_minuto() * pi
    return w / np.maximum(w.sum(1, keepdims=True), 1e-300)


def resortear(hora_frac: np.ndarray, minuto: np.ndarray, grupo: np.ndarray,
              post: dict, ventana: str, rng) -> np.ndarray:
    """Re-sortea cada hora con una resolución sacada de la posterior de su grupo.

    ``cercano``: hora ± r/2 (redondeo al más cercano). ``truncado``: [hora, hora + r)
    (quien dice «a las 8» por «8 y algo»). ``hacia_arriba``: (hora − r, hora] (quien dice
    «a las 6» por «6 menos algo»); añadida después de ver que ``truncado`` no mueve nada.

    Nota: los bordes de turno caen en horas en punto, así que ``truncado`` no puede cruzar
    ninguno: una hora redondeada hacia abajo ya está en su turno verdadero. Es inmune por
    construcción, no por robustez. ``hacia_arriba`` es la lectura que sí mueve masa a la
    madrugada (06:00 → 05:xx), la que preocupa en la literatura.
    """
    r = np.empty(len(hora_frac))
    u = rng.random(len(hora_frac))
    for g, tab in post.items():
        sel = grupo == g
        cum = np.cumsum(tab[minuto[sel]], axis=1)
        idx = (u[sel][:, None] > cum).sum(1).clip(max=len(RESOLUCIONES) - 1)
        r[sel] = RESOLUCIONES[idx]
    if ventana == "cercano":
        d = rng.uniform(-0.5, 0.5, len(r)) * r
    elif ventana == "truncado":
        d = rng.uniform(0.0, 1.0, len(r)) * r
    else:
        # r = 1 es «sin redondeo»: el minuto anotado es el truncado del verdadero, así que
        # no se desplaza hacia atrás (si no, todo :00 exacto cruzaría de turno).
        d = np.where(r == 1, rng.uniform(0.0, 1.0, len(r)), -rng.uniform(0.0, 1.0, len(r)) * r)
    return np.mod(hora_frac + d / 60.0, 24.0)


def razon_ruido_senal(celdas: pd.Series, t0: np.ndarray, t1: np.ndarray, k: int) -> dict:
    """La misma métrica que ``loader.auditar_heaping``: TVD mediana re-sorteo / señal."""
    c0 = L.tabla_conteos(celdas, t0, k)
    c1 = L.tabla_conteos(celdas, t1, k).reindex(c0.index, fill_value=0)
    ok = c0.sum(axis=1).to_numpy() >= L.N_MIN
    a0, a1 = c0.to_numpy()[ok], c1.to_numpy()[ok]
    p0, p1 = a0 / a0.sum(1, keepdims=True), a1 / a1.sum(1, keepdims=True)
    ciudad = a0.sum(0) / a0.sum()
    ruido = float(np.median(L.tvd(p0, p1)))
    senal = float(np.median(L.tvd(p0, ciudad)))
    return {"frac_cambia_turno": float((t0 != t1).mean()), "ratio": ruido / senal}


# ─── chequeo 1 · heaping por modalidad ───────────────────────────────────────
def grupos_de(uso: pd.DataFrame) -> np.ndarray:
    """Modalidad si tiene n ≥ N_MIN_GRUPO; si no, su categoría."""
    n = uso["modalidad"].value_counts()
    grandes = set(n[n >= N_MIN_GRUPO].index)
    return np.where(uso["modalidad"].isin(grandes), "mod:" + uso["modalidad"],
                    "cat:" + uso["crime_cat"])


def tasas(uso: pd.DataFrame, grupo: np.ndarray) -> tuple[dict, pd.DataFrame]:
    """π por grupo y su posterior; tabla larga para reportar."""
    post, filas = {}, []
    for g in np.unique(grupo):
        m = uso["minuto"].to_numpy()[grupo == g]
        pi = em_redondeo(np.bincount(m, minlength=60))
        post[g] = posterior_resolucion(pi)
        filas.append({"grupo": g, "n": int(len(m)),
                      **{f"pi_{r}": float(p) for r, p in zip(RESOLUCIONES, pi, strict=True)}})
    return post, pd.DataFrame(filas)


def eje_de(c: np.ndarray, prior: np.ndarray, alpha: float) -> np.ndarray:
    """Primer componente de la firma (el eje madrugada-tarde de ``loader.estructura``)."""
    x = L.firma(c, prior, alpha)
    val, vec = np.linalg.eigh(np.cov(x.T))
    pc1 = vec[:, np.argmax(val)]
    return pc1 * np.sign(pc1[np.argmax(np.abs(pc1))])


def chequeo_heaping(uso: pd.DataFrame, rng) -> tuple[dict, pd.DataFrame]:
    hf, mi = uso["hora_frac"].to_numpy(), uso["minuto"].to_numpy()
    t0 = L.turno_de(hf, "turnos4")
    base = grupos_de(uso)
    nombres = L.ESQUEMAS["turnos4"]["nombres"]
    variantes = {"modalidad": base,
                 "modalidad_x_turno": np.char.add(np.char.add(base.astype(str), "|"),
                                                  np.array(nombres)[t0])}
    c0t = L.tabla_conteos(uso["h3_index"], t0, 4)
    c0t = c0t[c0t.sum(axis=1) >= L.N_MIN]
    c0 = c0t.to_numpy()
    prior = c0.sum(0) / c0.sum()
    alpha = L.estimar_precision(c0, prior)
    pc1 = eje_de(c0, prior, alpha)
    eje0 = L.firma(c0, prior, alpha) @ pc1
    madr0 = float((t0 == 0).mean())

    res, tablas = {}, []
    for nombre, grupo in variantes.items():
        post, tab = tasas(uso, grupo)
        tablas.append(tab.assign(variante=nombre))
        for ventana in VENTANAS:
            reps = []
            for _ in range(N_REPLICAS):
                h1 = resortear(hf, mi, grupo, post, ventana, rng)
                t1 = L.turno_de(h1, "turnos4")
                r = razon_ruido_senal(uso["h3_index"], t0, t1, 4)
                r6 = razon_ruido_senal(uso["h3_index"], L.turno_de(hf, "bloques6"),
                                       L.turno_de(h1, "bloques6"), 6)
                c1 = (L.tabla_conteos(uso["h3_index"], t1, 4)
                      .reindex(c0t.index, fill_value=0).to_numpy())
                eje1 = L.firma(c1, prior, alpha) @ pc1
                reps.append({**r, "ratio_bloques6": r6["ratio"],
                             "frac_cambia_bloques6": r6["frac_cambia_turno"],
                             "madrugada_ciudad": float((t1 == 0).mean()),
                             "rho_eje": float(spearmanr(eje0, eje1).statistic)})
            rp = pd.DataFrame(reps)
            res[f"{nombre}|{ventana}"] = {
                "ratio_media": float(rp["ratio"].mean()),
                "ratio_p95": float(rp["ratio"].quantile(0.95)),
                "frac_cambia_media": float(rp["frac_cambia_turno"].mean()),
                "frac_cambia_p95": float(rp["frac_cambia_turno"].quantile(0.95)),
                "ratio_bloques6_p95": float(rp["ratio_bloques6"].quantile(0.95)),
                "frac_cambia_bloques6_p95": float(rp["frac_cambia_bloques6"].quantile(0.95)),
                "madrugada_ciudad_antes": madr0,
                "madrugada_ciudad_despues": float(rp["madrugada_ciudad"].mean()),
                "rho_eje_media": float(rp["rho_eje"].mean()),
            }
    def mata(v):
        return (v["ratio_p95"] >= L.KILL_HEAPING_RATIO_TVD
                or v["frac_cambia_p95"] > L.KILL_HEAPING_FRAC_CAMBIA)

    muere = any(mata(v) for k, v in res.items() if k.split("|")[1] in VENTANAS_PREREGISTRADAS)
    muere_estres = any(mata(v) for k, v in res.items() if k.endswith("|hacia_arriba"))
    return {"variantes": res, "muere": bool(muere), "muere_en_estres": bool(muere_estres),
            "n_replicas": N_REPLICAS, "n_min_grupo": N_MIN_GRUPO}, pd.concat(
                tablas, ignore_index=True)


# ─── chequeo 2 · tipos en hot spots y zonas comerciales ──────────────────────
def subconjuntos(n_celda: pd.Series, poi: pd.Series) -> dict[str, np.ndarray]:
    """Celdas (n ≥ N_MIN) del quintil superior de eventos y del cuartil superior de POI."""
    n = n_celda[n_celda >= L.N_MIN]
    p = poi.reindex(n.index).fillna(0)
    return {"hot_spots": np.sort(n[n >= n.quantile(Q_HOTSPOT)].index.to_numpy()),
            "comerciales": np.sort(p[p >= p.quantile(Q_COMERCIAL)].index.to_numpy())}


def elegir_k_relajado(est: pd.DataFrame, umbral: float = 0.5) -> int | None:
    """``elegir_k`` con el umbral de estabilidad en 0,5 (duda 5). Informativo, no decide."""
    ok = est[(est["silhouette"] > est["nulo_silhouette_p95"])
             & (est["ari_boot_p05"] > est["nulo_ari_boot_p95"])
             & (est["ari_boot_media"] >= umbral)]
    return int(ok["k"].min()) if len(ok) else None


def chequeo_tipos(uso: pd.DataFrame, poi: pd.Series, rng) -> tuple[dict, pd.DataFrame]:
    n_celda = uso.groupby("h3_index").size()
    subs = subconjuntos(n_celda, poi)
    res, ests = {}, []
    for sub, celdas in subs.items():
        u = uso[uso["h3_index"].isin(set(celdas))]
        res[sub] = {"n_celdas": int(len(celdas)), "n_eventos": int(len(u))}
        for esq, spec in L.ESQUEMAS.items():
            k = len(spec["nombres"])
            c = (L.tabla_conteos(u["h3_index"], L.turno_de(u["hora_frac"].to_numpy(), esq), k)
                 .reindex(celdas, fill_value=0).to_numpy())
            prior = c.sum(0) / c.sum()
            alpha = L.estimar_precision(c, prior)
            est = L.estabilidad(c, prior, alpha, rng).assign(subconjunto=sub, esquema=esq)
            ests.append(est)
            mejor = est.loc[est["silhouette"].idxmax()]
            res[sub][esq] = {
                "sobredispersion": L.sobredispersion(c),
                "alpha_dirichlet": alpha,
                "k_elegido": L.elegir_k(est),
                "k_elegido_umbral_0_5": elegir_k_relajado(est),
                "k_mejor_silhouette": int(mejor["k"]),
                "silhouette": float(mejor["silhouette"]),
                "nulo_silhouette_p95": float(mejor["nulo_silhouette_p95"]),
                "ari_boot_media": float(mejor["ari_boot_media"]),
                "nulo_ari_boot_p95": float(mejor["nulo_ari_boot_p95"]),
            }
    aparecen = any(res[s][e]["k_elegido"] is not None for s in subs for e in L.ESQUEMAS)
    return {"subconjuntos": res, "aparecen_tipos": bool(aparecen),
            "q_hotspot": Q_HOTSPOT, "q_comercial": Q_COMERCIAL}, pd.concat(ests)


def main() -> None:
    rng = np.random.default_rng(SEMILLA)
    ev = L.cargar_eventos()
    uso = ev[~ev["exact_midnight"] & ~ev["aoristica"]].reset_index(drop=True)
    print(f"  eventos del reloj: {len(uso):,}")
    fm = pd.read_parquet(L.fuentes.ruta("h3_feature_matrix"),
                         columns=["h3_index", *POI_COMERCIAL]).drop_duplicates("h3_index")
    poi = fm.set_index("h3_index")[list(POI_COMERCIAL)].fillna(0).sum(axis=1)

    heap, tasas_tab = chequeo_heaping(uso, rng)
    tipos, ests = chequeo_tipos(uso, poi, rng)
    out = {"slug": L.SLUG, "chequeo": "posterior (literatura)", "semilla": SEMILLA,
           "inputs_sha256": L.sha_fuentes(),
           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           "heaping_por_modalidad": heap,
           "tipos_en_subconjuntos": tipos}
    tasas_tab.to_parquet(L.OUT / "chequeo_tasas_redondeo.parquet", index=False)
    ests.to_parquet(L.OUT / "chequeo_estabilidad_subconjuntos.parquet", index=False)
    (L.OUT / "chequeo_literatura.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False, default=float))
    print(f"  heaping muere: {heap['muere']} · aparecen tipos: {tipos['aparecen_tipos']}")


if __name__ == "__main__":
    main()
