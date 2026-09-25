"""Métricas globales y locales de la red ``drive`` del área A (bead ``inwatch-92d.9``).

El Hito 1 pide "primeras métricas globales y locales" y "análisis exploratorio espacial".
La betweenness ya está (``centralidad.py``); esta etapa pone al lado lo que la hace
interpretable: qué tan grande, densa, conexa y ordenada es la red sobre la que se mide.

Tres decisiones, cada una por un error que evita:

- **Normalizado por área.** El enunciado exige normalizar las métricas que dependen de
  la escala. Un conteo de intersecciones no compara dos áreas; intersecciones por km² sí.
  El área sale del mismo polígono versionado con el que se descargó el grafo, proyectado
  a EPSG:32718, no de una cifra escrita a mano.
- **Orientación con las dos direcciones de cada calle.** Una calle de rumbo 10° también
  corre a 190°. Contar solo una dirección partiría una grilla perfecta en dos picos
  asimétricos según el sentido de digitalización de OSM. Es el método de Boeing (2019):
  36 bins de 10° centrados en los rumbos cardinales, peso = longitud. El rumbo se toma en
  la grilla UTM; la convergencia de meridianos en Lima es ~0,4°, menos que medio bin.
- **Closeness solo en la componente fuertemente conexa gigante.** En un dígrafo con
  varias componentes, la closeness de networkx promedia distancias a lo alcanzable y
  premia a los nodos atrapados en islas chicas. Restringida a la gigante, compara nodos
  que ven el mismo conjunto de destinos.

    uv run python experiments/corredores-criticos/metricas.py
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

SLUG = "corredores-criticos"
VARIANTE = "area_a_drive"
OUT = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG
GRAPHML = "area_a_drive.graphml"
FUENTE_POLIGONO = "distritos_limites_area_a"
UBIGEOS = ("150101", "150115", "150131", "150122", "150141")
CRS_METRICO = "EPSG:32718"
N_BINS = 36


# ─── globales ─────────────────────────────────────────────────────────────────
def componentes(G: nx.MultiDiGraph) -> dict:
    """Número de componentes y peso de la gigante, fuerte y débil."""
    fuertes = list(nx.strongly_connected_components(G))
    debiles = list(nx.weakly_connected_components(G))
    n = G.number_of_nodes()
    return {
        "n_scc": len(fuertes),
        "n_wcc": len(debiles),
        "pct_nodos_scc_gigante": 100 * max(map(len, fuertes)) / n,
        "pct_nodos_wcc_gigante": 100 * max(map(len, debiles)) / n,
    }


def grados(G: nx.MultiDiGraph) -> dict:
    """Grado medio y reparto de ``street_count``, el grado físico de la intersección.

    El grado del dígrafo cuenta arcos (una calle de doble sentido suma dos) y no dice
    cuántas calles confluyen; ``street_count`` de osmnx sí, y es el que se usa en la
    literatura de forma urbana (callejones = 1, trifurcaciones = 3, cruces = 4).
    """
    n = G.number_of_nodes()
    calles = pd.Series(dict(G.nodes(data="street_count")), dtype=float)
    if calles.isna().any():
        raise ValueError(f"{int(calles.isna().sum())} nodos sin street_count")
    return {
        "grado_medio_salida": G.number_of_edges() / n,
        "calles_por_nodo": float(calles.mean()),
        "pct_nodos_callejon": 100 * float((calles == 1).mean()),
        "pct_nodos_3_calles": 100 * float((calles == 3).mean()),
        "pct_nodos_4_o_mas": 100 * float((calles >= 4).mean()),
    }


def densidad_x1e4(G: nx.MultiDiGraph) -> float:
    """Densidad dirigida m / n(n−1), ×10⁴ para que no se redondee a cero."""
    n = G.number_of_nodes()
    return 1e4 * G.number_of_edges() / (n * (n - 1))


def circuidad(tramos: pd.DataFrame, nodos_xy: pd.DataFrame) -> float:
    """Longitud recorrida sobre distancia en línea recta, sumadas sobre los tramos.

    Es la media ponderada por longitud que usa osmnx (``stats.circuity_avg``). Los lazos
    (u == v) no tienen recta y se excluyen: dividirían por cero.
    """
    t = tramos[tramos["u"] != tramos["v"]]
    xu, yu = nodos_xy.loc[t["u"], "x"].to_numpy(), nodos_xy.loc[t["u"], "y"].to_numpy()
    xv, yv = nodos_xy.loc[t["v"], "x"].to_numpy(), nodos_xy.loc[t["v"], "y"].to_numpy()
    recta = np.hypot(xv - xu, yv - yu)
    return float(t["largo_m"].sum() / recta.sum())


def rumbos(tramos: pd.DataFrame, nodos_xy: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Rumbo desde el norte, en grados [0, 360), y longitud de cada tramo no lazo."""
    t = tramos[tramos["u"] != tramos["v"]]
    dx = nodos_xy.loc[t["v"], "x"].to_numpy() - nodos_xy.loc[t["u"], "x"].to_numpy()
    dy = nodos_xy.loc[t["v"], "y"].to_numpy() - nodos_xy.loc[t["u"], "y"].to_numpy()
    return np.degrees(np.arctan2(dx, dy)) % 360, t["largo_m"].to_numpy(dtype=float)


def histograma_orientacion(rumbo: np.ndarray, peso: np.ndarray, n_bins: int = N_BINS) -> np.ndarray:
    """Masa por bin, con las dos direcciones de cada calle y bins centrados en 0°."""
    ancho = 360 / n_bins
    ambos = np.concatenate([rumbo, (rumbo + 180) % 360])
    pesos = np.concatenate([peso, peso])
    # Corrido medio bin: el bin 0 cubre [−5°, 5°) y el norte cae en su centro.
    idx = np.floor(((ambos + ancho / 2) % 360) / ancho).astype(int)
    return np.bincount(idx, weights=pesos, minlength=n_bins)


def orientacion(masa: np.ndarray) -> dict:
    """Entropía de Shannon de la orientación y orden φ de Boeing (2019).

    φ = 1 − ((H − H_grilla) / (H_max − H_grilla))², con H_grilla = ln 4 (una grilla
    perfecta llena 4 bins por igual) y H_max = ln n_bins (todas las direcciones por igual).
    φ = 1 es una grilla perfecta; φ ≈ 0, calles en todas las direcciones.
    """
    p = masa / masa.sum()
    p = p[p > 0]
    h = float(-(p * np.log(p)).sum())
    h_max, h_grilla = math.log(len(masa)), math.log(4)
    return {"entropia": h, "orden": 1 - ((h - h_grilla) / (h_max - h_grilla)) ** 2}


def clustering_medio(G: nx.MultiDiGraph) -> float:
    """Clustering medio del grafo simple no dirigido: triángulos de calles."""
    return float(nx.average_clustering(nx.Graph(G.to_undirected())))


# ─── locales ──────────────────────────────────────────────────────────────────
def closeness_gigante(D: nx.DiGraph, *, peso: str = "length") -> pd.Series:
    """Closeness por distancia de viaje en la SCC gigante; NaN fuera de ella.

    Es la closeness **de llegada** de networkx (distancias hacia el nodo). En un dígrafo
    vial es la que responde "qué tan cerca está esta intersección del resto", porque es
    lo que se recorre para alcanzarla.
    """
    gigante = max(nx.strongly_connected_components(D), key=len)
    sub = D.subgraph(gigante)
    valores = nx.closeness_centrality(sub, distance=peso)
    return pd.Series(valores, dtype=float).reindex(list(D.nodes))


def area_km2(poligono_4326) -> float:
    import geopandas as gpd

    return float(gpd.GeoSeries([poligono_4326], crs="EPSG:4326").to_crs(CRS_METRICO).area.iloc[0]
                 / 1e6)


# ─── ejecución ────────────────────────────────────────────────────────────────
def main() -> None:
    import importlib.util

    from inwatch import canon, fuentes
    from inwatch.unidades import red_vial

    ruta = OUT / GRAPHML
    if not ruta.exists():
        raise FileNotFoundError(f"falta {ruta}: corre antes experiments/{SLUG}/loader.py")
    ruta_bc = OUT / "betweenness_intersecciones.parquet"
    if not ruta_bc.exists():
        raise FileNotFoundError(f"falta {ruta_bc}: corre antes experiments/{SLUG}/centralidad.py")

    # El dígrafo colapsado es el de centralidad.py: misma red para closeness y betweenness.
    spec = importlib.util.spec_from_file_location("_centralidad", Path(__file__).with_name(
        "centralidad.py"))
    centralidad = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(centralidad)

    distritos = fuentes.resolver(FUENTE_POLIGONO)
    area = area_km2(red_vial.poligono_distritos(distritos.ruta, UBIGEOS))
    G, _ = red_vial.cargar(ruta)
    D = centralidad.a_digrafo(G)
    tramos = red_vial.tramos(G)
    nodos_xy = pd.DataFrame.from_dict(dict(G.nodes(data=True)), orient="index")[["x", "y"]]

    g: dict = {"area_km2": area, "densidad_x1e4": densidad_x1e4(G)}
    g |= componentes(G) | grados(G)
    g["intersecciones_por_km2"] = sum(
        1 for _, c in G.nodes(data="street_count") if c > 1
    ) / area
    g["km_calle_por_km2"] = float(tramos["largo_m"].sum()) / 1000 / area
    g["largo_medio_tramo_m"] = float(tramos["largo_m"].mean())
    g["circuidad"] = circuidad(tramos, nodos_xy)
    masa = histograma_orientacion(*rumbos(tramos, nodos_xy))
    g |= {f"orientacion_{k}": v for k, v in orientacion(masa).items()}
    g["clustering_medio"] = clustering_medio(G)

    t0 = time.perf_counter()
    cercania = closeness_gigante(D)
    segundos_closeness = round(time.perf_counter() - t0, 1)

    bc = pd.read_parquet(ruta_bc).set_index("node_id")
    tabla = pd.DataFrame({
        "node_id": [str(n) for n in D.nodes],
        "street_count": [G.nodes[n]["street_count"] for n in D.nodes],
        "grado_entrada": [D.in_degree(n) for n in D.nodes],
        "grado_salida": [D.out_degree(n) for n in D.nodes],
        "closeness_length": cercania.to_numpy(),
    })
    tabla["en_scc_gigante"] = tabla["closeness_length"].notna()
    tabla = tabla.merge(bc[["bc_length"]], left_on="node_id", right_index=True, how="left")
    en_gigante = tabla[tabla["en_scc_gigante"]]
    g["rho_closeness_betweenness"] = float(
        spearmanr(en_gigante["closeness_length"], en_gigante["bc_length"]).statistic
    )

    def emitir(clave: str, valor: float, unidad: str, estimador: str, inputs: list) -> None:
        canon.emit(clave, float(valor), variant=VARIANTE, unit=unidad, estimator=estimador,
                   inputs=inputs, script=__file__)

    solo_grafo = [ruta]
    con_area = [distritos.ruta, ruta]
    emisiones = [
        ("corredores.area.km2", "area_km2", "km²", "polígono del área A en EPSG:32718",
         [distritos.ruta]),
        ("corredores.area.intersecciones_por_km2", "intersecciones_por_km2", "intersecciones/km²",
         "nodos con street_count > 1 sobre el área", con_area),
        ("corredores.area.km_calle_por_km2", "km_calle_por_km2", "km/km²",
         "suma de tramos no dirigidos sobre el área", con_area),
        ("corredores.red.densidad_x1e4", "densidad_x1e4", "m/n(n−1) × 10⁴", "dígrafo simplificado",
         solo_grafo),
        ("corredores.red.grado_medio_salida", "grado_medio_salida", "arcos por nodo", "m/n",
         solo_grafo),
        ("corredores.red.calles_por_nodo", "calles_por_nodo", "calles por intersección",
         "media de street_count", solo_grafo),
        ("corredores.red.circuidad", "circuidad", "adim.",
         "Σ largo / Σ recta, tramos no dirigidos sin lazos", solo_grafo),
        ("corredores.red.orientacion_entropia", "orientacion_entropia", "nats",
         f"Shannon, {N_BINS} bins, dos direcciones, peso = largo", solo_grafo),
        ("corredores.red.orientacion_orden", "orientacion_orden", "φ de Boeing (2019)",
         "1 − ((H − ln 4)/(ln 36 − ln 4))²", solo_grafo),
        ("corredores.red.clustering_medio", "clustering_medio", "adim.",
         "grafo simple no dirigido", solo_grafo),
        ("corredores.conteo.scc", "n_scc", "componentes", "fuertemente conexas", solo_grafo),
        ("corredores.conteo.wcc", "n_wcc", "componentes", "débilmente conexas", solo_grafo),
        ("corredores.pct.nodos_scc_gigante", "pct_nodos_scc_gigante", "% de nodos",
         "SCC más grande", solo_grafo),
        ("corredores.pct.nodos_callejon", "pct_nodos_callejon", "% de nodos", "street_count = 1",
         solo_grafo),
        ("corredores.pct.nodos_3_calles", "pct_nodos_3_calles", "% de nodos", "street_count = 3",
         solo_grafo),
        ("corredores.pct.nodos_4_o_mas", "pct_nodos_4_o_mas", "% de nodos", "street_count ≥ 4",
         solo_grafo),
        ("corredores.corr.closeness_betweenness_nodos", "rho_closeness_betweenness",
         "rho de Spearman", "closeness de llegada vs betweenness, por length, en la SCC gigante",
         [ruta, ruta_bc]),
    ]
    for clave, campo, unidad, estimador, inputs in emisiones:
        emitir(clave, g[campo], unidad, estimador, inputs)

    OUT.mkdir(parents=True, exist_ok=True)
    tabla.to_parquet(OUT / "metricas_intersecciones.parquet", index=False)
    pd.DataFrame({
        "bin_centro_grados": np.arange(N_BINS) * (360 / N_BINS),
        "masa_m": masa,
    }).to_parquet(OUT / "orientacion.parquet", index=False)
    (OUT / "metricas.meta.json").write_text(
        json.dumps({**g, "segundos_closeness": segundos_closeness}, ensure_ascii=False, indent=2)
        + "\n", encoding="utf-8"
    )
    print(f"  → {OUT}  área {area:.1f} km² · {g['n_scc']} SCC · φ = {g['orientacion_orden']:.3f} "
          f"· closeness en {segundos_closeness} s")


if __name__ == "__main__":
    main()
