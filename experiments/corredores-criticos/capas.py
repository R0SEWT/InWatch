"""Capas complementarias del TP: estaciones, estadios y ranking de lo crítico (92d.4).

El enunciado exige integrar al menos una capa de puntos al grafo. Acá entran las
estaciones del Metropolitano y de la Línea 1 (fuente ``transit_stations``) y los dos
estadios que caen en el área A, y se cruzan con la betweenness que dejó ``centralidad.py``.

Dos cuidados que el código hace explícitos:

- **Un punto lejano no se cuelga de la intersección del borde en silencio.** Si la
  estación más cercana está a kilómetros, es que quedó fuera del área: se marca
  ``fuera_de_rango`` en vez de fabricar una asociación.
- **El ranking desempata por clave.** Con betweenness iguales, ordenar por valor solo
  deja el resultado a merced del orden de las filas, y el top cambiaría entre corridas.

Las coordenadas de los estadios son las mismas que usa ``pulso-estadios`` para que los
dos experimentos hablen del mismo punto.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import geopandas as gpd
import pandas as pd

# Copiadas de experiments/pulso-estadios/loader.py, que a su vez las trajo de infelix.
# Monumental queda en Ate, fuera del área A.
ESTADIOS = {
    "Nacional": (-12.06707, -77.03386),
    "Matute": (-12.06850, -77.02293),
}
CRS_METRICO = "EPSG:32718"
RADIO_M = 300.0  # mismo buffer que usó infelix para los corredores de transporte
DIST_MAXIMA_M = 500.0


def cargar_estaciones(ruta, poligono=None) -> gpd.GeoDataFrame:
    """Estaciones del gazetteer, en métrico y recortadas al polígono si se da uno."""
    df = pd.read_csv(ruta, comment="#")
    g = gpd.GeoDataFrame(
        df.assign(capa="estacion"),
        geometry=gpd.points_from_xy(df["lng"], df["lat"]),
        crs="EPSG:4326",
    ).to_crs(CRS_METRICO)
    if poligono is not None:
        g = g[g.within(poligono)].reset_index(drop=True)
    return g


def cargar_estadios(poligono=None) -> gpd.GeoDataFrame:
    g = gpd.GeoDataFrame(
        {"nombre": list(ESTADIOS), "sistema": "estadio", "capa": "estadio"},
        geometry=gpd.points_from_xy([c[1] for c in ESTADIOS.values()],
                                    [c[0] for c in ESTADIOS.values()]),
        crs="EPSG:4326",
    ).to_crs(CRS_METRICO)
    if poligono is not None:
        g = g[g.within(poligono)].reset_index(drop=True)
    return g


def asignar_mas_cercana(
    puntos: gpd.GeoDataFrame,
    intersecciones: gpd.GeoDataFrame,
    *,
    dist_maxima_m: float = DIST_MAXIMA_M,
) -> pd.DataFrame:
    """Cada punto a su intersección más cercana, con la distancia y una marca de rango."""
    unidas = gpd.sjoin_nearest(
        puntos, intersecciones[["node_id", "geometry"]], how="left", distance_col="dist_m"
    )
    # sjoin_nearest devuelve una fila por empate; gana el node_id menor para que el
    # resultado no dependa del orden de las filas.
    unidas = unidas.sort_values(["dist_m", "node_id"])
    unidas = unidas[~unidas.index.duplicated(keep="first")].sort_index()
    unidas["fuera_de_rango"] = unidas["dist_m"] > dist_maxima_m
    columnas = [c for c in puntos.columns if c != "geometry"] + [
        "node_id", "dist_m", "fuera_de_rango"
    ]
    return unidas[columnas].reset_index(drop=True)


def tramos_cercanos(
    puntos: gpd.GeoDataFrame, tramos: gpd.GeoDataFrame, *, radio_m: float = RADIO_M
) -> pd.DataFrame:
    """Pares punto × tramo dentro del radio, con su distancia."""
    zonas = puntos.copy()
    zonas["geometry"] = zonas.geometry.buffer(radio_m)
    pares = gpd.sjoin(tramos[["tramo_id", "geometry"]], zonas, how="inner", predicate="intersects")
    if pares.empty:
        columnas = ["tramo_id", *(c for c in puntos.columns if c != "geometry"), "dist_m"]
        return pd.DataFrame(columns=columnas)
    geom_punto = puntos.geometry.to_numpy()[pares["index_right"].to_numpy()]
    pares["dist_m"] = pares.geometry.distance(gpd.GeoSeries(geom_punto, crs=tramos.crs),
                                              align=False)
    columnas = ["tramo_id", *(c for c in puntos.columns if c != "geometry"), "dist_m"]
    return pares[columnas].sort_values(["tramo_id", "dist_m"]).reset_index(drop=True)


def ranking(tabla: pd.DataFrame, columna: str, *, clave: str, top: int) -> pd.DataFrame:
    """Las `top` filas de mayor `columna`, numeradas desde 1 y con desempate por clave."""
    if top > len(tabla):
        raise ValueError(f"top={top} es mayor que las {len(tabla)} filas de la tabla")
    orden = tabla.sort_values([columna, clave], ascending=[False, True]).head(top).copy()
    orden["rango"] = range(1, top + 1)
    return orden.reset_index(drop=True)


def cobertura(top: Iterable[str], cercanos: set[str]) -> float:
    """Fracción del top que está en `cercanos`. Falla con un top vacío."""
    top = list(top)
    if not top:
        raise ValueError("el top está vacío: no hay nada de lo que medir cobertura")
    return sum(1 for x in top if x in cercanos) / len(top)


def tramos_entre_top(
    top_tramos: Iterable[str], top_nodos: set[str], tramos: pd.DataFrame
) -> float:
    """Fracción de los tramos del top cuyos DOS extremos son intersecciones del top.

    Es el contraste nodo-arista: un corredor puede unir hubs o puentear entre zonas sin
    que sus extremos destaquen por sí mismos.
    """
    top_tramos = list(top_tramos)
    if not top_tramos:
        raise ValueError("el top de tramos está vacío")
    # `red_vial.tramos` deja los extremos como el osmid entero y `node_id` es str.
    # Comparar sin normalizar da un conjunto vacío y devuelve 0,0 % sin avisar.
    extremos = tramos.set_index("tramo_id")[["u", "v"]].astype(str)
    faltan = set(top_tramos) - set(extremos.index)
    if faltan:
        raise ValueError(f"el tramo no existe en la tabla: {sorted(faltan)[:3]}")
    top_nodos = {str(n) for n in top_nodos}
    filas = extremos.loc[top_tramos]
    ambos = [(u in top_nodos and v in top_nodos) for u, v in zip(filas["u"], filas["v"],
                                                                 strict=True)]
    return sum(ambos) / len(top_tramos)


# ─── ejecución ────────────────────────────────────────────────────────────────
SLUG = "corredores-criticos"
VARIANTE = "area_a_drive"
TOP = 100
OUT = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG


def main() -> None:
    import importlib.util

    from inwatch import canon, fuentes
    from inwatch.unidades import red_vial

    # El loader es un script hermano, no un módulo instalado: se carga por ruta para no
    # depender del cwd ni de que el directorio del experimento esté en sys.path.
    spec = importlib.util.spec_from_file_location("loader", Path(__file__).with_name("loader.py"))
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)

    grafo = OUT / "area_a_drive.graphml"
    bc_nodos = pd.read_parquet(OUT / "betweenness_intersecciones.parquet")
    bc_tramos = pd.read_parquet(OUT / "betweenness_tramos.parquet")
    G, _ = red_vial.cargar(grafo)
    inter = red_vial.intersecciones(G)
    tramos = red_vial.tramos(G)
    poligono = red_vial.poligono_distritos(fuentes.ruta(loader.FUENTE_POLIGONO), loader.UBIGEOS)
    poligono_m = gpd.GeoSeries([poligono], crs="EPSG:4326").to_crs(CRS_METRICO).iloc[0]

    estaciones_ruta = fuentes.resolver("transit_stations")
    puntos = pd.concat(
        [cargar_estaciones(estaciones_ruta.ruta, poligono_m), cargar_estadios(poligono_m)],
        ignore_index=True,
    )
    puntos = gpd.GeoDataFrame(puntos, geometry="geometry", crs=CRS_METRICO)

    asignadas = asignar_mas_cercana(puntos, inter)
    cerca = tramos_cercanos(puntos, tramos)
    nodos_con_capa = set(asignadas.loc[~asignadas["fuera_de_rango"], "node_id"])
    tramos_con_capa = set(cerca["tramo_id"])

    def emitir(clave: str, valor: float, unidad: str, estimador: str) -> None:
        canon.emit(clave, float(valor), variant=VARIANTE, unit=unidad, estimator=estimador,
                   inputs=[grafo, estaciones_ruta.ruta], script=__file__)

    emitir("corredores.conteo.estaciones_area_a", int((puntos["capa"] == "estacion").sum()),
           "estaciones", "Metropolitano y Línea 1 dentro del área A")
    emitir("corredores.conteo.estadios_area_a", int((puntos["capa"] == "estadio").sum()),
           "estadios", "Nacional y Matute, mismos puntos que pulso-estadios")

    rankings = {}
    for peso in ("length", "travel_time"):
        col = f"bc_{peso}"
        r_nodos = ranking(bc_nodos, col, clave="node_id", top=TOP)
        r_tramos = ranking(bc_tramos, col, clave="tramo_id", top=TOP)
        rankings[peso] = (r_nodos, r_tramos)
        emitir(f"corredores.pct.top_nodos_con_capa_{peso}",
               100 * cobertura(r_nodos["node_id"], nodos_con_capa), f"% del top-{TOP}",
               f"intersecciones del top a ≤{DIST_MAXIMA_M:.0f} m de una estación o estadio")
        emitir(f"corredores.pct.top_tramos_con_capa_{peso}",
               100 * cobertura(r_tramos["tramo_id"], tramos_con_capa), f"% del top-{TOP}",
               f"tramos del top dentro del buffer de {RADIO_M:.0f} m")
        emitir(f"corredores.pct.top_tramos_entre_hubs_{peso}",
               100 * tramos_entre_top(r_tramos["tramo_id"], set(r_nodos["node_id"]), tramos),
               f"% del top-{TOP}", "tramos del top con sus dos extremos en el top de nodos")

    OUT.mkdir(parents=True, exist_ok=True)
    asignadas.to_parquet(OUT / "capas_asignadas.parquet", index=False)
    cerca.to_parquet(OUT / "capas_tramos_cercanos.parquet", index=False)
    for peso, (r_nodos, r_tramos) in rankings.items():
        r_nodos.to_parquet(OUT / f"ranking_intersecciones_{peso}.parquet", index=False)
        r_tramos.to_parquet(OUT / f"ranking_tramos_{peso}.parquet", index=False)
    print(f"  → {OUT}  ({len(puntos)} puntos · {len(cerca):,} pares punto×tramo)")


if __name__ == "__main__":
    main()
