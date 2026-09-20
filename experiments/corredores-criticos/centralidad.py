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


COLUMNA_DE_PESO = {"length": "largo_m", "travel_time": "travel_time"}


def a_tramos(arcos: pd.Series, tramos: pd.DataFrame, *, peso: str) -> pd.DataFrame:
    """Lleva la betweenness de arcos dirigidos a tramos no dirigidos.

    Los dos sentidos de una calle se **suman**, y es lo correcto: un camino mínimo es
    simple, así que nunca recorre la misma calle en los dos sentidos y los conjuntos de
    pares de cada arco son disjuntos. La suma responde "qué fracción de los pares pasa
    por esta calle en cualquier sentido", que es lo que se quiere para "qué se rompe si
    la cierras". Promediar castigaría a las de doble sentido justo por llevar más flujo.

    Entre tramos paralelos la cifra se adjudica al que el ruteo usó, **y eso depende del
    peso**: la paralela más corta puede no ser la más rápida. Adjudicar siempre a la más
    corta ponía toda la betweenness por tiempo en un tramo por el que los caminos mínimos
    por tiempo no pasan. Con empate exacto gana el `tramo_id` menor, para que el resultado
    no dependa del orden de las filas; el empate significa que el ruteo es indiferente.
    """
    columna = COLUMNA_DE_PESO.get(peso)
    if columna is None:
        raise ValueError(f"peso desconocido '{peso}': se esperaba uno de {sorted(COLUMNA_DE_PESO)}")
    if columna not in tramos:
        raise ValueError(
            f"la tabla de tramos no trae '{columna}', que es el peso con el que se calculó "
            f"la betweenness por {peso}"
        )
    por_par: dict[tuple, float] = {}
    for (u, v), valor in arcos.items():
        clave = _par(u, v)
        por_par[clave] = por_par.get(clave, 0.0) + float(valor)

    t = tramos[["tramo_id", "u", "v", columna]].copy()
    t["_par"] = [_par(u, v) for u, v in zip(t["u"], t["v"], strict=True)]
    sin_tramo = set(por_par) - set(t["_par"])
    if sin_tramo:
        raise ValueError(f"{len(sin_tramo)} arcos no tienen tramo, p. ej. {sorted(sin_tramo)[:3]}")

    t["betweenness"] = 0.0
    # El desempate por `tramo_id` va en el orden, no en `idxmin`, que ante empate
    # devuelve la primera fila del DataFrame y deja el resultado a merced de su orden.
    orden = t.sort_values([columna, "tramo_id"])
    elegidos = orden.groupby("_par", sort=False).head(1)
    t.loc[elegidos.index, "betweenness"] = [por_par.get(p, 0.0) for p in elegidos["_par"]]
    return t[["tramo_id", "betweenness"]].reset_index(drop=True)


def resumen_busway(tramos: pd.DataFrame, bc: pd.DataFrame) -> dict:
    """Cuánto pesa el busway del Metropolitano en la red y en la betweenness.

    El grupo decidió MANTENERLO en el grafo y declararlo como limitación (bead
    ``inwatch-92d.8``). Declararlo en prosa no basta en este repo: la limitación se
    mide, se emite al registro y el README la cita por clave.

    Por qué es una limitación: OSM etiqueta esas vías ``access=no`` —84 de 86 en el
    área A—, así que están cerradas al tránsito general. El filtro ``drive`` de osmnx
    solo descarta ``access=private``, y por eso entran.
    """
    t = tramos[["tramo_id", "highway", "largo_m"]].merge(bc, on="tramo_id")
    es_bus = t["highway"] == "busway"
    salida: dict = {
        "pct_busway_tramos": 100 * float(es_bus.mean()),
        "pct_busway_largo": 100 * float(t.loc[es_bus, "largo_m"].sum() / t["largo_m"].sum()),
    }
    for peso in PESOS:
        col = f"bc_{peso}"
        salida[f"pct_busway_{col}"] = 100 * float(t.loc[es_bus, col].sum() / t[col].sum())
        primero = t.loc[t[col].idxmax(), "highway"]
        salida[f"busway_es_primero_{peso}"] = bool(primero == "busway")
    return salida


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
        por_tramo = a_tramos(arcos, tramos, peso=peso).rename(
            columns={"betweenness": f"bc_{peso}"}
        )
        tabla_tramos = tabla_tramos.merge(por_tramo, on="tramo_id", how="left")

        t0 = time.perf_counter()
        nodos_k, arcos_k = betweenness(D, peso=peso, k=K_APROX)
        registro["segundos"][f"aprox_{peso}"] = round(time.perf_counter() - t0, 1)
        # El error se mide también sobre TRAMOS, que es la unidad del contrato y la que
        # se dibuja. El de arcos no sirve de sustituto: `a_tramos` suma los dos sentidos
        # y deja las paralelas en cero, así que un ranking no se deriva del otro.
        tramos_exacta = a_tramos(arcos, tramos, peso=peso).set_index("tramo_id")["betweenness"]
        tramos_aprox = a_tramos(arcos_k, tramos, peso=peso).set_index("tramo_id")["betweenness"]
        for unidad, (aprox, exacta) in {"nodos": (nodos_k, nodos),
                                        "aristas": (arcos_k, arcos),
                                        "tramos": (tramos_aprox, tramos_exacta)}.items():
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

    # La limitación del busway, medida y anclada (inwatch-92d.8).
    bus = resumen_busway(tramos, tabla_tramos)
    registro["busway"] = bus
    for clave, unidad in (
        ("pct_busway_tramos", "% de tramos"),
        ("pct_busway_largo", "% de longitud"),
        ("pct_busway_bc_length", "% de la betweenness por longitud"),
        ("pct_busway_bc_travel_time", "% de la betweenness por tiempo"),
    ):
        emitir(f"corredores.pct.{clave.removeprefix('pct_')}", bus[clave], unidad,
               "highway=busway, que OSM marca access=no; se mantiene y se declara")
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
