"""Precómputo de corredores-criticos: la red ``drive`` del área A, lista para centralidades.

TP de Complex Networks, tema 2 (bead ``inwatch-92d``). Esta etapa (``inwatch-92d.2``)
deja el grafo dirigido del eje Metropolitano centro-sur con velocidad y tiempo de viaje
en cada arista, y emite las cifras que el enunciado exige declarar sobre el dato.

Por qué la marca ``maxspeed_observado`` va ANTES de imputar: ``add_edge_speeds`` de
osmnx completa el ``maxspeed`` faltante con la media del tipo de vía y sobrescribe todas
las aristas con ``speed_kph``. Después de eso ya no se distingue qué velocidad salió de
OSM y cuál es un supuesto, y la betweenness por tiempo de viaje heredaría ese supuesto sin
declararlo.

Por qué ``drive``: el tema es de tránsito vehicular; el enunciado exige justificar el
``network_type`` y reserva ``walk`` para accesibilidad peatonal.

    uv run python experiments/corredores-criticos/loader.py
"""

from __future__ import annotations

import math
from pathlib import Path

import networkx as nx
import osmnx as ox
from pyproj import CRS

from inwatch import canon, fuentes
from inwatch.unidades import red_vial

SLUG = "corredores-criticos"
MODO = "drive"
VARIANTE = "area_a_drive"
# Área A: Cercado de Lima, La Victoria, San Isidro, Miraflores, Surquillo.
UBIGEOS = ("150101", "150115", "150131", "150122", "150141")
# El recorte versionado, no el shapefile nacional de infelix: así un clon del repo
# reproduce el grafo exacto sin bocho ni infelix. El polígono es el mismo (54,2 km²).
FUENTE_POLIGONO = "distritos_limites_area_a"
CONSULTA = (
    f"ox.graph_from_polygon(unión de UBIGEO {', '.join(UBIGEOS)} de la fuente "
    f"{FUENTE_POLIGONO}, network_type='{MODO}', simplify=True, retain_all=False)"
)
OUT = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG
GRAPHML = f"area_a_{MODO}.graphml"


def _tiene_valor(valor) -> bool:
    if valor is None:
        return False
    if isinstance(valor, float) and math.isnan(valor):
        return False
    if isinstance(valor, str | list | tuple):
        return len(valor) > 0
    return True


def marcar_maxspeed(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Marca en cada arista si su ``maxspeed`` vino de OSM. Muta y devuelve ``G``."""
    for _, _, datos in G.edges(data=True):
        datos["maxspeed_observado"] = _tiene_valor(datos.get("maxspeed"))
    return G


def preparar(G: nx.MultiDiGraph) -> nx.MultiDiGraph:
    """Marca lo observado, imputa velocidades por tipo de vía y calcula ``travel_time``."""
    crs = G.graph.get("crs")
    if crs is None or CRS.from_user_input(crs).to_epsg() != 32718:
        raise ValueError(f"se exige EPSG:32718 (proyectado en metros); llegó {crs!r}")
    marcar_maxspeed(G)
    ox.routing.add_edge_speeds(G)
    ox.routing.add_edge_travel_times(G)
    return G


def resumen(G: nx.MultiDiGraph) -> dict[str, float]:
    """Cifras sobre el dato que el enunciado pide declarar.

    La imputación se cuenta sobre aristas dirigidas —es lo que usa la betweenness— y
    también por longitud, porque una avenida imputada pesa más que un pasaje. Los
    faltantes de atributos se cuentan sobre tramos no dirigidos, que es la calle.
    """
    aristas = [(d["length"], bool(d["maxspeed_observado"])) for _, _, d in G.edges(data=True)]
    largo_total = sum(largo for largo, _ in aristas)
    imputadas = [largo for largo, observado in aristas if not observado]
    faltan = red_vial.faltantes(red_vial.tramos(G))
    return {
        "n_nodos": G.number_of_nodes(),
        "n_aristas": G.number_of_edges(),
        "pct_maxspeed_imputado_aristas": 100 * len(imputadas) / len(aristas),
        "pct_maxspeed_imputado_largo": 100 * sum(imputadas) / largo_total,
        "pct_sin_maxspeed": faltan["maxspeed"],
        "pct_sin_lanes": faltan["lanes"],
        "pct_sin_name": faltan["name"],
    }


def reduccion_por_simplificacion(*, n_sin: int, n_con: int) -> float:
    """Porcentaje de nodos que ``simplify=True`` elimina (nodos intermedios de geometría)."""
    if n_con > n_sin:
        raise ValueError(
            f"el grafo simplificado ({n_con}) no puede tener más nodos que el crudo ({n_sin})"
        )
    return 100 * (n_sin - n_con) / n_sin


# ─── ejecución ────────────────────────────────────────────────────────────────
EMISIONES = {
    # clave canon: (campo del resumen, unidad, estimador)
    "corredores.conteo.nodos": ("n_nodos", "intersecciones", "grafo drive simplificado"),
    "corredores.conteo.aristas": ("n_aristas", "aristas dirigidas", "grafo drive simplificado"),
    "corredores.conteo.nodos_sin_simplificar": (
        "n_nodos_sin_simplificar", "nodos", "mismo polígono con simplify=False"),
    "corredores.pct.reduccion_simplificacion": (
        "reduccion_simplificacion", "% de nodos", "(sin − con) / sin"),
    "corredores.pct.maxspeed_imputado_aristas": (
        "pct_maxspeed_imputado_aristas", "% de aristas dirigidas",
        "add_edge_speeds: media por highway, luego media global"),
    "corredores.pct.maxspeed_imputado_largo": (
        "pct_maxspeed_imputado_largo", "% de longitud", "ídem, ponderado por length"),
    "corredores.pct.sin_maxspeed": ("pct_sin_maxspeed", "% de tramos", "tramos no dirigidos"),
    "corredores.pct.sin_lanes": ("pct_sin_lanes", "% de tramos", "tramos no dirigidos"),
    "corredores.pct.sin_name": ("pct_sin_name", "% de tramos", "tramos no dirigidos"),
}


def main() -> None:
    cfg = fuentes.load_config()
    distritos = fuentes.resolver(FUENTE_POLIGONO)
    poligono = red_vial.poligono_distritos(distritos.ruta, UBIGEOS)
    cache = cfg.datos / ".cache" / "osmnx"

    G, meta = red_vial.descargar(poligono, modo=MODO, consulta=CONSULTA, cache=cache)
    crudo = ox.graph_from_polygon(poligono, network_type=MODO, simplify=False, retain_all=False)
    preparar(G)

    r = resumen(G)
    r["n_nodos_sin_simplificar"] = crudo.number_of_nodes()
    r["reduccion_simplificacion"] = reduccion_por_simplificacion(
        n_sin=crudo.number_of_nodes(), n_con=G.number_of_nodes()
    )
    meta = {
        **meta,
        "n_nodos_sin_simplificar": crudo.number_of_nodes(),
        "velocidades": "ox.routing.add_edge_speeds (media por highway; si no hay, media global)",
        "fuente_poligono": {FUENTE_POLIGONO: distritos.sha256, "ubigeos": list(UBIGEOS)},
    }
    ruta = red_vial.guardar(G, OUT / GRAPHML, meta)

    for clave, (campo, unidad, estimador) in EMISIONES.items():
        canon.emit(clave, float(r[campo]), variant=VARIANTE, unit=unidad, estimator=estimador,
                   inputs=[distritos.ruta, ruta], script=__file__)
    print(f"  → {ruta}  ({r['n_nodos']:,} nodos · {r['n_aristas']:,} aristas)")


if __name__ == "__main__":
    main()
