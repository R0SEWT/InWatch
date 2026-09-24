"""Geometría y cartografía de la pieza: estadios, anillos y capas del basemap.

Es el subconjunto de acceso a datos de lo que era un módulo suelto fuera del repo, donde
convivía con el estilo matplotlib de las figuras impresas. Acá solo vive la geometría:
la pieza dibuja con deck.gl, no con matplotlib, así que arrastrar los rcParams de
Frontiers no servía de nada.

Las rutas salen del **catálogo de fuentes**, no de constantes. La versión de fuera tenía
``OSM = Path("/home/<usuario>/Code/tesis/infelix/…")`` escrito a mano: eso ataba la pieza
a una laptop y al árbol de otro repo. Con el catálogo se pide el nombre y él decide de
dónde sale (inwatch-iv1.2, inwatch-8sm).
"""

from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Point, box

from inwatch import fuentes

# Centroides de los tres estadios, en lat/lon. Son puntos públicos y estables; la
# procedencia del CONTEO de días de partido, que es lo portante, vive en el registro
# canónico bajo `pulso.dias_tratados`, no acá.
ESTADIOS = {
    "Estadio Nacional": (-12.06707, -77.03386),
    "Estadio Monumental": (-12.05565, -76.93533),
    "Matute": (-12.06850, -77.02293),
}
# Claves cortas: las que usan el guion, la escena y el parquet del perfil.
CLAVES = {"Matute": "matute", "Estadio Nacional": "nacional",
          "Estadio Monumental": "monumental"}

BORDES = [0.0, 500.0, 1000.0, 2000.0, 4000.0]
ANILLOS = ["r0_500", "r500_1000", "r1000_2000", "r2000_4000"]

# Ventana de carga: cubre los tres estadios separados unos 10 km más sus anillos de 4 km
# a cada lado, con margen para el zoom más abierto del recorrido.
ANCHO_M, ALTO_M = 27_000.0, 16_500.0

PRINCIPALES = {"motorway", "trunk", "primary", "secondary",
               "motorway_link", "trunk_link", "primary_link", "secondary_link"}
PARQUES = {"park", "forest", "grass", "recreation_ground", "nature_reserve",
           "cemetery", "meadow", "scrub", "orchard", "village_green"}

CRS_METRICO = 32718          # UTM 18S: los anillos se miden en metros, no en grados


def estadios() -> gpd.GeoDataFrame:
    """Los tres estadios, proyectados a métrico."""
    return gpd.GeoDataFrame(
        {"nombre": list(ESTADIOS), "clave": [CLAVES[n] for n in ESTADIOS]},
        geometry=[Point(lon, lat) for lat, lon in ESTADIOS.values()],
        crs=4326,
    ).to_crs(CRS_METRICO)


def ventana() -> tuple[gpd.GeoDataFrame, tuple[float, float, float, float],
                       tuple[float, float, float, float]]:
    """Estadios, límites en métrico y la misma caja en lon/lat para el `bbox` de lectura."""
    est = estadios()
    cx, cy = float(est.geometry.x.mean()), float(est.geometry.y.mean())
    lim = (cx - ANCHO_M / 2, cx + ANCHO_M / 2, cy - ALTO_M / 2, cy + ALTO_M / 2)
    caja = gpd.GeoSeries([Point(lim[0], lim[2]), Point(lim[1], lim[3])],
                         crs=CRS_METRICO).to_crs(4326).total_bounds
    return est, lim, tuple(caja)


def cartografia(caja, lim) -> dict[str, gpd.GeoDataFrame]:
    """Capas del basemap, recortadas a la ventana. Todas del extracto de OSM del catálogo."""
    osm = fuentes.ruta("osm_peru_gpkg")
    distritos = fuentes.ruta("distritos_limites")
    recorte = box(lim[0], lim[2], lim[1], lim[3])

    def leer(capa):
        g = gpd.read_file(osm, layer=capa, bbox=caja,
                          engine="pyogrio").to_crs(CRS_METRICO)
        return gpd.clip(g, recorte)

    agua = leer("gis_osm_water_a_free")
    uso = leer("gis_osm_landuse_a_free")
    vias = leer("gis_osm_roads_free")
    rieles = leer("gis_osm_railways_free")
    # El recorte va sobre la LÍNEA, no sobre el polígono: recortar el polígono mete los
    # bordes de la ventana en su contorno y el mapa termina con un marco punteado que
    # nadie dibujó.
    dist = gpd.read_file(f"zip://{distritos}", bbox=caja,
                         engine="pyogrio").to_crs(CRS_METRICO)
    dist = gpd.GeoDataFrame(geometry=gpd.clip(dist.boundary, recorte), crs=CRS_METRICO)
    return {
        "agua": agua,
        "verdes": uso[uso["fclass"].isin(PARQUES)],
        "vias_menores": vias[~vias["fclass"].isin(PRINCIPALES)],
        "vias_mayores": vias[vias["fclass"].isin(PRINCIPALES)],
        "rieles": rieles,
        "distritos": dist,
    }


def anillos_vectoriales(est, lim) -> gpd.GeoDataFrame:
    """Los cuatro anillos de cada estadio, COMPLETOS y por lo tanto solapados.

    El solape es lo fiel al estimador: cada estadio mide sus anillos por su propia
    distancia, sin mirar al vecino, así que un punto entre Matute y el Nacional pertenece
    a un anillo de cada uno **a la vez**. No se resuelve en la geometría sino en el
    diseño: los días en que el vecino también tiene partido se excluyen de tratamiento y
    de control. La pieza además dibuja un solo estadio por parada, así que el solape
    nunca llega a la pantalla.
    """
    envolvente = box(lim[0], lim[2], lim[1], lim[3])
    filas = []
    for nombre, pt in zip(est["nombre"], est.geometry, strict=True):
        for k, anillo in enumerate(ANILLOS):
            corona = pt.buffer(BORDES[k + 1], quad_segs=96)
            if BORDES[k] > 0:
                corona = corona.difference(pt.buffer(BORDES[k], quad_segs=96))
            filas.append({"estadio": nombre, "anillo": anillo,
                          "geometry": corona.intersection(envolvente)})
    return gpd.GeoDataFrame(filas, crs=CRS_METRICO)
