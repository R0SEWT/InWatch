"""Red vial como unidad: ``tramo`` e ``interseccion``, con cruces por longitud.

Las unidades del repo eran todas de área (hexágono, manzana, tesela), pero el flujo
potencial de una ciudad vive sobre calles. Forzarlo sobre un polígono promedia una
avenida con la cuadra de al lado. Este módulo define las dos unidades de red y la
tabla que las lleva a cualquier unidad de área sin perder ni inventar longitud.

Tres decisiones, cada una por un fallo que se evita:

- **El tramo es no dirigido.** En el grafo dirigido, una calle de doble sentido son dos
  aristas: sumar longitudes ahí duplica la red vial.
- **Solo EPSG:32718.** Una distancia en grados no es una distancia; se exige el grafo
  proyectado en vez de convertir en silencio.
- **``frac_tramo`` no se normaliza.** Si un tramo sale de la cobertura, la parte que
  falta es calle sin celda que la reciba, no un error de redondeo.

La descarga (``descargar``) es I/O contra Overpass y no se prueba; todo lo demás opera
sobre grafos ya en memoria.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pandas as pd
from pyproj import CRS

CRS_METRICO = "EPSG:32718"
ATRIBUTOS_FALTANTES = ("maxspeed", "lanes", "name")
COLUMNAS_TRAMO = ("tramo_id", "u", "v", "largo_m", "highway", "oneway", *ATRIBUTOS_FALTANTES)
TOLERANCIA_COMPLETO = 1e-6


def _exigir_metrico(crs) -> None:
    if crs is None or CRS.from_user_input(crs).to_epsg() != 32718:
        raise ValueError(f"se exige EPSG:32718 (proyectado en metros); llegó {crs!r}")


def _primero(valor):
    """osmnx deja listas cuando fusiona segmentos con atributos distintos."""
    if isinstance(valor, list):
        return valor[0] if valor else None
    return valor


def _a_bool(valor) -> bool:
    if isinstance(valor, str):
        return valor.strip().lower() in {"true", "yes", "1", "-1"}
    return bool(_primero(valor))


# ─── unidades ─────────────────────────────────────────────────────────────────
def tramos(G: nx.MultiDiGraph) -> gpd.GeoDataFrame:
    """Una fila por tramo del grafo no dirigido, con clave ``"<u>-<v>-<key>"`` y ``u < v``."""
    _exigir_metrico(G.graph.get("crs"))
    U = ox.convert.to_undirected(G)
    aristas = ox.convert.graph_to_gdfs(U, nodes=False, edges=True).reset_index()

    extremos = [sorted((a, b), key=str) for a, b in zip(aristas["u"], aristas["v"], strict=True)]
    aristas["u"] = [e[0] for e in extremos]
    aristas["v"] = [e[1] for e in extremos]
    aristas["tramo_id"] = [
        f"{u}-{v}-{k}" for u, v, k in zip(aristas["u"], aristas["v"], aristas["key"], strict=True)
    ]
    if aristas["tramo_id"].duplicated().any():
        raise ValueError("tramo_id duplicado: el grafo no dirigido tiene aristas repetidas")

    aristas["largo_m"] = aristas["length"].astype("float32")
    aristas["oneway"] = aristas["oneway"].map(_a_bool) if "oneway" in aristas else False
    for campo in ("highway", *ATRIBUTOS_FALTANTES):
        if campo not in aristas:
            aristas[campo] = None
        aristas[campo] = aristas[campo].map(_primero)
    return gpd.GeoDataFrame(
        aristas[[*COLUMNAS_TRAMO]], geometry=aristas.geometry.values, crs=aristas.crs
    )


def intersecciones(G: nx.MultiDiGraph) -> gpd.GeoDataFrame:
    """Una fila por nodo, con ``node_id`` como string del ``osmid``."""
    _exigir_metrico(G.graph.get("crs"))
    nodos = ox.convert.graph_to_gdfs(G, nodes=True, edges=False).reset_index()
    nodos["node_id"] = nodos["osmid"].astype(str)
    columnas = ["node_id", "x", "y"] + (["street_count"] if "street_count" in nodos else [])
    return gpd.GeoDataFrame(nodos[columnas], geometry=nodos.geometry.values, crs=nodos.crs)


def faltantes(t: pd.DataFrame, campos: Iterable[str] = ATRIBUTOS_FALTANTES) -> dict[str, float]:
    """Porcentaje de tramos sin cada atributo. Lo exige el enunciado del TP."""
    return {c: float(100 * t[c].isna().mean()) if c in t else 100.0 for c in campos}


# ─── correspondencia ──────────────────────────────────────────────────────────
def correspondencia(
    t: gpd.GeoDataFrame,
    poligonos: gpd.GeoDataFrame,
    *,
    clave: str,
    longitud_minima_m: float = 1.0,
) -> pd.DataFrame:
    """``tramo_id`` × ``clave`` con ``largo_m`` y ``frac_tramo``.

    ``frac_tramo`` se mide contra la longitud geométrica del tramo, no contra el
    atributo ``length`` de OSM: así el reparto es coherente con los pedazos que se miden.
    """
    _exigir_metrico(t.crs)
    if poligonos.crs != t.crs:
        poligonos = poligonos.to_crs(t.crs)

    base = t[["tramo_id", "geometry"]].copy()
    base["_largo_total"] = base.geometry.length
    piezas = gpd.overlay(base, poligonos[[clave, "geometry"]], how="intersection",
                         keep_geom_type=True)
    if piezas.empty:
        return pd.DataFrame(columns=["tramo_id", clave, "largo_m", "frac_tramo"])

    piezas["largo_m"] = piezas.geometry.length
    salida = piezas.groupby(["tramo_id", clave], as_index=False).agg(
        largo_m=("largo_m", "sum"), _largo_total=("_largo_total", "first")
    )
    salida = salida[salida["largo_m"] >= longitud_minima_m].copy()
    salida["frac_tramo"] = salida["largo_m"] / salida["_largo_total"]
    return salida[["tramo_id", clave, "largo_m", "frac_tramo"]].reset_index(drop=True)


def desvio_de_longitud(corr: pd.DataFrame) -> float:
    """Máximo |Σ frac_tramo − 1| entre los tramos completos, y todo exceso sobre 1.

    Un exceso significa longitud inventada (por ejemplo, polígonos que se solapan).
    Sin un solo tramo completo no hay nada contra qué verificar: falla en vez de
    devolver un 0 que no comprobó nada.
    """
    suma = corr.groupby("tramo_id")["frac_tramo"].sum()
    completos = suma[suma >= 1 - TOLERANCIA_COMPLETO]
    if completos.empty:
        raise ValueError("ningún tramo queda completo en la cobertura: nada que verificar")
    exceso = (suma - 1).clip(lower=0).max()
    return float(max((completos - 1).abs().max(), exceso))


def asignar_intersecciones(
    inter: gpd.GeoDataFrame, poligonos: gpd.GeoDataFrame, *, clave: str
) -> pd.DataFrame:
    """Cada intersección a una celda. En un borde compartido gana la clave menor."""
    if poligonos.crs != inter.crs:
        poligonos = poligonos.to_crs(inter.crs)
    unidas = gpd.sjoin(inter[["node_id", "geometry"]], poligonos[[clave, "geometry"]],
                       how="left", predicate="intersects")
    unidas = unidas.sort_values(["node_id", clave]).drop_duplicates("node_id", keep="first")
    orden = {n: i for i, n in enumerate(inter["node_id"])}
    unidas = unidas.sort_values("node_id", key=lambda s: s.map(orden))
    return unidas[["node_id", clave]].reset_index(drop=True)


# ─── descarga, metadatos y persistencia ───────────────────────────────────────
def metadatos(G: nx.MultiDiGraph, *, modo: str, consulta: str) -> dict:
    return {
        "consulta": consulta,
        "modo": modo,
        "crs": CRS.from_user_input(G.graph["crs"]).to_string(),
        "n_nodos": G.number_of_nodes(),
        "n_aristas": G.number_of_edges(),
        "versiones": {p: version(p) for p in ("osmnx", "networkx", "geopandas", "shapely")},
        "descargado_en": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
    }


def descargar(poligono_4326, *, modo: str, consulta: str, cache: Path | None = None):
    """Descarga con osmnx, simplifica y proyecta a EPSG:32718. Devuelve ``(G, metadatos)``."""
    if cache is not None:
        ox.settings.use_cache = True
        ox.settings.cache_folder = str(cache)
    G = ox.graph_from_polygon(poligono_4326, network_type=modo, simplify=True, retain_all=False)
    G = ox.project_graph(G, to_crs=CRS_METRICO)
    return G, metadatos(G, modo=modo, consulta=consulta)


def _ruta_meta(ruta: Path) -> Path:
    return ruta.with_suffix(".meta.json")


def guardar(G: nx.MultiDiGraph, ruta: Path, meta: dict) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ox.io.save_graphml(G, ruta)
    meta = {**meta, "sha256": hashlib.sha256(ruta.read_bytes()).hexdigest()}
    _ruta_meta(ruta).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return ruta


def cargar(ruta: Path) -> tuple[nx.MultiDiGraph, dict]:
    return ox.io.load_graphml(ruta), json.loads(_ruta_meta(ruta).read_text(encoding="utf-8"))


def poligono_distritos(zip_distritos: Path, ubigeos: Iterable[str]):
    """Unión de los distritos pedidos, en EPSG:4326, desde el shapefile INEI zipeado."""
    pedidos = {str(u) for u in ubigeos}
    capa = gpd.read_file(f"/vsizip/{zip_distritos}/DISTRITOS.shp", engine="pyogrio")
    elegidos = capa[capa["UBIGEO"].astype(str).isin(pedidos)]
    faltan = pedidos - set(elegidos["UBIGEO"].astype(str))
    if faltan:
        raise ValueError(f"UBIGEO sin polígono en {zip_distritos.name}: {sorted(faltan)}")
    return elegidos.to_crs("EPSG:4326").union_all()
