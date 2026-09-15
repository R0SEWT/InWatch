"""Betweenness dirigida del área A, por longitud y por tiempo de viaje (bead ``inwatch-92d.3``).

Consume el GraphML que deja ``loader.py`` y produce dos tablas sin geometría, una por
unidad del contrato: ``interseccion`` (``node_id``) y ``tramo`` (``tramo_id``).

Tres decisiones, cada una por un error que evita:

- **Dirigida.** Sobre el grafo no dirigido, una vía de un solo sentido cargaría caminos
  que ningún vehículo puede recorrer, y los corredores saldrían donde no hay paso.
- **Paralelas colapsadas por peso, no por arista.** Entre dos intersecciones puede haber
  una arista más corta y otra más rápida. Quedarse con una sola para ambos pesos haría
  que la betweenness por tiempo se calculara sobre la ruta corta, en silencio.
- **Exacta en el área A.** Con ~7.500 nodos el cálculo exacto cuesta minutos. La
  aproximación con ``k`` se corre igual sobre el mismo grafo y se compara contra la
  exacta: el error queda **medido**, no supuesto, que es lo que el enunciado pide cuando
  se usa muestreo.

Normalización de networkx para grafos dirigidos: nodos por (n−1)(n−2), aristas por n(n−1).

    uv run python experiments/corredores-criticos/centralidad.py
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import networkx as nx
import pandas as pd
from scipy.stats import spearmanr

SLUG = "corredores-criticos"
VARIANTE = "area_a_drive"
OUT = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG
GRAPHML = "area_a_drive.graphml"
PESOS = ("length", "travel_time")
SEED = 42
K_APROX = 500
TOP = 100


def _falta(valor) -> bool:
    return valor is None or (isinstance(valor, float) and math.isnan(valor))


def a_digrafo(G: nx.MultiDiGraph, pesos: tuple[str, ...] = PESOS) -> nx.DiGraph:
    """Colapsa aristas paralelas guardando, por peso, el mínimo y la clave que lo aporta."""
    D = nx.DiGraph(crs=G.graph.get("crs"))
    for n, datos in G.nodes(data=True):
        D.add_node(n, x=datos.get("x"), y=datos.get("y"))
    for u, v, k, datos in G.edges(keys=True, data=True):
        for p in pesos:
            if _falta(datos.get(p)):
                raise ValueError(f"la arista ({u}, {v}, {k}) no tiene {p}")
        if not D.has_edge(u, v):
            D.add_edge(u, v, **{p: float(datos[p]) for p in pesos},
                       **{f"key_{p}": k for p in pesos})
            continue
        actual = D[u][v]
        for p in pesos:
            if float(datos[p]) < actual[p]:
                actual[p] = float(datos[p])
                actual[f"key_{p}"] = k
    return D


def betweenness(
    D: nx.DiGraph, *, peso: str, k: int | None = None, seed: int = SEED
) -> tuple[pd.Series, pd.Series]:
    """Betweenness normalizada de nodos y de arcos. ``k=None`` es exacta."""
    nodos = nx.betweenness_centrality(D, k=k, normalized=True, weight=peso, seed=seed)
    arcos = nx.edge_betweenness_centrality(D, k=k, normalized=True, weight=peso, seed=seed)
    return pd.Series(nodos, dtype=float), pd.Series(arcos, dtype=float)


def _par(u, v) -> tuple:
    return tuple(sorted((u, v), key=str))


def a_tramos(arcos: pd.Series, tramos: pd.DataFrame) -> pd.DataFrame:
    """Lleva la betweenness de arcos dirigidos a tramos no dirigidos.

    Los dos sentidos de una calle se **suman**: el flujo potencial de la calle es el de
    ambos. Entre tramos paralelos, la cifra va a la más corta y las demás quedan en 0,
    que es su valor real: ningún camino mínimo por longitud las usa.
    """
    por_par: dict[tuple, float] = {}
    for (u, v), valor in arcos.items():
        clave = _par(u, v)
        por_par[clave] = por_par.get(clave, 0.0) + float(valor)

    t = tramos[["tramo_id", "u", "v", "largo_m"]].copy()
    t["_par"] = [_par(u, v) for u, v in zip(t["u"], t["v"], strict=True)]
    sin_tramo = set(por_par) - set(t["_par"])
    if sin_tramo:
        raise ValueError(f"{len(sin_tramo)} arcos no tienen tramo, p. ej. {sorted(sin_tramo)[:3]}")

    t["betweenness"] = 0.0
    elegidos = t.groupby("_par", sort=False)["largo_m"].idxmin()
    t.loc[elegidos.to_numpy(), "betweenness"] = [por_par.get(p, 0.0) for p in elegidos.index]
    return t[["tramo_id", "betweenness"]].reset_index(drop=True)


def comparar(aprox: pd.Series, exacta: pd.Series, *, top: int) -> dict[str, float]:
    """Error de la aproximación: Spearman sobre todas las unidades y solape del top."""
    if top > len(exacta):
        raise ValueError(f"top={top} es mayor que las {len(exacta)} unidades")
    a = aprox.reindex(exacta.index).fillna(0.0)
    top_a = set(a.nlargest(top).index)
    top_e = set(exacta.nlargest(top).index)
    return {
        "spearman": float(spearmanr(a.to_numpy(), exacta.to_numpy()).statistic),
        "solape_top": len(top_a & top_e) / top,
    }


# ─── ejecución ────────────────────────────────────────────────────────────────
def main() -> None:
    from inwatch import canon
    from inwatch.unidades import red_vial

    ruta = OUT / GRAPHML
    if not ruta.exists():
        raise FileNotFoundError(f"falta {ruta}: corre antes experiments/{SLUG}/loader.py")
    G, _ = red_vial.cargar(ruta)
    D = a_digrafo(G)
    tramos = red_vial.tramos(G)

    tabla_nodos = pd.DataFrame({"node_id": [str(n) for n in D.nodes]})
    tabla_tramos = tramos[["tramo_id"]].copy()
    exactas: dict[str, tuple[pd.Series, pd.Series]] = {}
    registro: dict = {"k_aprox": K_APROX, "top": TOP, "seed": SEED, "segundos": {}}

    def emitir(clave: str, valor: float, unidad: str, estimador: str) -> None:
        canon.emit(clave, float(valor), variant=VARIANTE, unit=unidad, estimator=estimador,
                   inputs=[ruta], script=__file__)

    for peso in PESOS:
        t0 = time.perf_counter()
        nodos, arcos = betweenness(D, peso=peso)
        registro["segundos"][f"exacta_{peso}"] = round(time.perf_counter() - t0, 1)
        exactas[peso] = (nodos, arcos)
        tabla_nodos[f"bc_{peso}"] = nodos.reindex(list(D.nodes)).to_numpy()
        por_tramo = a_tramos(arcos, tramos).rename(columns={"betweenness": f"bc_{peso}"})
        tabla_tramos = tabla_tramos.merge(por_tramo, on="tramo_id", how="left")

        t0 = time.perf_counter()
        nodos_k, arcos_k = betweenness(D, peso=peso, k=K_APROX)
        registro["segundos"][f"aprox_{peso}"] = round(time.perf_counter() - t0, 1)
        for unidad, (aprox, exacta) in {"nodos": (nodos_k, nodos),
                                        "aristas": (arcos_k, arcos)}.items():
            error = comparar(aprox, exacta, top=TOP)
            estimador = f"k={K_APROX} vs exacta, seed={SEED}"
            emitir(f"corredores.error.spearman_{unidad}_{peso}", error["spearman"],
                   "rho de Spearman", estimador)
            emitir(f"corredores.error.solape_top_{unidad}_{peso}", error["solape_top"],
                   f"fracción del top-{TOP} compartida", estimador)

    for tabla, unidad in ((tabla_nodos, "nodos"), (tabla_tramos, "tramos")):
        for peso in PESOS:
            tabla[f"rango_{peso}"] = tabla[f"bc_{peso}"].rank(ascending=False, method="min")
        rho = spearmanr(tabla["bc_length"], tabla["bc_travel_time"]).statistic
        emitir(f"corredores.corr.length_travel_time_{unidad}", rho, "rho de Spearman",
               "betweenness exacta por length vs por travel_time")

    emitir("corredores.conteo.k_aprox", K_APROX, "fuentes muestreadas", "parámetro k de networkx")
    OUT.mkdir(parents=True, exist_ok=True)
    tabla_nodos.to_parquet(OUT / "betweenness_intersecciones.parquet", index=False)
    tabla_tramos.to_parquet(OUT / "betweenness_tramos.parquet", index=False)
    (OUT / "betweenness.meta.json").write_text(
        json.dumps(registro, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"  → {OUT}  ({len(tabla_nodos):,} intersecciones · {len(tabla_tramos):,} tramos) "
          f"· segundos {registro['segundos']}")


if __name__ == "__main__":
    main()
