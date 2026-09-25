"""Precómputo de `reloj-de-riesgo` (E8): denuncias → firma horaria por celda.

La pregunta es si las celdas de Lima tienen un *reloj* propio — una distribución del
crimen por turno que las distinga del resto de la ciudad y que se pueda agrupar en
tipos (los *chronotypes* de infelix slr-b41b, Idea 15). El bead (inwatch-kr0) fija dos
cosas antes de dejar agrupar nada, y este archivo tiene la forma que tiene por ellas:

1. LA UNIDAD. Celda × hora es inviable: celda × mes ya roza cero en categorías raras.
   La unidad es celda × turno (4 a 6 turnos), agregada como CLIMATOLOGÍA — todos los
   años apilados en una sola distribución por celda — y no como panel. Por eso aquí no
   hay índice temporal en la salida: solo conteos por (celda, turno).

2. LAS TRES TRAMPAS SE AUDITAN ANTES. Heaping (horas redondas y el 00:00 como default
   de hora desconocida), incertidumbre aorística (delitos descubiertos después, cuya
   hora es la del descubrimiento) y sparsity. Cada trampa tiene un criterio de muerte
   escrito abajo como constante, ANTES del clustering, y el clustering solo corre si
   las tres sobreviven. Si una mata, el entregable es la auditoría.

Lo que se hereda de E6.H1 (``pulso-estadios``) y no se re-litiga: horas fraccionales
en America/Lima, exclusión de los 00:00:00 exactos, exclusión de las modalidades
aorísticas, y la limpieza de puntos (sólo denuncias, con coordenada, bbox, anti-centroide
y celdas del feature matrix). El crosswalk de categorías y las constantes se IMPORTAN de
ese loader en vez de copiarse: dos copias de la limpieza derivarían.

Lo que NO hace este archivo, y a propósito: no emite al registro canónico. La emisión
queda para cuando Rody revise la auditoría (ver README, "Decisiones tomadas"). Las cifras
viven en ``trampas.json`` con el ``inputs_sha256`` de las fuentes.

Limitación que se declara: ENAPRES no registra hora del hecho, así que la corrección de
sesgo de denuncia no puede condicionarse a la hora. Este reloj es el reloj de la
DENUNCIA, y hereda el sesgo horario de denuncia sin poder medirlo.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

from inwatch import fuentes

SLUG = "reloj-de-riesgo"
UNIDAD = "h3_8"

_RAIZ = Path(__file__).resolve().parents[2]
OUT = _RAIZ / "data" / "silver" / SLUG
BRONZE = _RAIZ / "data" / "bronze" / SLUG

# La limpieza de puntos es la de E6.H1. Se carga su loader por ruta porque los
# experimentos no son paquetes (mismo patrón que los tests).
_PULSO = _RAIZ / "experiments" / "pulso-estadios" / "loader.py"
_spec = importlib.util.spec_from_file_location("pulso_loader", _PULSO)
pulso = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pulso)

SEED = 42

# ─── esquemas de turno ───────────────────────────────────────────────────────
# `turnos4` son los cuatro turnos que el propio SIDPOL trae en `turno_hecho`
# (madrugada 0–6, mañana 6–12, tarde 12–18, noche 18–24; verificado contra la hora: la
# tabla cruzada es diagonal salvo 6 filas). `bloques6` es la alternativa de seis bloques
# de 4 h que el bead permite. Los dos se computan: si una firma solo existe en uno, no
# es del lugar, es del corte.
ESQUEMAS: dict[str, dict] = {
    "turnos4": {
        "bordes": [0, 6, 12, 18, 24],
        "nombres": ["madrugada", "mañana", "tarde", "noche"],
    },
    "bloques6": {
        "bordes": [0, 4, 8, 12, 16, 20, 24],
        "nombres": ["00–04", "04–08", "08–12", "12–16", "16–20", "20–24"],
    },
}
ESQUEMA_PRINCIPAL = "turnos4"

# ─── criterios de muerte, fijados ANTES de mirar el clustering ───────────────
# Trampa 1 · heaping. Se re-sortea la hora de cada evento redondeado dentro de su
# ventana de redondeo (``jitter_heaping``) y se mide cuánto se mueve la firma.
KILL_HEAPING_FRAC_CAMBIA = 0.10   # > 10 % de eventos cambia de turno → el corte no aguanta
KILL_HEAPING_RATIO_TVD = 0.50     # ruido por heaping ≥ mitad de la señal entre celdas → muere
# Trampa 2 · aorística. Sin ventana (inicio, fin) no hay Ratcliffe posible; se excluyen.
KILL_AORISTICA_FRAC = 0.50        # si se pierde más de la mitad de los eventos → muere
# Trampa 3 · sparsity. n ≥ 100 da SE ≤ 0,05 en cualquier proporción de turno.
N_MIN = 100
KILL_SPARSITY_MIN_CELDAS = 100      # menos celdas que esto no es un mapa
KILL_SPARSITY_MIN_COBERTURA = 0.50  # las celdas con piso deben retener ≥ 50 % de eventos
KILL_SPARSITY_MIN_FIABILIDAD = 0.50  # fiabilidad split-half (Spearman-Brown) de la firma
KILL_SPARSITY_MIN_SOBREDISP = 1.50   # varianza entre celdas / varianza multinomial esperada

# ─── clustering ──────────────────────────────────────────────────────────────
K_RANGO = list(range(2, 9))
N_SEMILLAS = 20
N_INIT = 10
B_BOOT = 60
N_NULO = 20


# ─── pura: turnos y heaping ──────────────────────────────────────────────────
def turno_de(hora_frac: np.ndarray, esquema: str) -> np.ndarray:
    """Índice de turno para horas fraccionales en [0, 24). El borde izquierdo es cerrado."""
    bordes = np.asarray(ESQUEMAS[esquema]["bordes"][1:-1], dtype=float)
    h = np.mod(np.asarray(hora_frac, dtype=float), 24.0)
    return np.searchsorted(bordes, h, side="right").astype(np.int8)


def semiancho_redondeo(minuto: np.ndarray) -> np.ndarray:
    """Semiancho (en minutos) de la ventana de redondeo que un minuto sugiere.

    ``:00`` → quien no sabía dijo "a las ocho": ±30 min. ``:30`` → "y media": ±15.
    Otro múltiplo de 5 → ±2,5. Lo demás no se trata como redondeado. Es la hipótesis
    más generosa con el heaping que todavía es plausible; si la firma resiste esto,
    resiste redondeos más finos.
    """
    m = np.asarray(minuto)
    return np.select([m == 0, m == 30, m % 5 == 0], [30.0, 15.0, 2.5], default=0.0)


def jitter_heaping(hora_frac: np.ndarray, minuto: np.ndarray, rng) -> np.ndarray:
    """Re-sortea uniformemente cada hora redondeada dentro de su ventana de redondeo."""
    w = semiancho_redondeo(minuto) / 60.0
    return np.mod(np.asarray(hora_frac, dtype=float) + rng.uniform(-1, 1, len(w)) * w, 24.0)


# ─── pura: firmas composicionales ────────────────────────────────────────────
def tabla_conteos(celdas: pd.Series, turnos: np.ndarray, n_turnos: int) -> pd.DataFrame:
    """Matriz celda × turno de conteos (int), con todas las columnas aunque estén en 0."""
    t = pd.crosstab(celdas.to_numpy(), np.asarray(turnos))
    t = t.reindex(columns=range(n_turnos), fill_value=0)
    t.index.name = "h3_index"
    return t.astype(np.int64)


def estimar_precision(conteos: np.ndarray, prior: np.ndarray) -> float:
    """Precisión α de un Dirichlet-multinomial por momentos (celdas con n ≥ 2).

    Var(p̂_b) entre celdas = p_b(1−p_b) · (1/n + (1 − 1/n)/(α+1)) aproximadamente. Se
    despeja 1/(α+1) promediando sobre turnos. α grande = celdas casi iguales a la ciudad.
    """
    n = conteos.sum(1)
    ok = n >= 2
    c, n = conteos[ok], n[ok]
    p = c / n[:, None]
    var_obs = ((p - prior) ** 2 * n[:, None]).sum(0) / n.sum()
    base = prior * (1 - prior)
    ruido = base * np.mean(1.0 / n)
    rho = np.clip((var_obs - ruido).sum() / max((base * (1 - np.mean(1.0 / n))).sum(), 1e-12),
                  1e-6, 1 - 1e-6)
    return float(1.0 / rho - 1.0)


def encoger(conteos: np.ndarray, prior: np.ndarray, alpha: float) -> np.ndarray:
    """Media posterior Dirichlet: (n_cb + α p_b) / (n_c + α)."""
    return (conteos + alpha * prior) / (conteos.sum(1, keepdims=True) + alpha)


def clr(p: np.ndarray) -> np.ndarray:
    """Log-ratio centrado: la geometría correcta para proporciones (Aitchison)."""
    lp = np.log(p)
    return lp - lp.mean(-1, keepdims=True)


def firma(conteos: np.ndarray, prior: np.ndarray, alpha: float) -> np.ndarray:
    """clr de la firma encogida menos clr de la ciudad: exceso relativo por turno."""
    return clr(encoger(conteos, prior, alpha)) - clr(prior)


def tvd(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Distancia de variación total fila a fila."""
    return 0.5 * np.abs(np.asarray(p) - np.asarray(q)).sum(-1)


def sobredispersion(conteos: np.ndarray) -> float:
    """Varianza entre celdas de p̂ sobre la esperada si todas fueran la ciudad + ruido.

    ≈ 1: las celdas no difieren más de lo que difiere el muestreo. Es el test que
    decide si hay algo que agrupar ANTES de agrupar.
    """
    n = conteos.sum(1)
    prior = conteos.sum(0) / conteos.sum()
    p = conteos / n[:, None]
    obs = ((p - prior) ** 2).mean(0)
    esp = (prior * (1 - prior) * np.mean(1.0 / n))
    return float(obs.sum() / esp.sum())


def fiabilidad_split_half(ca: np.ndarray, cb: np.ndarray, prior: np.ndarray,
                          alpha: float) -> float:
    """Correlación entre las firmas de dos mitades disjuntas, corregida por Spearman-Brown.

    Se promedia sobre turnos la correlación de Pearson de la firma de cada turno entre
    mitades. Si la firma de una celda es ruido, las dos mitades no se parecen.
    """
    fa, fb = firma(ca, prior, alpha), firma(cb, prior, alpha)
    r = np.nanmean([np.corrcoef(fa[:, j], fb[:, j])[0, 1] for j in range(fa.shape[1])])
    return float(2 * r / (1 + r))


# ─── pura: clustering sin sklearn (CI no instala el extra `ml`) ───────────────
def kmeans(x: np.ndarray, k: int, seed: int, n_init: int = N_INIT) -> tuple[np.ndarray, float]:
    """k-means++ con ``n_init`` arranques; devuelve (etiquetas, inercia) del mejor."""
    from scipy.cluster.vq import kmeans2

    rng = np.random.default_rng(seed)
    mejor, mejor_in = None, np.inf
    for _ in range(n_init):
        cent, lab = kmeans2(x, k, minit="++", seed=rng, iter=50)
        inercia = float(((x - cent[lab]) ** 2).sum())
        if inercia < mejor_in:
            mejor, mejor_in = lab, inercia
    return canonizar(mejor, x), mejor_in


def canonizar(lab: np.ndarray, x: np.ndarray) -> np.ndarray:
    """Renombra clusters por tamaño descendente: la etiqueta 0 es siempre el mayor."""
    orden = np.argsort(-np.bincount(lab, minlength=lab.max() + 1), kind="stable")
    mapa = np.empty_like(orden)
    mapa[orden] = np.arange(len(orden))
    return mapa[lab]


def ari(a: np.ndarray, b: np.ndarray) -> float:
    """Adjusted Rand Index (Hubert & Arabie 1985)."""
    from scipy.special import comb

    tab = pd.crosstab(np.asarray(a), np.asarray(b)).to_numpy()
    s_ij = comb(tab, 2).sum()
    s_a = comb(tab.sum(1), 2).sum()
    s_b = comb(tab.sum(0), 2).sum()
    tot = comb(tab.sum(), 2)
    esp = s_a * s_b / tot
    mx = 0.5 * (s_a + s_b)
    return float((s_ij - esp) / (mx - esp)) if mx != esp else 1.0


def silhouette(x: np.ndarray, lab: np.ndarray) -> float:
    """Silhouette media (euclidiana)."""
    from scipy.spatial.distance import cdist

    d = cdist(x, x)
    ks = np.unique(lab)
    if len(ks) < 2:
        return float("nan")
    medias = np.stack([d[:, lab == k].mean(1) for k in ks], 1)
    tam = np.array([(lab == k).sum() for k in ks])
    propio = np.searchsorted(ks, lab)
    # a(i) excluye a i de su propio cluster
    a = medias[np.arange(len(x)), propio] * tam[propio] / np.maximum(tam[propio] - 1, 1)
    medias[np.arange(len(x)), propio] = np.inf
    b = medias.min(1)
    s = (b - a) / np.maximum(a, b)
    s[tam[propio] == 1] = 0.0
    return float(s.mean())


# ─── carga ───────────────────────────────────────────────────────────────────
COLS = pulso.SOURCE_COLS + ["fecha_hora_registro_hecho", "turno_hecho", "comisaria_registro"]


def cargar_eventos() -> pd.DataFrame:
    """Todas las denuncias limpias (cinco categorías), con hora y banderas, sin excluir.

    Misma limpieza que ``pulso.cargar_puntos`` salvo el recorte final a robo callejero:
    acá se quieren todas las categorías y todas las modalidades, porque las exclusiones
    son justamente lo que se audita. Nada se excluye en esta función.
    """
    import h3

    src = fuentes.ruta("denuncias_lima")
    df = pd.read_parquet(src, columns=COLS)
    df = df[df["solo_denuncia"] == 1].copy()
    df["year"] = pd.to_numeric(df["año_hecho"], errors="coerce")
    df = df[(df["year"] >= pulso.YEAR_LO) & (df["year"] <= pulso.YEAR_HI)]
    df["crime_cat"] = pulso.map_category(df["tipo_hecho"], df["subtipo_hecho"],
                                         df["modalidad_hecho"])
    df = df[df["crime_cat"].notna()]
    geo = df[df["estado_coord"].astype(str).str.upper() == "CON COORDENADA"].copy()
    geo["lat"] = pd.to_numeric(geo["lat_hecho"], errors="coerce")
    geo["lng"] = pd.to_numeric(geo["long_hecho"], errors="coerce")
    geo = geo[geo["lat"].between(pulso.LAT_MIN, pulso.LAT_MAX)
              & geo["lng"].between(pulso.LNG_MIN, pulso.LNG_MAX)]
    pile = geo.groupby(["lat", "lng"]).size()
    bad = set(pile[pile > pulso.MAX_PER_COORD].index)
    if bad:
        keep = np.array([k not in bad for k in zip(geo["lat"], geo["lng"], strict=True)])
        geo = geo[keep]
    geo["h3_index"] = [h3.latlng_to_cell(la, ln, pulso.H3_RES)
                       for la, ln in zip(geo["lat"].to_numpy(), geo["lng"].to_numpy(),
                                         strict=True)]
    celdas = set(pd.read_parquet(fuentes.ruta("h3_feature_matrix"),
                                 columns=["h3_index"])["h3_index"].unique())
    geo = geo[geo["h3_index"].isin(celdas)].copy()

    ts = pd.to_datetime(geo["fecha_hora_hecho"], unit="ms", utc=True).dt.tz_convert(
        "America/Lima")
    # SUPUESTO: `fecha_hora_registro_hecho` es hora de pared de Lima guardada como si
    # fuera UTC, a diferencia de `fecha_hora_hecho` (que sí es UTC: su hora en Lima cuadra
    # con `turno_hecho`). Evidencia: leído como UTC, el rezago registro − hecho tiene un
    # piso duro en −5 h (menos del 1 % cae por debajo) y 39 % de rezagos negativos —
    # denuncias registradas antes del hecho. Leído como hora de Lima, el piso pasa a 0.
    reg = pd.to_datetime(geo["fecha_hora_registro_hecho"], unit="ms").dt.tz_localize(
        "America/Lima", ambiguous="NaT", nonexistent="NaT")
    out = pd.DataFrame({
        "h3_index": geo["h3_index"].to_numpy(),
        "crime_cat": geo["crime_cat"].to_numpy(),
        "modalidad": geo["modalidad_hecho"].fillna("").str.upper().to_numpy(),
        "comisaria": geo["comisaria_registro"].to_numpy(),
        "year": geo["year"].astype(int).to_numpy(),
        "hora": ts.dt.hour.to_numpy(),
        "minuto": ts.dt.minute.to_numpy(),
        "hora_frac": (ts.dt.hour + ts.dt.minute / 60.0).to_numpy(),
        "exact_midnight": ((ts.dt.hour == 0) & (ts.dt.minute == 0)
                           & (ts.dt.second == 0)).to_numpy(),
        "lag_registro_h": ((reg - ts).dt.total_seconds() / 3600.0).to_numpy(),
        "turno_sidpol": geo["turno_hecho"].to_numpy(),
    })
    out["aoristica"] = out["modalidad"].isin(pulso.AORISTIC_MODS)
    return out.reset_index(drop=True)


def sha_fuentes() -> str:
    """Hash conjunto de las fuentes (caché de sha de ``fuentes``) y de este script."""
    h = hashlib.sha256()
    for nombre in ("denuncias_lima", "h3_feature_matrix"):
        r = fuentes.resolver(nombre)
        h.update(f"{nombre}:{r.sha256}".encode())
    h.update(Path(__file__).read_bytes())
    h.update(_PULSO.read_bytes())
    return h.hexdigest()


# ─── las tres trampas ────────────────────────────────────────────────────────
def auditar_heaping(ev: pd.DataFrame, rng) -> tuple[dict, pd.DataFrame]:
    """Trampa 1. Histograma hora×minuto, 00:00 por celda, y test de re-sorteo."""
    hist = (ev.groupby(["hora", "minuto"]).size().rename("n").reset_index())
    n = len(ev)
    res: dict = {
        "n_eventos": n,
        "frac_minuto_00": float((ev["minuto"] == 0).mean()),
        "frac_minuto_30": float((ev["minuto"] == 30).mean()),
        "frac_minuto_mult5": float((ev["minuto"] % 5 == 0).mean()),
        "frac_minuto_uniforme_esperada_mult5": 12 / 60,
        "frac_exact_midnight": float(ev["exact_midnight"].mean()),
    }
    # Espiga de las 00:00 sobre lo que "debería" haber: minuto 0 de las 01:00–05:00.
    base = hist[(hist["hora"].between(1, 5)) & (hist["minuto"] == 0)]["n"].mean()
    res["espiga_0000_sobre_0100_0500"] = float(
        hist[(hist["hora"] == 0) & (hist["minuto"] == 0)]["n"].sum() / base)
    # Espiga en cada borde de turno, minuto 0, contra el minuto 0 de las horas vecinas.
    esp = {}
    for h0 in (6, 12, 18):
        m0 = hist[(hist["minuto"] == 0)].set_index("hora")["n"]
        esp[f"{h0:02d}:00"] = float(m0[h0] / np.mean([m0[h0 - 1], m0[h0 + 1]]))
    res["espiga_borde_sobre_vecinas"] = esp

    # ¿El default 00:00 es homogéneo en el espacio? Si se concentra en ciertas celdas,
    # excluirlo les quita madrugada a ellas y no a otras: sesgo diferencial.
    por_celda = ev.groupby("h3_index").agg(n=("exact_midnight", "size"),
                                            m=("exact_midnight", "sum"))
    pc = por_celda[por_celda["n"] >= N_MIN]
    p0 = pc["m"].sum() / pc["n"].sum()
    var_obs = ((pc["m"] / pc["n"] - p0) ** 2).mean()
    var_esp = (p0 * (1 - p0) / pc["n"]).mean()
    res["midnight_celda_sobredispersion"] = float(var_obs / var_esp)
    res["midnight_celda_p90"] = float((pc["m"] / pc["n"]).quantile(0.9))
    res["midnight_celda_p10"] = float((pc["m"] / pc["n"]).quantile(0.1))

    # Test de re-sorteo, sobre los eventos que efectivamente entran al reloj.
    uso = ev[~ev["exact_midnight"] & ~ev["aoristica"]]
    res["resorteo"] = {}
    for esq, spec in ESQUEMAS.items():
        k = len(spec["nombres"])
        t0 = turno_de(uso["hora_frac"].to_numpy(), esq)
        t1 = turno_de(jitter_heaping(uso["hora_frac"].to_numpy(),
                                     uso["minuto"].to_numpy(), rng), esq)
        c0 = tabla_conteos(uso["h3_index"], t0, k)
        c1 = tabla_conteos(uso["h3_index"], t1, k).reindex(c0.index, fill_value=0)
        ok = c0.sum(axis=1).to_numpy() >= N_MIN
        a0, a1 = c0.to_numpy()[ok], c1.to_numpy()[ok]
        p0v, p1v = a0 / a0.sum(1, keepdims=True), a1 / a1.sum(1, keepdims=True)
        ciudad = a0.sum(0) / a0.sum()
        tvd_ruido = float(np.median(tvd(p0v, p1v)))
        tvd_senal = float(np.median(tvd(p0v, ciudad)))
        res["resorteo"][esq] = {
            "frac_cambia_turno": float((t0 != t1).mean()),
            "tvd_mediana_resorteo": tvd_ruido,
            "tvd_mediana_celda_vs_ciudad": tvd_senal,
            "ratio": tvd_ruido / tvd_senal,
        }
    r = res["resorteo"][ESQUEMA_PRINCIPAL]
    res["muere"] = bool(r["frac_cambia_turno"] > KILL_HEAPING_FRAC_CAMBIA
                        or r["ratio"] >= KILL_HEAPING_RATIO_TVD)
    return res, hist


def auditar_aoristica(ev: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Trampa 2. Qué modalidades tienen hora de descubrimiento y cuánto pesan."""
    tot = len(ev)
    mod = (ev.groupby("modalidad")
           .agg(n=("hora", "size"),
                frac_midnight=("exact_midnight", "mean"),
                frac_madrugada=("hora", lambda h: float((h < 6).mean())),
                lag_mediana_h=("lag_registro_h", "median"),
                lag_p90_h=("lag_registro_h", lambda s: float(s.quantile(0.9))),
                aoristica=("aoristica", "first"))
           .sort_values("n", ascending=False).reset_index())
    mod["frac_total"] = mod["n"] / tot
    no_ao = ev[~ev["aoristica"]]
    ao = ev[ev["aoristica"]]
    res = {
        "modalidades_excluidas": sorted(pulso.AORISTIC_MODS),
        "frac_eventos_aoristicos": float(ev["aoristica"].mean()),
        "frac_midnight_aoristicas": float(ao["exact_midnight"].mean()),
        "frac_midnight_resto": float(no_ao["exact_midnight"].mean()),
        "lag_mediana_h_aoristicas": float(ao["lag_registro_h"].median()),
        "lag_mediana_h_resto": float(no_ao["lag_registro_h"].median()),
        "frac_madrugada_aoristicas": float((ao["hora"] < 6).mean()),
        "frac_madrugada_resto": float((no_ao["hora"] < 6).mean()),
        # Sin columna de fin de ventana no hay reparto de Ratcliffe posible: SIDPOL trae
        # una sola hora del hecho y la hora de registro, que es POSTERIOR al
        # descubrimiento — no acota la ventana del hecho por arriba de forma útil.
        "ventana_disponible": False,
    }
    # ¿La exclusión vacía de reloj a las celdas residenciales? Fracción aorística por celda.
    pc = ev.groupby("h3_index")["aoristica"].agg(["size", "mean"])
    pc = pc[pc["size"] >= N_MIN]
    res["celda_frac_aoristica_p50"] = float(pc["mean"].median())
    res["celda_frac_aoristica_p90"] = float(pc["mean"].quantile(0.9))
    res["celdas_mayoria_aoristica"] = int((pc["mean"] > 0.5).sum())
    # Las modalidades que se comportan como aorísticas sin estar en la lista: mucho
    # 00:00 o mucho rezago. No se excluyen (no se re-litiga E6.H1) — se reportan.
    grandes = mod[(mod["n"] >= 2000) & ~mod["aoristica"]]
    sosp = grandes[(grandes["frac_midnight"] > 3 * res["frac_midnight_resto"])
                   | (grandes["lag_mediana_h"] > 24)]
    res["sospechosas_no_excluidas"] = [
        {"modalidad": r.modalidad, "n": int(r.n), "frac_midnight": round(r.frac_midnight, 4),
         "lag_mediana_h": round(r.lag_mediana_h, 1)} for r in sosp.itertuples()]
    res["frac_eventos_sospechosos"] = float(sosp["n"].sum() / tot)
    res["muere"] = bool(res["frac_eventos_aoristicos"] > KILL_AORISTICA_FRAC)
    return res, mod


def auditar_sparsity(uso: pd.DataFrame, rng) -> tuple[dict, pd.DataFrame]:
    """Trampa 3. Cuántas celdas sostienen una firma, y si la firma se repite."""
    res: dict = {"n_eventos_reloj": len(uso), "n_celdas_con_evento": int(uso["h3_index"].nunique())}
    n_c = uso.groupby("h3_index").size()
    # Lo que el bead declara inviable, medido: celda × hora y celda × turno × mes.
    celda_hora = uso.groupby(["h3_index", "hora"]).size().unstack(fill_value=0)
    res["celda_hora_mediana"] = float(np.median(celda_hora.to_numpy()))
    res["celda_hora_frac_cero"] = float((celda_hora.to_numpy() == 0).mean())
    n_meses = 12 * (pulso.YEAR_HI - pulso.YEAR_LO + 1)
    t4 = turno_de(uso["hora_frac"].to_numpy(), "turnos4")
    panel = uso.assign(t=t4).groupby(["h3_index", "t"]).size()
    res["celda_turno_mes_media"] = float(panel.mean() / n_meses)
    res["n_meses"] = n_meses

    res["piso_n_min"] = N_MIN
    ok = n_c[n_c >= N_MIN]
    res["celdas_sobre_piso"] = int(len(ok))
    res["frac_celdas_sobre_piso"] = float(len(ok) / len(n_c))
    res["cobertura_eventos_sobre_piso"] = float(ok.sum() / n_c.sum())
    res["n_celda_mediana_sobre_piso"] = float(ok.median())

    res["por_esquema"] = {}
    for esq, spec in ESQUEMAS.items():
        k = len(spec["nombres"])
        t = turno_de(uso["hora_frac"].to_numpy(), esq)
        c = tabla_conteos(uso["h3_index"], t, k).loc[ok.index].to_numpy()
        prior = c.sum(0) / c.sum()
        alpha = estimar_precision(c, prior)
        # Split-half aleatorio de eventos dentro de cada celda: mide ruido de muestreo.
        mitad = rng.random(len(uso)) < 0.5
        sub = uso["h3_index"]
        ca = tabla_conteos(sub[mitad], t[mitad], k).reindex(ok.index, fill_value=0).to_numpy()
        cb = tabla_conteos(sub[~mitad], t[~mitad], k).reindex(ok.index, fill_value=0).to_numpy()
        fia = fiabilidad_split_half(ca, cb, prior, alpha)
        # Split temporal: años pares vs impares. Mide si la firma es climatología (estable)
        # o episodio. El toque de queda 2020–21 cae en ambos lados.
        par = (uso["year"] % 2 == 0).to_numpy()
        ta = tabla_conteos(sub[par], t[par], k).reindex(ok.index, fill_value=0).to_numpy()
        tb = tabla_conteos(sub[~par], t[~par], k).reindex(ok.index, fill_value=0).to_numpy()
        fit = fiabilidad_split_half(ta, tb, prior, alpha)
        # Sin los años de toque de queda (2020–2021) contra solo ellos.
        cuarentena = uso["year"].isin([2020, 2021]).to_numpy()
        qa = tabla_conteos(sub[~cuarentena], t[~cuarentena], k).reindex(
            ok.index, fill_value=0).to_numpy()
        qb = tabla_conteos(sub[cuarentena], t[cuarentena], k).reindex(
            ok.index, fill_value=0).to_numpy()
        res["por_esquema"][esq] = {
            "perfil_ciudad": dict(zip(spec["nombres"], prior.round(4).tolist(), strict=True)),
            "alpha_dirichlet": alpha,
            "sobredispersion": sobredispersion(c),
            "fiabilidad_split_half_aleatorio": fia,
            "fiabilidad_split_half_años_par_impar": fit,
            "fiabilidad_sin_vs_con_toque_de_queda": fiabilidad_split_half(qa, qb, prior, alpha),
            "perfil_ciudad_toque_de_queda": dict(zip(
                spec["nombres"], (qb.sum(0) / qb.sum()).round(4).tolist(), strict=True)),
            "perfil_ciudad_sin_toque_de_queda": dict(zip(
                spec["nombres"], (qa.sum(0) / qa.sum()).round(4).tolist(), strict=True)),
        }
    p = res["por_esquema"][ESQUEMA_PRINCIPAL]
    res["muere"] = bool(
        res["celdas_sobre_piso"] < KILL_SPARSITY_MIN_CELDAS
        or res["cobertura_eventos_sobre_piso"] < KILL_SPARSITY_MIN_COBERTURA
        or p["fiabilidad_split_half_aleatorio"] < KILL_SPARSITY_MIN_FIABILIDAD
        or p["sobredispersion"] < KILL_SPARSITY_MIN_SOBREDISP)
    tabla = n_c.rename("n").reset_index()
    tabla["sobre_piso"] = tabla["n"] >= N_MIN
    return res, tabla


# ─── clustering (solo si las tres trampas sobreviven) ────────────────────────
def estabilidad(c: np.ndarray, prior: np.ndarray, alpha: float, rng) -> pd.DataFrame:
    """Por k: silhouette, ARI entre semillas, ARI bootstrap y el mismo par bajo el nulo.

    El nulo es la ciudad sin relojes: cada celda es multinomial del perfil de la ciudad
    con su propio n. k-means siempre devuelve k grupos; lo que distingue estructura de
    partición arbitraria es superar al nulo, no el valor absoluto de la silhouette.
    """
    x = firma(c, prior, alpha)
    n = c.sum(1)
    filas = []
    for k in K_RANGO:
        corridas = [kmeans(x, k, s) for s in range(N_SEMILLAS)]
        labs = [lb for lb, _ in corridas]
        ref = labs[int(np.argmin([i for _, i in corridas]))]
        ari_sem = [ari(labs[i], labs[j]) for i in range(len(labs))
                   for j in range(i + 1, len(labs))]
        boot = []
        for _ in range(B_BOOT):
            p_hat = c / n[:, None]
            cb = rng.multinomial(n, p_hat)
            lb, _ = kmeans(firma(cb, prior, alpha), k, int(rng.integers(1 << 31)), n_init=3)
            boot.append(ari(ref, lb))
        nulo_sil, nulo_boot = [], []
        for _ in range(N_NULO):
            c0 = rng.multinomial(n, np.broadcast_to(prior, (len(n), len(prior))))
            x0 = firma(c0, prior, alpha)
            l0, _ = kmeans(x0, k, int(rng.integers(1 << 31)), n_init=3)
            nulo_sil.append(silhouette(x0, l0))
            c1 = rng.multinomial(n, c0 / n[:, None])
            l1, _ = kmeans(firma(c1, prior, alpha), k, int(rng.integers(1 << 31)), n_init=3)
            nulo_boot.append(ari(l0, l1))
        filas.append({
            "k": k,
            "silhouette": silhouette(x, ref),
            "ari_semillas_media": float(np.mean(ari_sem)),
            "ari_semillas_min": float(np.min(ari_sem)),
            "ari_boot_media": float(np.mean(boot)),
            "ari_boot_p05": float(np.percentile(boot, 5)),
            "nulo_silhouette_media": float(np.mean(nulo_sil)),
            "nulo_silhouette_p95": float(np.percentile(nulo_sil, 95)),
            "nulo_ari_boot_media": float(np.mean(nulo_boot)),
            "nulo_ari_boot_p95": float(np.percentile(nulo_boot, 95)),
            "tam_min_cluster": int(np.bincount(ref).min()),
        })
    return pd.DataFrame(filas)


def elegir_k(est: pd.DataFrame) -> int | None:
    """El k más chico que supera al nulo en silhouette y en estabilidad bootstrap.

    Supera = silhouette > p95 del nulo Y ARI bootstrap p05 > p95 del nulo Y ARI bootstrap
    medio ≥ 0,75 (convención de estabilidad "buena" de Hennig 2007). Si ningún k cumple,
    None: no hay chronotypes y se reporta así.
    """
    ok = est[(est["silhouette"] > est["nulo_silhouette_p95"])
             & (est["ari_boot_p05"] > est["nulo_ari_boot_p95"])
             & (est["ari_boot_media"] >= 0.75)]
    return int(ok["k"].min()) if len(ok) else None


def describir_clusters(c: np.ndarray, lab: np.ndarray, prior: np.ndarray,
                       nombres: list[str]) -> pd.DataFrame:
    """Perfil agregado de cada cluster y su razón contra la ciudad, turno por turno.

    La etiqueta es descriptiva y sale del dato ("exceso en noche ×1,3"), no de la
    tipología nocturna/diurna/madrugada que traía la hipótesis.
    """
    filas = []
    for g in np.unique(lab):
        tot = c[lab == g].sum(0)
        p = tot / tot.sum()
        rr = p / prior
        j = int(np.argmax(rr))
        filas.append({"cluster": int(g), "n_celdas": int((lab == g).sum()),
                      "n_eventos": int(tot.sum()),
                      **{f"p_{nm}": float(v) for nm, v in zip(nombres, p, strict=True)},
                      **{f"rr_{nm}": float(v) for nm, v in zip(nombres, rr, strict=True)},
                      "etiqueta": f"exceso en {nombres[j]} ×{rr[j]:.2f}"})
    return pd.DataFrame(filas)


def mapa_por_turno(uso: pd.DataFrame, esquema: str, alpha_por: dict) -> pd.DataFrame:
    """Largo: celda × turno con conteo, proporción cruda, encogida y razón vs ciudad.

    Incluye TODAS las celdas con algún evento; las bajo piso llevan ``sobre_piso=False``
    y el notebook las deshilacha. Ninguna celda se omite.
    """
    spec = ESQUEMAS[esquema]
    k = len(spec["nombres"])
    t = turno_de(uso["hora_frac"].to_numpy(), esquema)
    c = tabla_conteos(uso["h3_index"], t, k)
    n = c.sum(axis=1).to_numpy()
    ok = n >= N_MIN
    prior = c.to_numpy()[ok].sum(0) / c.to_numpy()[ok].sum()
    ps = encoger(c.to_numpy(), prior, alpha_por[esquema])
    filas = []
    for j, nm in enumerate(spec["nombres"]):
        filas.append(pd.DataFrame({
            "h3_index": c.index, "esquema": esquema, "turno": nm, "turno_idx": j,
            "n_celda": n, "n_turno": c[j].to_numpy(),
            "p_cruda": c[j].to_numpy() / np.maximum(n, 1),
            "p_encogida": ps[:, j], "rr_ciudad": ps[:, j] / prior[j],
            "sobre_piso": ok,
        }))
    return pd.concat(filas, ignore_index=True)


def sensibilidad(ev: pd.DataFrame, esquema: str, k: int, celdas: np.ndarray,
                 ref: np.ndarray, alpha: float, rng) -> list[dict]:
    """¿La partición depende de las decisiones de las trampas? ARI contra la principal.

    Cada variante deshace UNA decisión: reincorporar los 00:00 exactos, reincorporar las
    aorísticas (con su hora puntual, que es lo que Ratcliffe desaconseja), re-sortear el
    heaping, o sacar los años de toque de queda. Se agrupa con el mismo k sobre las
    mismas celdas y se compara con la partición principal.
    """
    kk = len(ESQUEMAS[esquema]["nombres"])
    base = ~ev["exact_midnight"] & ~ev["aoristica"]
    variantes = {
        "con_00:00": ~ev["aoristica"],
        "con_aoristicas": ~ev["exact_midnight"],
        "resorteo_heaping": base,
        "sin_toque_de_queda": base & ~ev["year"].isin([2020, 2021]),
    }
    out = []
    for nombre, m in variantes.items():
        sub = ev[m]
        h = sub["hora_frac"].to_numpy()
        if nombre == "resorteo_heaping":
            h = jitter_heaping(h, sub["minuto"].to_numpy(), rng)
        c = tabla_conteos(sub["h3_index"], turno_de(h, esquema), kk).reindex(
            celdas, fill_value=0).to_numpy()
        prior = c.sum(0) / c.sum()
        lab, _ = kmeans(firma(c, prior, alpha), k, SEED)
        out.append({"esquema": esquema, "k": k, "variante": nombre,
                    "ari_vs_principal": ari(ref, lab), "n_eventos": int(c.sum())})
    return out


def moran_h3(celdas: np.ndarray, z: np.ndarray, rng, n_perm: int = 199) -> tuple[float, float]:
    """Moran's I con pesos binarios de primer anillo H3 y su p95 bajo permutación."""
    import h3

    idx = {h: i for i, h in enumerate(celdas)}
    pares = np.array([(i, idx[v]) for h, i in idx.items() for v in h3.grid_ring(h, 1)
                      if v in idx])
    if len(pares) == 0:
        return float("nan"), float("nan")

    def _i(v):
        v = v - v.mean()
        return float(len(v) / len(pares) * (v[pares[:, 0]] * v[pares[:, 1]]).sum() / (v @ v))

    nulo = [_i(rng.permutation(z)) for _ in range(n_perm)]
    return _i(np.asarray(z, dtype=float)), float(np.percentile(nulo, 95))


def estructura(uso: pd.DataFrame, celdas: np.ndarray, rng) -> dict:
    """¿Tipos o gradiente? ¿Reloj del lugar o de su mezcla de delitos?

    Tres diagnósticos sobre ``turnos4``, que responden a lo que el clustering no puede:
    - Ejes: fracción de varianza de la firma en su primer componente principal y sus
      cargas. Si un solo eje explica casi todo, las celdas viven en un continuo. El
      puntaje de cada celda en ese eje se guarda en ``eje.parquet``: si no hay tipos,
      el continuo ES el producto.
    - Composición: correlación de Spearman entre la firma de cada turno y la fracción de
      cada categoría en la celda. Si el "reloj" es la mezcla de delitos, no es del lugar.
    - Solo robo callejero: la misma prueba de heterogeneidad y estabilidad dentro de una
      sola categoría, donde la mezcla no puede explicar nada.
    """
    from scipy.stats import spearmanr

    nombres = ESQUEMAS["turnos4"]["nombres"]
    t = turno_de(uso["hora_frac"].to_numpy(), "turnos4")
    c = tabla_conteos(uso["h3_index"], t, 4).reindex(celdas, fill_value=0).to_numpy()
    prior = c.sum(0) / c.sum()
    alpha = estimar_precision(c, prior)
    x = firma(c, prior, alpha)
    val, vec = np.linalg.eigh(np.cov(x.T))
    orden = np.argsort(val)[::-1]
    val, vec = val[orden], vec[:, orden]
    pc1 = vec[:, 0] * np.sign(vec[np.argmax(np.abs(vec[:, 0])), 0])
    eje = pd.DataFrame({"h3_index": celdas, "eje_madrugada_tarde": x @ pc1,
                        "n_celda": c.sum(1)})
    admin = pd.read_parquet(fuentes.ruta("h3_admin"), columns=["h3_index", "distrito"])
    eje = eje.merge(admin, on="h3_index", how="left")
    eje.to_parquet(OUT / "eje.parquet", index=False)
    res: dict = {"pca_frac_var": (val / val.sum()).round(4).tolist(),
                 "pca1_cargas": dict(zip(nombres, pc1.round(3).tolist(), strict=True))}

    # ¿El eje es geografía o ruido espacial? Moran's I sobre vecinos H3 de primer anillo,
    # con nulo de permutación.
    res["moran_eje"], res["moran_eje_nulo_p95"] = moran_h3(eje["h3_index"].to_numpy(),
                                                           eje["eje_madrugada_tarde"]
                                                           .to_numpy(), rng)
    por_d = (eje.groupby("distrito")["eje_madrugada_tarde"].agg(["size", "median"])
             .query("size >= 8").sort_values("median"))
    res["distritos_extremo_tarde"] = por_d.head(6)["median"].round(3).to_dict()
    res["distritos_extremo_madrugada"] = por_d.tail(6)["median"].round(3).to_dict()

    mezcla = (pd.crosstab(uso["h3_index"], uso["crime_cat"], normalize="index")
              .reindex(celdas, fill_value=0))
    res["spearman_firma_vs_mezcla"] = {
        cat: {nm: float(spearmanr(mezcla[cat], x[:, j]).statistic)
              for j, nm in enumerate(nombres)}
        for cat in mezcla.columns if mezcla[cat].mean() > 0.02}

    rob = uso[uso["crime_cat"] == pulso.CAT]
    tr = turno_de(rob["hora_frac"].to_numpy(), "turnos4")
    cr_all = tabla_conteos(rob["h3_index"], tr, 4)
    cr_all = cr_all[cr_all.sum(axis=1) >= N_MIN]
    cr = cr_all.to_numpy()
    pr = cr.sum(0) / cr.sum()
    ar = estimar_precision(cr, pr)
    mitad = rng.random(len(rob)) < 0.5
    ca = tabla_conteos(rob["h3_index"][mitad], tr[mitad], 4).reindex(
        cr_all.index, fill_value=0).to_numpy()
    cb = tabla_conteos(rob["h3_index"][~mitad], tr[~mitad], 4).reindex(
        cr_all.index, fill_value=0).to_numpy()
    est = estabilidad(cr, pr, ar, rng)
    # ¿Es el MISMO eje? Puntaje de robo callejero sobre las cargas del eje de todos los
    # delitos, correlacionado con el puntaje de todos en las celdas comunes.
    xr = pd.Series(firma(cr, pr, ar) @ pc1, index=cr_all.index)
    comun = eje.set_index("h3_index")["eje_madrugada_tarde"].reindex(xr.index).dropna()
    rho_eje = float(spearmanr(comun, xr.loc[comun.index]).statistic)
    res["solo_robo_callejero"] = {
        "spearman_eje_robo_vs_todos": rho_eje,
        "celdas_sobre_piso": int(len(cr_all)),
        "perfil_ciudad": dict(zip(nombres, pr.round(4).tolist(), strict=True)),
        "sobredispersion": sobredispersion(cr),
        "fiabilidad_split_half_aleatorio": fiabilidad_split_half(ca, cb, pr, ar),
        "k_elegido": elegir_k(est),
        "estabilidad": est.round(4).to_dict(orient="records"),
    }
    return res


# ─── main ────────────────────────────────────────────────────────────────────
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(SEED)
    ev = cargar_eventos()
    print(f"  eventos limpios: {len(ev):,}")

    h_res, hist = auditar_heaping(ev, rng)
    a_res, mods = auditar_aoristica(ev)
    uso = ev[~ev["exact_midnight"] & ~ev["aoristica"]].reset_index(drop=True)
    s_res, tabla_n = auditar_sparsity(uso, rng)

    trampas = {
        "slug": SLUG, "unidad": UNIDAD, "años": [pulso.YEAR_LO, pulso.YEAR_HI],
        "inputs_sha256": sha_fuentes(), "semilla": SEED,
        "criterios": {k: v for k, v in globals().items() if k.startswith("KILL_")} | {
            "N_MIN": N_MIN},
        "heaping": h_res, "aoristica": a_res, "sparsity": s_res,
    }
    muere = [n for n in ("heaping", "aoristica", "sparsity") if trampas[n]["muere"]]
    trampas["veredicto"] = "kill" if muere else "sobrevive"
    trampas["trampas_que_matan"] = muere

    hist.to_parquet(OUT / "heaping_hora_minuto.parquet", index=False)
    mods.to_parquet(OUT / "aoristica_modalidades.parquet", index=False)
    tabla_n.to_parquet(OUT / "sparsity_celdas.parquet", index=False)

    if not muere:
        alpha_por = {e: s_res["por_esquema"][e]["alpha_dirichlet"] for e in ESQUEMAS}
        mapas = pd.concat([mapa_por_turno(uso, e, alpha_por) for e in ESQUEMAS],
                          ignore_index=True)
        mapas.to_parquet(OUT / "mapa_turno.parquet", index=False)
        trampas["clustering"] = {}
        asign, descr, ests, sens = [], [], [], []
        for esq, spec in ESQUEMAS.items():
            kk = len(spec["nombres"])
            m = mapas[(mapas["esquema"] == esq) & mapas["sobre_piso"]]
            c = (m.pivot(index="h3_index", columns="turno_idx", values="n_turno")
                 .reindex(columns=range(kk)).to_numpy())
            celdas = m["h3_index"].drop_duplicates().sort_values().to_numpy()
            prior = c.sum(0) / c.sum()
            est = estabilidad(c, prior, alpha_por[esq], rng).assign(esquema=esq)
            ests.append(est)
            k_sel = elegir_k(est)
            trampas["clustering"][esq] = {"k_elegido": k_sel}
            print(f"  {esq}: k elegido = {k_sel}")
            # Se guarda la partición de CADA k para que el notebook deje moverlo, y se
            # marca cuál pasó el criterio. Un k que no pasa se muestra como tal.
            x = firma(c, prior, alpha_por[esq])
            # La sensibilidad se mide en el k elegido; si ninguno pasó, en el de mejor
            # silhouette, declarado como tal: sigue siendo útil saber si esa partición
            # (que no pasó) al menos depende de las decisiones de limpieza.
            k_sens = k_sel or int(est.loc[est["silhouette"].idxmax(), "k"])
            ref, _ = kmeans(x, k_sens, SEED)
            sens.extend(sensibilidad(ev, esq, k_sens, celdas, ref, alpha_por[esq], rng))
            trampas["clustering"][esq]["k_sensibilidad"] = k_sens
            for k in K_RANGO:
                lab, _ = kmeans(x, k, SEED)
                asign.append(pd.DataFrame({"h3_index": celdas, "esquema": esq, "k": k,
                                           "cluster": lab}))
                descr.append(describir_clusters(c, lab, prior, spec["nombres"])
                             .assign(esquema=esq, k=k))
        celdas4 = (mapas[(mapas["esquema"] == "turnos4") & mapas["sobre_piso"]]["h3_index"]
                   .drop_duplicates().sort_values().to_numpy())
        trampas["estructura"] = estructura(uso, celdas4, rng)
        pd.concat(ests).to_parquet(OUT / "estabilidad.parquet", index=False)
        pd.DataFrame(sens).to_parquet(OUT / "sensibilidad.parquet", index=False)
        trampas["clustering"]["sensibilidad"] = sens
        trampas["clustering"]["estabilidad"] = pd.concat(ests).to_dict(orient="records")
        pd.concat(asign).to_parquet(OUT / "clusters.parquet", index=False)
        pd.concat(descr).to_parquet(OUT / "clusters_perfil.parquet", index=False)

    (OUT / "trampas.json").write_text(json.dumps(trampas, indent=2, ensure_ascii=False,
                                                 default=float))
    print(f"  veredicto de las trampas: {trampas['veredicto']} {muere}")
    print(f"  → {OUT}")


if __name__ == "__main__":
    main()
