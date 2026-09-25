"""Tests de `reloj-de-riesgo` (E8).

Casi todo corre sin datos: turnos, re-sorteo del heaping, firmas composicionales,
sobredispersión, fiabilidad split-half, k-means, ARI y silhouette son aritmética pura y se
ejercitan con tablas sintéticas. Sólo el contrato de los artefactos necesita `data/`, y va
marcado `needs_data`.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_LOADER = Path(__file__).resolve().parents[1] / "experiments/reloj-de-riesgo/loader.py"
_spec = importlib.util.spec_from_file_location("reloj_loader", _LOADER)
loader = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(loader)


# ─── turnos ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(("hora", "turno"), [
    (0.0, 0), (5.99, 0), (6.0, 1), (11.5, 1), (12.0, 2), (17.99, 2), (18.0, 3), (23.99, 3),
    (24.0, 0),
])
def test_turno_de_turnos4_respeta_los_bordes_de_sidpol(hora, turno):
    assert loader.turno_de(np.array([hora]), "turnos4")[0] == turno


def test_turno_de_bloques6_cubre_seis_bloques():
    h = np.arange(0, 24, 0.5)
    t = loader.turno_de(h, "bloques6")
    assert set(t) == set(range(6))
    assert (np.bincount(t) == 8).all()


# ─── heaping ─────────────────────────────────────────────────────────────────
def test_semiancho_redondeo_por_minuto():
    w = loader.semiancho_redondeo(np.array([0, 30, 15, 7]))
    assert w.tolist() == [30.0, 15.0, 2.5, 0.0]


def test_jitter_no_mueve_minutos_no_redondeados_y_acota_los_redondeados():
    rng = np.random.default_rng(0)
    h = np.array([10.0 + 7 / 60] * 100 + [18.0] * 1000)
    m = np.array([7] * 100 + [0] * 1000)
    j = loader.jitter_heaping(h, m, rng)
    assert np.allclose(j[:100], h[:100])
    assert (np.abs(j[100:] - 18.0) <= 0.5 + 1e-9).all()
    # Un 18:00 redondeado cae la mitad de las veces en la tarde.
    frac_tarde = (loader.turno_de(j[100:], "turnos4") == 2).mean()
    assert 0.4 < frac_tarde < 0.6


# ─── firmas ──────────────────────────────────────────────────────────────────
def test_encoger_con_alpha_cero_es_la_proporcion_cruda_y_con_alpha_enorme_la_ciudad():
    c = np.array([[10, 0, 0, 0], [1, 1, 1, 1]])
    prior = np.full(4, 0.25)
    assert np.allclose(loader.encoger(c, prior, 0.0)[0], [1, 0, 0, 0])
    assert np.allclose(loader.encoger(c, prior, 1e9), prior, atol=1e-6)


def test_firma_de_una_celda_igual_a_la_ciudad_es_cero():
    prior = np.array([0.1, 0.2, 0.3, 0.4])
    c = (prior * 1000).astype(int)[None, :]
    assert np.allclose(loader.firma(c, prior, 50.0), 0.0, atol=1e-9)


def _ciudad(n_celdas, n, prior, rng, tipos=None):
    """Celdas multinomiales; con `tipos`, cada celda saca su perfil de uno de ellos."""
    if tipos is None:
        return rng.multinomial(n, np.broadcast_to(prior, (n_celdas, len(prior))))
    lab = rng.integers(0, len(tipos), n_celdas)
    return rng.multinomial(n, np.asarray(tipos)[lab]), lab


def test_sobredispersion_distingue_ciudad_homogenea_de_ciudad_con_relojes():
    rng = np.random.default_rng(1)
    prior = np.array([0.15, 0.25, 0.3, 0.3])
    homog = _ciudad(500, 300, prior, rng)
    assert 0.8 < loader.sobredispersion(homog) < 1.2
    tipos = [[0.30, 0.20, 0.20, 0.30], [0.05, 0.30, 0.40, 0.25]]
    con, _ = _ciudad(500, 300, prior, rng, tipos)
    assert loader.sobredispersion(con) > 3


def test_estimar_precision_recupera_orden_de_magnitud():
    rng = np.random.default_rng(2)
    prior = np.array([0.15, 0.25, 0.3, 0.3])
    alpha = 100.0
    p = rng.dirichlet(alpha * prior, 3000)
    c = rng.multinomial(400, p)
    est = loader.estimar_precision(c, prior)
    assert 50 < est < 200


def test_fiabilidad_split_half_alta_con_relojes_y_nula_sin_ellos():
    rng = np.random.default_rng(3)
    prior = np.array([0.15, 0.25, 0.3, 0.3])
    tipos = np.array([[0.30, 0.20, 0.20, 0.30], [0.05, 0.30, 0.40, 0.25]])
    lab = rng.integers(0, 2, 400)
    ca, cb = rng.multinomial(300, tipos[lab]), rng.multinomial(300, tipos[lab])
    assert loader.fiabilidad_split_half(ca, cb, prior, 50.0) > 0.8
    ha = rng.multinomial(300, np.broadcast_to(prior, (400, 4)))
    hb = rng.multinomial(300, np.broadcast_to(prior, (400, 4)))
    assert abs(loader.fiabilidad_split_half(ha, hb, prior, 50.0)) < 0.3


# ─── clustering ──────────────────────────────────────────────────────────────
def test_ari_identico_permutado_y_aleatorio():
    a = np.array([0, 0, 1, 1, 2, 2] * 50)
    assert loader.ari(a, a) == pytest.approx(1.0)
    assert loader.ari(a, (a + 1) % 3) == pytest.approx(1.0)
    rng = np.random.default_rng(4)
    assert abs(loader.ari(a, rng.integers(0, 3, len(a)))) < 0.05


def test_canonizar_numera_por_tamano():
    lab = np.array([2, 2, 2, 0, 1, 1])
    assert loader.canonizar(lab, None).tolist() == [0, 0, 0, 2, 1, 1]


def test_silhouette_alta_en_grupos_separados():
    rng = np.random.default_rng(5)
    x = np.vstack([rng.normal(0, 0.1, (50, 2)), rng.normal(5, 0.1, (50, 2))])
    lab = np.array([0] * 50 + [1] * 50)
    assert loader.silhouette(x, lab) > 0.9


def test_kmeans_y_estabilidad_recuperan_dos_relojes_plantados():
    rng = np.random.default_rng(6)
    prior = np.array([0.15, 0.25, 0.3, 0.3])
    tipos = [[0.40, 0.15, 0.15, 0.30], [0.05, 0.30, 0.40, 0.25]]
    c, verdad = _ciudad(200, 400, prior, rng, tipos)
    prior_obs = c.sum(0) / c.sum()
    x = loader.firma(c, prior_obs, 50.0)
    lab, _ = loader.kmeans(x, 2, 0)
    assert loader.ari(lab, verdad) > 0.95


def test_elegir_k_devuelve_none_si_nada_supera_al_nulo():
    est = pd.DataFrame({
        "k": [2, 3], "silhouette": [0.3, 0.3], "nulo_silhouette_p95": [0.4, 0.4],
        "ari_boot_p05": [0.9, 0.9], "nulo_ari_boot_p95": [0.5, 0.5],
        "ari_boot_media": [0.95, 0.95],
    })
    assert loader.elegir_k(est) is None
    est.loc[1, "silhouette"] = 0.5
    assert loader.elegir_k(est) == 3


def test_describir_clusters_etiqueta_por_el_turno_de_mayor_exceso():
    c = np.array([[50, 10, 10, 30], [5, 30, 40, 25]])
    prior = c.sum(0) / c.sum()
    d = loader.describir_clusters(c, np.array([0, 1]), prior, ["a", "b", "c", "d"])
    assert d.loc[0, "etiqueta"].startswith("exceso en a")
    assert d.loc[1, "etiqueta"].startswith("exceso en c")


# ─── artefactos ──────────────────────────────────────────────────────────────
@pytest.mark.needs_data
def test_artefactos_declaran_unidad_y_veredicto():
    t = json.loads((loader.OUT / "trampas.json").read_text())
    assert t["unidad"] == "h3_8"
    assert t["veredicto"] in {"kill", "sobrevive"}
    for trampa in ("heaping", "aoristica", "sparsity"):
        assert "muere" in t[trampa]
    if t["veredicto"] == "sobrevive":
        m = pd.read_parquet(loader.OUT / "mapa_turno.parquet")
        # Ninguna celda con evento se omite: las bajo piso van marcadas, no borradas.
        n_celdas = t["sparsity"]["n_celdas_con_evento"]
        assert m.groupby("esquema")["h3_index"].nunique().eq(n_celdas).all()
        assert {"sobre_piso", "n_celda", "p_encogida"} <= set(m.columns)


# ─── chequeo posterior (literatura): heaping por modalidad y subconjuntos ────
_CHQ = Path(__file__).resolve().parents[1] / "experiments/reloj-de-riesgo/chequeo_literatura.py"
_spec_c = importlib.util.spec_from_file_location("reloj_chequeo", _CHQ)
chequeo = importlib.util.module_from_spec(_spec_c)
_spec_c.loader.exec_module(chequeo)


def test_em_recupera_las_tasas_de_redondeo_sinteticas():
    rng = np.random.default_rng(0)
    pi = np.array([0.3, 0.3, 0.05, 0.25, 0.1])
    n = 200_000
    r = rng.choice(chequeo.RESOLUCIONES, size=n, p=pi)
    verdad = rng.uniform(0, 60, n)
    m = (np.round(verdad / r) * r % 60).astype(int)
    est = chequeo.em_redondeo(np.bincount(m, minlength=60))
    assert est.sum() == pytest.approx(1.0)
    assert np.abs(est - pi).max() < 0.02


def test_la_posterior_solo_pone_peso_en_resoluciones_compatibles():
    post = chequeo.posterior_resolucion(np.full(5, 0.2))
    assert np.allclose(post.sum(1), 1.0)
    assert post[7, :4].sum() == 0.0  # el minuto 7 solo es compatible con r = 1
    assert post[0].min() > 0.0  # el minuto 0 es compatible con todas


def test_truncado_no_cruza_bordes_de_turno_en_hora_en_punto():
    rng = np.random.default_rng(1)
    h = np.array([5.0, 6.0, 11.5, 17.0, 18.0])
    mi = np.array([0, 0, 30, 0, 0])
    g = np.array(["a"] * 5)
    post = {"a": chequeo.posterior_resolucion(np.array([1.0, 0, 0, 0, 0]))}
    for _ in range(50):
        h1 = chequeo.resortear(h, mi, g, post, "truncado", rng)
        assert (loader.turno_de(h1, "turnos4") == loader.turno_de(h, "turnos4")).all()
    h1 = chequeo.resortear(h, mi, g, post, "hacia_arriba", rng)
    assert loader.turno_de(h1, "turnos4")[1] == 0  # 06:00 redondeado hacia arriba es madrugada


def test_subconjuntos_respetan_el_piso_y_los_cuantiles():
    n = pd.Series({f"c{i}": 50 + 10 * i for i in range(30)})
    poi = pd.Series({f"c{i}": i % 7 for i in range(30)})
    s = chequeo.subconjuntos(n, poi)
    elegibles = set(n[n >= loader.N_MIN].index)
    assert set(s["hot_spots"]) <= elegibles and set(s["comerciales"]) <= elegibles
    assert n[s["hot_spots"]].min() >= n[list(elegibles)].quantile(chequeo.Q_HOTSPOT)
