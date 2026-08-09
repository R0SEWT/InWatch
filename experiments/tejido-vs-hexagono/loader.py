"""Precómputo de `tejido-vs-hexagono`: la tercera unidad espacial y su costo.

Este experimento existe para poder **dejar de creerle al hexágono**. La escalera de
atribución del trabajo de origen encontró un solo escalón significativo — la manzana
censal — y eso dice que la señal vive en la forma urbana a granularidad sub-distrital.
Un hexágono H3 res-8 mide ~530 m de arista y no respeta ni manzanas ni calles: promedia
sobre el borde entre un tejido y otro sin declarar que lo hace.

La tesselación morfológica (`city2graph.morphological_graph`, sobre momepy) construye
la unidad al revés: las calles son **barreras**, los edificios son semillas, y cada
celda es el espacio que le corresponde a un edificio dentro de su manzana cerrada. La
adyacencia resultante no es la del dibujante de la grilla, es la del peatón.

Dos consecuencias que este loader mide en vez de afirmar:

- **La adyacencia hexagonal no informa.** En una grilla H3 todo hexágono interior tiene
  exactamente seis vecinos por construcción. Un grafo sobre esa adyacencia no codifica
  estructura urbana: codifica la grilla. En el tejido, el grado varía con la forma real
  de la manzana, y dos celdas separadas por una avenida **no** son vecinas aunque se
  toquen en el mapa.
- **El hexágono parte el tejido.** La tabla de correspondencia mide con qué frecuencia
  una celda morfológica cae repartida entre dos o más hexágonos. Cada celda partida es
  una manzana cuyo valor el mapa hexagonal promedió con la de al lado.

Y una tercera, que es la regla dura número uno aplicada a la geometría: **el tejido no
cubre toda la grilla**. Donde no hay edificios OSM no hay tesselación, y esos hexágonos
salen en la tabla con cobertura areal cero — presentes y vacíos, nunca ausentes. Un
`inner join` los borraría y el mapa siguiente diría que ahí no pasa nada.

Esa tercera consecuencia **hay que construirla, no sale sola**, y descubrirlo costó una
corrida entera (``inwatch-72j``). ``morphological_graph(limit=)`` hace tesselación
*encerrada*: particiona **todo** el interior del límite, sin dejar huecos. Corriendo así,
los 4172 hexágonos salían con tejido, la celda del edificio más cercano se estiraba sobre
el desierto —415 celdas más grandes que un hexágono entero, la mayor de 136 km²— y
``hexagonos_sin_tejido`` era 0.0 % por construcción: una constante disfrazada de
medición. Peor que inútil, porque dibujaba la ausencia de dato como si fuera tejido.

Por eso la tesselación se **recorta a una máscara de área construida** antes de medir
nada. Fuera de esa máscara no hay unidad morfológica: hay hueco declarado. El radio que
define la máscara es un parámetro visible —``RADIO_CONSTRUIDO_M``, abajo, con su
justificación— y no una constante enterrada, porque es la perilla que decide qué cuenta
como ciudad.

Contrato de salida: unidad ``morfologica``, clave ``tess_id``; ver
``design/contrato-unidades.md``. La geometría va en un artefacto **aparte** porque, a
diferencia de H3, un polígono de tesselación no es reconstruible desde su clave — la
tabla de features sigue sin geometría, como manda el contrato.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import city2graph as c2g
import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Polygon
from shapely.ops import unary_union

from inwatch import canon

SLUG = "tejido-vs-hexagono"
# Read-only. El repo de origen nunca se modifica desde acá.
SOURCE = Path("/home/rosewt-dell/Code/tesis/infelix/data")
OUT = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG

ADMIN = SOURCE / "silver" / "h3_features" / "h3_admin.parquet"
H3_EDGES = SOURCE / "silver" / "h3_graph_edges.parquet"
OSM = SOURCE / "datasets" / "osm" / "peru.gpkg"

CAPA_EDIFICIOS = "gis_osm_buildings_a_free"
CAPA_VIAS = "gis_osm_roads_free"

# UTM 18S. La tesselación y todo factor de área se calculan en metros: hacerlo en
# grados mezclaría unidades que no son comparables entre latitudes.
CRS_METRICO = "EPSG:32718"

# Qué cuenta como barrera. `footway`, `steps`, `path` y `cycleway` atraviesan manzanas
# por dentro —un pasaje peatonal no separa dos tejidos— y usarlos como barrera
# fragmentaría la manzana en astillas sin significado morfológico. Se excluyen a
# propósito; la lista está acá arriba y no enterrada en un filtro para que la decisión
# sea revisable.
VIAS_BARRERA = frozenset(
    {
        "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
        "secondary", "secondary_link", "tertiary", "tertiary_link", "unclassified",
        "residential", "living_street", "service", "pedestrian", "busway",
    }
)

# Área mínima de intersección que cuenta en la tabla de correspondencia. Por debajo de
# 1 m² lo que hay es ruido de precisión geométrica en el borde compartido, no una celda
# realmente repartida entre dos hexágonos. Sin este piso, "celda partida" mediría el
# épsilon de la librería en vez de la ciudad.
AREA_MINIMA_M2 = 1.0

# Ventana de muestra para el notebook: los polígonos de toda Lima no caben en WASM.
# Se elige por área, no a mano, y el criterio queda en `ventana_muestra`.
VENTANA_HEXAGONOS = 12

# Radio del buffer que define «área construida». Es LA perilla de este loader: decide
# dónde termina la ciudad y empieza el hueco, así que vive acá arriba y no dentro de un
# filtro.
#
# 100 m no es arbitrario. Dos edificios separados por menos de 200 m quedan en la misma
# mancha —sus buffers se tocan—, que es el criterio clásico de aglomeración urbana usado
# para delinear área construida a partir de edificación. Con un radio mucho menor la
# trama densa de Lima se fragmenta en islas por cada avenida ancha; con uno mucho mayor
# la máscara vuelve a tragarse el desierto y reaparece el problema que esto arregla.
#
# Subirlo o bajarlo mueve `correspondencia.hexagonos_sin_tejido` y `area_partida`: es
# el experimento, no un detalle de implementación.
RADIO_CONSTRUIDO_M = 100.0


# ─── grilla canónica ──────────────────────────────────────────────────────────
def leer_grilla(admin: Path = ADMIN) -> gpd.GeoDataFrame:
    """Grilla canónica H3 res-8 de Lima + Callao, con geometría reconstruida.

    La geometría de un hexágono **sí** es reconstruible desde su clave, que es la razón
    por la que el contrato prohíbe guardarla. Acá se reconstruye para poder cruzarla
    contra el tejido, y se descarta al escribir.
    """
    adm = pd.read_parquet(admin, columns=["h3_index", "ubigeo", "distrito", "departamento"])
    # `cell_to_boundary` devuelve (lat, lng); shapely quiere (x, y) = (lng, lat).
    geom = [Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(c)]) for c in adm["h3_index"]]
    return gpd.GeoDataFrame(adm, geometry=geom, crs="EPSG:4326").to_crs(CRS_METRICO)


def leer_aristas_h3(edges: Path = H3_EDGES) -> pd.DataFrame:
    """Adyacencia hexagonal existente, normalizada a no dirigida.

    El artefacto de origen guarda cada vecindad dos veces (una por sentido). Compararlo
    contra el tejido sin normalizar duplicaría el grado del hexágono y regalaría el
    hallazgo: hay que medir las dos adyacencias en la misma convención o no se están
    midiendo.
    """
    e = pd.read_parquet(edges)
    par = pd.DataFrame(
        {
            "a": np.minimum(e["src_h3"], e["dst_h3"]),
            "b": np.maximum(e["src_h3"], e["dst_h3"]),
        }
    )
    return par[par["a"] != par["b"]].drop_duplicates(ignore_index=True)


# ─── tejido morfológico ───────────────────────────────────────────────────────
def leer_osm(limite, osm: Path = OSM) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Edificios y vías dentro del límite de la grilla canónica, en CRS métrico.

    Se lee por `bbox` en grados —lo único que el driver entiende— y se recorta contra
    el límite real después. Leer el gpkg entero de Perú para quedarse con Lima sería
    gastar un giga de memoria en geometría que se descarta.
    """
    limite_geo = gpd.GeoSeries([limite], crs=CRS_METRICO).to_crs("EPSG:4326")
    bbox = tuple(limite_geo.total_bounds)

    edificios = gpd.read_file(osm, layer=CAPA_EDIFICIOS, bbox=bbox, engine="pyogrio")
    vias = gpd.read_file(osm, layer=CAPA_VIAS, bbox=bbox, engine="pyogrio")

    edificios = edificios.to_crs(CRS_METRICO)
    vias = vias.to_crs(CRS_METRICO)

    edificios = edificios[edificios.intersects(limite)].reset_index(drop=True)
    vias = vias[vias["fclass"].isin(VIAS_BARRERA) & vias.intersects(limite)].reset_index(drop=True)
    if edificios.empty or vias.empty:
        raise ValueError(
            f"sin insumos morfológicos dentro del límite: {len(edificios):,} edificios, "
            f"{len(vias):,} vías barrera; no hay tejido que construir"
        )
    return edificios, vias


def construir_tejido(
    edificios: gpd.GeoDataFrame, vias: gpd.GeoDataFrame, limite
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """Tesselación morfológica y su adyacencia, vía ``city2graph.morphological_graph``.

    Devuelve `(celdas, aristas)`. Las aristas son ``touched_to``: contigüidad **dentro
    de la manzana cerrada**. Dos celdas a ambos lados de una avenida se tocan en el
    mapa y no son vecinas acá, y esa es exactamente la diferencia con el hexágono.
    """
    nodos, aristas = c2g.morphological_graph(
        edificios,
        vias,
        limit=limite,
        keep_buildings=False,
        keep_segments=False,
        tessellation_fallback=True,
    )
    celdas = nodos["place"]
    tocan = aristas[("place", "touched_to", "place")]

    # `place_id` es el índice; el contrato exige la clave como columna llamada tess_id.
    celdas = celdas.reset_index().rename(columns={"place_id": "tess_id"})
    celdas["tess_id"] = celdas["tess_id"].astype(str)

    # ⚠ La columna `geometry` activa de los nodos `place` es un **punto
    # representativo** —city2graph la usa para el grafo—, y el polígono de la celda vive
    # en `tessellation_geometry`. Usar la activa sin mirar da áreas de cero y una tabla
    # de correspondencia vacía, sin levantar ningún error: el `overlay` contra polígonos
    # simplemente no devuelve nada. Pasó, y por eso hay una comprobación abajo.
    celdas = celdas.set_geometry("tessellation_geometry").drop(columns=["geometry"])
    celdas = celdas.rename_geometry("geometry")

    if not (celdas.geometry.area > 0).any():
        raise ValueError(
            "la geometría de las celdas no tiene área: `morphological_graph` cambió qué "
            "columna lleva el polígono de la tesselación. Sin área no hay factor de área "
            "y la tabla de correspondencia sería un archivo vacío con forma de resultado"
        )

    # El índice de las aristas es un MultiIndex (from_place_id, to_place_id).
    par = pd.DataFrame(tocan.index.tolist(), columns=["src_tess", "dst_tess"]).astype(str)
    par = pd.DataFrame(
        {
            "src_tess": np.minimum(par["src_tess"], par["dst_tess"]),
            "dst_tess": np.maximum(par["src_tess"], par["dst_tess"]),
        }
    )
    par = par[par["src_tess"] != par["dst_tess"]].drop_duplicates(ignore_index=True)
    return celdas, par


# ─── caché de la tesselación ──────────────────────────────────────────────────
# `morphological_graph` es ~40 min de los ~45 que tarda el loader, y **no depende de
# `RADIO_CONSTRUIDO_M`**, que es justo el parámetro que este experimento existe para
# girar. Sin caché, barrer el radio cuesta 45 min por punto y deja de ser un parámetro
# para volverse una constante que nadie se anima a tocar.
#
# La clave no hashea el gpkg de 1,1 GB —hacerlo costaría más que el ahorro— sino todo lo
# que puede cambiar la tesselación: identidad del archivo OSM, cuántos insumos entraron,
# el límite y la lista de vías barrera. Ante la duda se borra `_cache_*` y se recomputa.
CACHE_CELDAS = OUT / "_cache_tejido_celdas.parquet"
CACHE_ARISTAS = OUT / "_cache_tejido_aristas.parquet"
CACHE_CLAVE = OUT / "_cache_tejido_clave.json"


def _clave_tejido(edificios: gpd.GeoDataFrame, vias: gpd.GeoDataFrame, limite) -> dict:
    st = OSM.stat()
    return {
        "osm_size": st.st_size,
        "osm_mtime_ns": st.st_mtime_ns,
        "n_edificios": int(len(edificios)),
        "n_vias": int(len(vias)),
        "area_limite_m2": round(float(limite.area), 3),
        "vias_barrera": sorted(VIAS_BARRERA),
        "crs": CRS_METRICO,
    }


def tejido_con_cache(
    edificios: gpd.GeoDataFrame, vias: gpd.GeoDataFrame, limite
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, bool]:
    """`construir_tejido`, pero sin recomputar lo que no cambió. Devuelve `(…, hubo_cache)`."""
    clave = _clave_tejido(edificios, vias, limite)
    if CACHE_CLAVE.exists() and json.loads(CACHE_CLAVE.read_text()) == clave:
        cel = pd.read_parquet(CACHE_CELDAS)
        celdas = gpd.GeoDataFrame(
            cel.drop(columns=["geometry_wkb"]),
            geometry=gpd.GeoSeries.from_wkb(cel["geometry_wkb"]),
            crs=CRS_METRICO,
        )
        return celdas, pd.read_parquet(CACHE_ARISTAS), True

    celdas, aristas = construir_tejido(edificios, vias, limite)
    CACHE_CELDAS.parent.mkdir(parents=True, exist_ok=True)
    guardar = pd.DataFrame({"tess_id": celdas["tess_id"], "geometry_wkb": celdas.geometry.to_wkb()})
    if "enclosure_index" in celdas.columns:
        guardar["enclosure_index"] = celdas["enclosure_index"].values
    guardar.to_parquet(CACHE_CELDAS, index=False)
    aristas.to_parquet(CACHE_ARISTAS, index=False)
    CACHE_CLAVE.write_text(json.dumps(clave, indent=2, sort_keys=True), encoding="utf-8")
    return celdas, aristas, False


# ─── el hueco: recortar el tejido a lo que de verdad está construido ──────────
def mascara_construida(
    edificios: gpd.GeoDataFrame, grilla: gpd.GeoDataFrame, radio: float = RADIO_CONSTRUIDO_M
) -> gpd.GeoDataFrame:
    """Dónde hay ciudad según OSM, **troceada por la grilla**. Una fila por pedazo.

    Fuera de esto no hay unidad morfológica que valga: es la pieza que convierte
    ``hexagonos_sin_tejido`` de constante estructural en medición.

    El troceado no es cosmético, es lo que hace que esto termine. Disuelta, la máscara de
    Lima es **una sola** geometría con cientos de miles de vértices, y recortar 245 000
    celdas contra ella deja inservible el índice espacial: cada celda se intersecaría
    contra toda la ciudad. Cortada por la grilla, cada pedazo tiene el bbox de un
    hexágono y el índice descarta de entrada todo lo que no toca. Misma geometría
    resultante, orden de magnitud distinto en tiempo — y el radio está para girarlo, así
    que la corrida tiene que ser repetible.
    """
    disuelta = edificios.geometry.buffer(radio).union_all()
    entera = gpd.GeoDataFrame(geometry=[disuelta], crs=edificios.crs)
    return gpd.overlay(entera, grilla[["geometry"]], how="intersection", keep_geom_type=True)


def recortar_a_construido(
    celdas: gpd.GeoDataFrame, mascara: gpd.GeoDataFrame
) -> tuple[gpd.GeoDataFrame, int]:
    """Recorta cada celda a la máscara. Devuelve `(celdas, cuántas desaparecieron)`.

    **Que desaparezcan celdas es el hallazgo, no un fallo**, y costó una corrida
    entenderlo. La tesselación encerrada no reparte solo el espacio *entre* edificios:
    también le da una celda a la manzana cerrada que no tiene ninguno. Esas celdas —las
    que se estiraban sobre el desierto, las que llegaban a 136 km²— no tienen un solo
    edificio a menos de ``RADIO_CONSTRUIDO_M``, así que la intersección con la máscara es
    vacía y salen de la tabla. Eso es exactamente el hueco que el experimento quiere
    dibujar deshilachado.

    Una celda **con** edificio nunca desaparece: contiene su semilla y la máscara contiene
    a todos los edificios.
    """
    columnas = [c for c in ("tess_id", "enclosure_index") if c in celdas.columns]
    trozos = gpd.overlay(
        celdas[[*columnas, "geometry"]], mascara, how="intersection", keep_geom_type=True
    )
    # `overlay` devuelve un trozo por pedazo de máscara; la celda es su unión.
    out = trozos.dissolve(by="tess_id", as_index=False, aggfunc="first")
    return out, len(celdas) - len(out)


def desolapar(celdas: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, float]:
    """Hace de las celdas una partición de verdad. Devuelve `(celdas, área_disputada)`.

    `morphological_graph` no siempre entrega celdas disjuntas: en esta corrida avisó de
    81 enclosures con celdas que se solapan o dejan huecos. Medido sobre el artefacto, el
    peor hexágono tenía un 5,5 % de área contada dos veces, y eso hace que
    ``Σ frac_h3`` supere 1 — imposible por definición, y una fuga de masa silenciosa para
    cualquier experimento que reparta cantidades con esta tabla.

    Regla de desempate: **gana el `tess_id` menor**. Es arbitraria y está declarada; lo
    que no puede ser arbitrario es que el área disputada se cuente dos veces. Se itera en
    orden ascendente restando lo que ya reclamaron las anteriores, así que el resultado no
    depende del orden de las filas.
    """
    # `predicate="intersects"` y no `"overlaps"`: en shapely, `overlaps` exige que
    # ninguna contenga a la otra, así que una celda **dentro** de otra no es «overlaps» y
    # se escapaba. Pasó: la primera versión dejó 7 hexágonos sobre 1, el peor con 1,0672
    # —unos 58 000 m² contados dos veces—, que es contención, no astillas de borde.
    # A cambio hay que descartar los pares que solo comparten borde, y eso se hace por
    # área de intersección: vectorizado en GEOS, no en un bucle de Python.
    pares = gpd.sjoin(
        celdas[["tess_id", "geometry"]],
        celdas[["tess_id", "geometry"]].rename(columns={"tess_id": "tess_id_otro"}),
        predicate="intersects",
        how="inner",
    )
    # cada par desordenado una sola vez; de paso se va el auto-emparejamiento
    pares = pares[pares["tess_id"] < pares["tess_id_otro"]]
    if not pares.empty:
        por_id = celdas.set_index("tess_id").geometry
        izq = por_id.loc[pares["tess_id"]].to_numpy()
        der = por_id.loc[pares["tess_id_otro"]].to_numpy()
        # Compartir borde es área cero. El piso descarta esas y el ruido de precisión,
        # y deja pasar cualquier solape que pueda mover la cobertura de un hexágono.
        pares = pares[shapely.area(shapely.intersection(izq, der)) > 1e-3]
    if pares.empty:
        return celdas, 0.0

    vecinos: dict[str, set[str]] = defaultdict(set)
    for a, b in zip(pares["tess_id"], pares["tess_id_otro"], strict=True):
        vecinos[a].add(b)
        vecinos[b].add(a)

    geom = dict(zip(celdas["tess_id"], celdas.geometry, strict=True))
    area_antes = sum(geom[t].area for t in vecinos)
    for tid in sorted(vecinos):
        previas = [geom[o] for o in vecinos[tid] if o < tid]
        if previas:
            geom[tid] = geom[tid].difference(unary_union(previas))
    disputada = area_antes - sum(geom[t].area for t in vecinos)

    out = celdas.copy()
    out["geometry"] = out["tess_id"].map(geom)
    out = out.set_geometry("geometry")
    # Una celda enteramente contenida en otra se queda sin nada al ceder lo disputado.
    # Deja de ser una unidad: sale de la tabla en vez de quedarse con área cero, que sería
    # una fila que existe y no significa nada.
    return out[~out.geometry.is_empty].reset_index(drop=True), float(disputada)


def tabla_celdas(celdas: gpd.GeoDataFrame, aristas: pd.DataFrame) -> pd.DataFrame:
    """Una fila por celda morfológica: área, grado y su enclosure. Sin geometría."""
    grado = (
        pd.concat([aristas["src_tess"], aristas["dst_tess"]])
        .value_counts()
        .rename("grado")
        .rename_axis("tess_id")
        .reset_index()
    )
    df = pd.DataFrame(
        {
            "tess_id": celdas["tess_id"],
            "area_m2": celdas.geometry.area.astype("float32"),
            # `Int32` nullable y no `int32`: una celda que cayó al fallback de huella
            # —su enclosure no se pudo teselar— no tiene enclosure, y eso es información.
            # Rellenarlo con un 0 la haría parecer miembro de la manzana número cero.
            "enclosure_index": celdas["enclosure_index"].astype("Int32"),
        }
    ).merge(grado, on="tess_id", how="left")
    # Grado 0 ES el dato: una celda aislada en su propia manzana. No es un faltante.
    df["grado"] = df["grado"].fillna(0).astype("int16")
    df["tess_id"] = df["tess_id"].astype("string")
    return df.sort_values("tess_id", ignore_index=True)


# ─── correspondencia entre unidades ───────────────────────────────────────────
def correspondencia(celdas: gpd.GeoDataFrame, grilla: gpd.GeoDataFrame) -> pd.DataFrame:
    """Tabla `tess_id` ↔ `h3_index` con factor de área en ambos sentidos.

    Es lo que ``design/contrato-unidades.md`` exige para cruzar unidades: un `merge`
    entre una capa H3 y una capa morfológica que "parece funcionar" está repartiendo
    masa sin declarar cómo. Acá se declara.

    - ``frac_tess`` — qué proporción de la celda morfológica cae en ese hexágono.
      Reparte una cantidad **de la celda** hacia H3.
    - ``frac_h3`` — qué proporción del hexágono ocupa esa celda. Reparte una cantidad
      **del hexágono** hacia el tejido. Sus sumas por hexágono **no llegan a 1** donde
      el tejido no cubre: ese déficit es cobertura faltante, no error de la tabla.
    """
    tess = celdas[["tess_id", "geometry"]].copy()
    tess["area_tess_m2"] = tess.geometry.area
    hexes = grilla[["h3_index", "geometry"]].copy()
    hexes["area_h3_m2"] = hexes.geometry.area

    inter = gpd.overlay(tess, hexes, how="intersection", keep_geom_type=True)
    inter["area_m2"] = inter.geometry.area
    inter = inter[inter["area_m2"] >= AREA_MINIMA_M2].reset_index(drop=True)

    out = pd.DataFrame(
        {
            "tess_id": inter["tess_id"].astype("string"),
            "h3_index": inter["h3_index"].astype("string"),
            "area_m2": inter["area_m2"].astype("float64"),
            "frac_tess": (inter["area_m2"] / inter["area_tess_m2"]).astype("float64"),
            "frac_h3": (inter["area_m2"] / inter["area_h3_m2"]).astype("float64"),
        }
    )
    return out.sort_values(["h3_index", "tess_id"], ignore_index=True)


def cobertura_por_hexagono(corr: pd.DataFrame, grilla: gpd.GeoDataFrame) -> pd.DataFrame:
    """Cuánto tejido real sostiene cada hexágono. **Una fila por hexágono de la grilla.**

    `left join` sobre la grilla entera y no `groupby` sobre la correspondencia: un
    hexágono sin ninguna celda morfológica tiene que existir en esta tabla con cero, no
    desaparecer de ella. Es la regla dura número uno en forma de esquema — filtrarlo acá
    haría imposible dibujarlo deshilachado después, y el mapa siguiente diría que ahí no
    hay nada que mirar cuando lo que no hay es dato.
    """
    agg = corr.groupby("h3_index", observed=True).agg(
        celdas_tejido=("tess_id", "nunique"),
        cobertura_areal=("frac_h3", "sum"),
    )
    # Σ frac_h3 > 1 significa que dos celdas reclaman el mismo suelo, y a partir de ahí
    # cualquier reparto con esta tabla inventa masa. `desolapar` lo previene; esto es el
    # cinturón, porque la tabla se escribe a disco y la sobrevive quien la lea después.
    peor = float(agg["cobertura_areal"].max())
    if peor > 1.0 + 1e-6:
        raise ValueError(
            f"{int((agg['cobertura_areal'] > 1.0 + 1e-6).sum())} hexágonos con cobertura "
            f"areal > 1 (peor: {peor:.4f}). Las celdas no son una partición: hay suelo "
            "contado dos veces y la tabla de correspondencia repartiría masa inexistente"
        )
    df = (
        grilla[["h3_index", "distrito", "departamento"]]
        .merge(agg, on="h3_index", how="left")
        .fillna({"celdas_tejido": 0, "cobertura_areal": 0.0})
    )
    df["tiene_tejido"] = df["celdas_tejido"] > 0
    return df.astype(
        {
            "h3_index": "string",
            "distrito": "string",
            "departamento": "string",
            "celdas_tejido": "int32",
            "cobertura_areal": "float32",
        }
    ).sort_values("h3_index", ignore_index=True)


def desvio_de_masa(corr: pd.DataFrame) -> float:
    """Peor desvío relativo al reconstruir el área de una celda desde la tabla.

    El test de "no pierde ni inventa masa" que pide el contrato, reducido a una cifra
    portante. Se mide sobre las celdas **completamente dentro** de la grilla: una celda
    que asoma por el borde pierde área legítimamente, y contarla como fuga convertiría
    el recorte en un falso positivo permanente.
    """
    suma = corr.groupby("tess_id", observed=True)["frac_tess"].sum()
    completas = suma[suma >= 1.0 - 1e-6]
    if completas.empty:
        raise ValueError(
            "ninguna celda del tejido queda completa dentro de la grilla; "
            "el recorte o el CRS están mal y la tabla de correspondencia no es fiable"
        )
    return float((completas - 1.0).abs().max())


# ─── ventana de muestra para la capa de presentación ──────────────────────────
def ventana_muestra(
    celdas: gpd.GeoDataFrame,
    grilla: gpd.GeoDataFrame,
    corr: pd.DataFrame,
    n: int = VENTANA_HEXAGONOS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Polígonos de una ventana pequeña, en WGS84 y **sin geometría shapely**.

    El notebook corre en Pyodide y ahí no hay geopandas: recibe listas de coordenadas y
    dibuja.

    La ventana se ancla en el hexágono con más celdas morfológicas dentro —el tejido más
    denso es donde el corte se ve— y se completa con sus vecinos **de la vecindad H3**,
    ordenados por densidad. El disco primero y la densidad después, y no al revés: si se
    eligieran los `n` hexágonos más densos de la ciudad la ventana saldría confeti
    repartido por Lima, y el mapa tendría que estar a zoom de ciudad, que es justo el
    zoom al que el corte de la manzana no se distingue.
    """
    densos = corr.groupby("h3_index", observed=True)["tess_id"].nunique()
    semilla = densos.idxmax()
    con_tejido = set(densos.index)
    disco = [c for c in h3.grid_disk(semilla, 2) if c in con_tejido]
    elegidos = sorted(disco, key=lambda c: -densos[c])[:n] or [semilla]

    hex_win = grilla[grilla["h3_index"].isin(elegidos)]
    tess_ids = set(corr.loc[corr["h3_index"].isin(elegidos), "tess_id"])
    tess_win = celdas[celdas["tess_id"].isin(tess_ids)]

    return _a_coordenadas(hex_win, "h3_index"), _a_coordenadas(tess_win, "tess_id")


def _a_coordenadas(gdf: gpd.GeoDataFrame, clave: str) -> pd.DataFrame:
    """GeoDataFrame → tabla plana de anillos exteriores en WGS84.

    Solo el anillo exterior: un hueco interior en una celda de tesselación es un
    artefacto de precisión, no un patio, y arrastrarlo obligaría al notebook a saber
    de topología para dibujar un polígono.
    """
    wgs = gdf.to_crs("EPSG:4326")
    filas = []
    for clave_valor, geom in zip(wgs[clave], wgs.geometry, strict=True):
        if geom is None or geom.is_empty:
            continue
        partes = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        mayor = max(partes, key=lambda g: g.area)
        filas.append(
            {
                clave: str(clave_valor),
                "lng": [round(x, 6) for x, _ in mayor.exterior.coords],
                "lat": [round(y, 6) for _, y in mayor.exterior.coords],
            }
        )
    return pd.DataFrame(filas)


# ─── emisión ──────────────────────────────────────────────────────────────────
def emitir(
    celdas_tabla: pd.DataFrame,
    aristas_tejido: pd.DataFrame,
    grilla: gpd.GeoDataFrame,
    aristas_h3: pd.DataFrame,
    corr: pd.DataFrame,
    script: str = __file__,
) -> None:
    """Emite al registro las cifras portantes de la comparación entre unidades."""
    fuentes = [ADMIN, H3_EDGES, OSM]

    def _emit(family: str, value: float, *, variant: str, unit: str, estimator: str) -> None:
        canon.emit(
            family, value, variant=variant, unit=unit, estimator=estimator,
            inputs=fuentes, script=script,
        )

    n_tess = len(celdas_tabla)
    n_hex = len(grilla)

    _emit(
        "tejido.celdas", float(n_tess), variant="morfologica", unit="celdas de la tesselación",
        estimator=f"celdas de morphological_graph sobre {CAPA_EDIFICIOS} recortado a la grilla",
    )
    _emit(
        "tejido.aristas", float(len(aristas_tejido)), variant="morfologica",
        unit="aristas no dirigidas",
        estimator="pares touched_to (contigüidad dentro de la manzana cerrada), no dirigidos",
    )
    _emit(
        "tejido.grado_medio", float(celdas_tabla["grado"].mean()), variant="morfologica",
        unit="vecinos por celda",
        estimator=f"2·aristas/celdas sobre el grafo touched_to ({n_tess} celdas)",
    )
    _emit(
        "tejido.grado_desviacion", float(celdas_tabla["grado"].std(ddof=0)), variant="morfologica",
        unit="vecinos por celda",
        estimator="desviación estándar poblacional del grado en el grafo touched_to",
    )
    for etiqueta, valor in (
        ("mediana", celdas_tabla["area_m2"].median()),
        ("p05", celdas_tabla["area_m2"].quantile(0.05)),
        ("p95", celdas_tabla["area_m2"].quantile(0.95)),
    ):
        _emit(
            f"tejido.area_{etiqueta}", float(valor), variant="morfologica", unit="m² por celda",
            estimator=f"{etiqueta} del área de celda morfológica sobre {n_tess} celdas",
        )

    _emit(
        "hexagono.aristas", float(len(aristas_h3)), variant="grilla_canonica",
        unit="aristas no dirigidas",
        estimator=f"pares de {H3_EDGES.name} normalizados a no dirigidos",
    )
    grado_h3 = 2.0 * len(aristas_h3) / n_hex
    _emit(
        "hexagono.grado_medio", grado_h3, variant="grilla_canonica", unit="vecinos por celda",
        estimator=f"2·aristas/celdas sobre la adyacencia H3 ({n_hex} hexágonos)",
    )
    _emit(
        "hexagono.area_mediana", float(grilla.geometry.area.median()),
        variant="grilla_canonica", unit="m² por celda",
        estimator=f"mediana del área de hexágono H3 res-8 en {CRS_METRICO}",
    )

    # ── el hallazgo: el hexágono parte el tejido, y el tejido no cubre el hexágono ──
    hexes_por_tess = corr.groupby("tess_id", observed=True)["h3_index"].nunique()
    partidas = 100.0 * float((hexes_por_tess > 1).mean())
    _emit(
        "correspondencia.celdas_partidas", partidas, variant="morfologica",
        unit="% de celdas de la tesselación",
        estimator=(
            f"celdas con área ≥{AREA_MINIMA_M2:.0f} m² en más de un hexágono / "
            f"{len(hexes_por_tess)} celdas con correspondencia"
        ),
    )
    area_por_tess = corr.groupby("tess_id", observed=True)["area_m2"].sum()
    partida_area = 100.0 * float(
        area_por_tess[hexes_por_tess > 1].sum() / area_por_tess.sum()
    )
    _emit(
        "correspondencia.area_partida", partida_area, variant="morfologica",
        unit="% del área del tejido",
        estimator="área en celdas repartidas entre ≥2 hexágonos / área total del tejido",
    )

    tess_por_hex = corr.groupby("h3_index", observed=True)["tess_id"].nunique()
    _emit(
        "correspondencia.tejido_por_hexagono_mediana", float(tess_por_hex.median()),
        variant="grilla_canonica", unit="celdas por hexágono",
        estimator=(
            f"mediana de celdas morfológicas por hexágono sobre "
            f"{len(tess_por_hex)} hexágonos con tejido"
        ),
    )
    _emit(
        "correspondencia.hexagonos_sin_tejido", 100.0 * (n_hex - len(tess_por_hex)) / n_hex,
        variant="grilla_canonica", unit="% de la grilla canónica",
        estimator=f"hexágonos sin ninguna celda morfológica / {n_hex} hexágonos de la grilla",
    )
    cobertura = corr.groupby("h3_index", observed=True)["frac_h3"].sum()
    _emit(
        "correspondencia.cobertura_areal_mediana", 100.0 * float(cobertura.median()),
        variant="grilla_canonica", unit="% del área del hexágono",
        estimator=f"mediana de Σ frac_h3 sobre los {len(cobertura)} hexágonos con tejido",
    )
    _emit(
        "correspondencia.desvio_masa", desvio_de_masa(corr),
        variant="morfologica", unit="desvío relativo (adim.)",
        estimator="máx |Σ frac_tess − 1| sobre las celdas completamente dentro de la grilla",
    )


# ─── orquestación ─────────────────────────────────────────────────────────────
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    grilla = leer_grilla()
    limite = unary_union(grilla.geometry.values)
    print(f"  grilla canónica: {len(grilla):,} hexágonos, {limite.area / 1e6:,.0f} km²")

    edificios, vias = leer_osm(limite)
    print(f"  insumos OSM: {len(edificios):,} edificios · {len(vias):,} vías barrera")

    celdas, aristas_tejido, de_cache = tejido_con_cache(edificios, vias, limite)
    print(
        f"  tejido: {len(celdas):,} celdas · {len(aristas_tejido):,} aristas no dirigidas"
        f"{'  (desde caché)' if de_cache else ''}"
    )

    # El recorte va ANTES de medir nada: sin él la tesselación encerrada tapa el límite
    # entero y todo lo que sigue mide la grilla en vez de la ciudad. Ver inwatch-72j.
    area_cruda = float(celdas.geometry.area.sum())
    n_crudas = len(celdas)
    mascara = mascara_construida(edificios, grilla)
    celdas, sin_edificio = recortar_a_construido(celdas, mascara)
    celdas, disputada = desolapar(celdas)
    # Las aristas que apuntan a una celda que ya no existe se van con ella: `touched_to`
    # une celdas de la misma manzana, y una manzana sin edificación no tiene tejido que
    # conectar. Dejarlas inflaría el grado con vecinos que no están en la tabla.
    vivas = set(celdas["tess_id"])
    n_aristas_crudas = len(aristas_tejido)
    aristas_tejido = aristas_tejido[
        aristas_tejido["src_tess"].isin(vivas) & aristas_tejido["dst_tess"].isin(vivas)
    ].reset_index(drop=True)
    area_util = float(celdas.geometry.area.sum())
    print(
        f"  máscara r={RADIO_CONSTRUIDO_M:.0f} m: {area_util / 1e6:,.0f} km² construidos "
        f"de {area_cruda / 1e6:,.0f} km² teselados "
        f"({100 * (1 - area_util / area_cruda):.1f}% era hueco disfrazado de tejido)"
    )
    print(
        f"  celdas sin un solo edificio: {sin_edificio:,} de {n_crudas:,} "
        f"({100 * sin_edificio / n_crudas:.1f}%) — son el hueco, salen de la tabla; "
        f"con ellas se van {n_aristas_crudas - len(aristas_tejido):,} aristas"
    )
    if disputada:
        print(f"  solape resuelto: {disputada:,.0f} m² que dos celdas reclamaban a la vez")

    celdas_tabla = tabla_celdas(celdas, aristas_tejido)
    corr = correspondencia(celdas, grilla)
    cobertura = cobertura_por_hexagono(corr, grilla)
    aristas_h3 = leer_aristas_h3()
    print(
        f"  correspondencia: {len(corr):,} pares tess↔h3 · "
        f"{int((~cobertura['tiene_tejido']).sum()):,} hexágonos sin tejido"
    )

    emitir(celdas_tabla, aristas_tejido, grilla, aristas_h3, corr)

    hex_win, tess_win = ventana_muestra(celdas, grilla, corr)

    salidas = {
        "tejido_celdas": celdas_tabla,
        "tejido_aristas": aristas_tejido,
        "correspondencia_h3_tejido": corr,
        "hexagonos_cobertura": cobertura,
        "ventana_hexagonos": hex_win,
        "ventana_tejido": tess_win,
    }
    for nombre, df in salidas.items():
        dest = OUT / f"{nombre}.parquet"
        df.to_parquet(dest, index=False)
        print(f"  → {dest.name}  ({len(df):,} filas)")

    # La geometría completa va aparte y en WKB: no es reconstruible desde `tess_id`,
    # pero tampoco pertenece a la tabla de features. Quien la necesite la pide.
    geo = pd.DataFrame(
        {
            "tess_id": celdas["tess_id"].astype("string"),
            "geometry_wkb": celdas.to_crs("EPSG:4326").geometry.to_wkb(),
        }
    )
    geo.to_parquet(OUT / "tejido_geometria.parquet", index=False)
    print(f"  → tejido_geometria.parquet  ({len(geo):,} polígonos, WGS84, WKB)")


if __name__ == "__main__":
    main()
