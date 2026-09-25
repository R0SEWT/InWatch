"""Las dos unidades alternativas del hito 2: banda de red y celda morfológica.

El hito 1 recortó el espacio con anillos euclidianos alrededor del punto del estadio,
igual que el repo de origen. Pero el propio repo de origen escribió, en
``eval_stadium_corridors.py``, que *la multitud no llega en círculos, llega por el
Metropolitano y la Línea 1* — y respondió con buffers de 300 m alrededor de estaciones,
que es geometría euclidiana centrada en otro punto. Nadie recortó por la red que la
gente camina. Este módulo lo hace, de dos formas:

- ``banda_red`` — distancia **sobre el grafo peatonal** de OSM, con los mismos cortes
  en metros que los anillos (0-500-1000-2000-4000 m de red).
- ``morfologica`` — la celda de la tesselación de E5 (``tejido-vs-hexagono``),
  agregada por **anillos de adyacencia**: saltos de celda en celda desde la del estadio.

Por qué vive aparte del ``loader.py``: todo esto necesita el extra ``geo`` (osmnx,
geopandas, scipy), y el loader del hito 1 corre sin él salvo por ``h3``. El loader lo
importa sólo cuando se piden las unidades nuevas.

TRES DECISIONES QUE MUEVEN EL RESULTADO, a la vista y no enterradas:

1. **Mismos metros no es mismo tamaño.** La distancia de red es siempre mayor o igual a
   la euclidiana, así que la banda de red de 0-500 m es un recorte MÁS CHICO que el
   disco de 500 m. Si el pulso cambia, no se sabría si fue la forma o el tamaño. Por eso
   hay una tercera variante, ``banda_red_area``: mismos cortes de red, pero elegidos para
   que cada banda acumulada tenga el área del disco euclidiano correspondiente. Aísla la
   forma. La tesselación, que se mide en saltos y no en metros, sólo admite esta versión.

2. **La adyacencia de E5 no cruza calles.** ``tejido_aristas.parquet`` guarda sólo
   ``touched_to``, que une celdas dentro de la misma manzana cerrada: es el punto de E5
   —dos edificios a ambos lados de una avenida no son vecinos—. Pero entonces un anillo
   de adyacencia no sale nunca de la manzana del estadio. Aquí se añade la contigüidad
   **entre** manzanas (celdas cuyo polígono toca al de otra manzana a través del eje de
   la calle), y cruzar la calle cuenta como un salto más. Es una decisión de este hito,
   no de E5, y va declarada.

3. **El tejido no cubre la ciudad.** Donde OSM no tiene edificios no hay celda, y el
   punto de denuncia queda sin unidad. Ese punto se PIERDE para la unidad morfológica
   y se reporta como masa perdida; no se reasigna a la celda más cercana. Reasignarlo
   inventaría tejido donde no hay registro — la regla dura *sin datos ≠ seguro* dicha
   en geometría.

Todo en EPSG:32718. Nunca se mide en grados.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

import numpy as np
import pandas as pd

CRS_METRICO = "EPSG:32718"

# Cortes en metros: los mismos del anillo euclidiano del hito 1 (``RING_EDGES``).
CORTES_M = (0.0, 500.0, 1000.0, 2000.0, 4000.0)

# Un punto se engancha al nodo peatonal más cercano sólo si está a menos de esto. Más
# lejos, no hay red caminable registrada que lo alcance: se pierde para la banda de red
# y se cuenta como masa perdida. 150 m es media cuadra larga de Lima; más allá el punto
# está en un parque, un cerro o un vacío de OSM, no sobre una vereda que falte dibujar.
SNAP_MAX_M = 150.0

# El estadio no es un nodo: es un polígono de cientos de metros. La distancia de red se
# mide desde su punto (el mismo del anillo) con acceso en línea recta a todo nodo a menos
# de este radio, que cubre el perímetro de los tres recintos. Sin esto, el origen sería
# un único nodo arbitrario —una escalera de tribuna o una esquina— y la banda 0-500 se
# corría hacia ese lado.
RADIO_FUENTE_M = 300.0

# Resolución de la rejilla con la que se miden áreas de banda. Una banda de red no es un
# polígono cerrado: es el conjunto de lugares cuya distancia de red cae en el corte. Se
# mide contando píxeles de 25 m, cada uno asignado como se asignaría un punto.
PIXEL_M = 25.0

# Ventana de la unidad morfológica alrededor de cada estadio. Tiene que exceder el anillo
# exterior para que el corte igualado por área tenga de dónde elegir.
VENTANA_M = 5000.0


# ─── banda de red ────────────────────────────────────────────────────────────
def distancia_red(
    nodos_xy: np.ndarray,
    aristas: Iterable[tuple[int, int, float]],
    origen_xy: np.ndarray,
    puntos_xy: np.ndarray,
    *,
    radio_fuente: float = RADIO_FUENTE_M,
    snap_max: float = SNAP_MAX_M,
) -> np.ndarray:
    """Distancia de red desde ``origen_xy`` hasta cada punto; ``nan`` si no engancha.

    d(p) = min_s (|origen − s| + d_G(s, n(p))) + |p − n(p)|, con s los nodos a menos de
    ``radio_fuente`` del origen y n(p) el nodo más cercano a p. Es un Dijkstra de fuente
    múltiple: equivale a agregar un nodo virtual en el origen unido en línea recta a los
    nodos cercanos.

    ``nodos_xy``: (N, 2) en metros; ``aristas``: (i, j, largo_m) no dirigidas, con índices
    en ``nodos_xy``.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    from scipy.spatial import cKDTree

    n = len(nodos_xy)
    ar = np.asarray(aristas if isinstance(aristas, np.ndarray) else list(aristas),
                    dtype=float).reshape(-1, 3)
    d_origen = np.hypot(*(nodos_xy - origen_xy).T)
    fuentes = np.flatnonzero(d_origen <= radio_fuente)
    if len(fuentes) == 0:
        fuentes = np.array([int(np.argmin(d_origen))])

    # Nodo virtual n: une al origen con cada fuente a su distancia recta.
    i = np.concatenate([ar[:, 0], ar[:, 1], np.full(len(fuentes), n)]).astype(int)
    j = np.concatenate([ar[:, 1], ar[:, 0], fuentes]).astype(int)
    w = np.concatenate([ar[:, 2], ar[:, 2], d_origen[fuentes]])
    # dijkstra toma el mínimo entre aristas paralelas sólo si no se suman: coo→csr suma
    # duplicados, así que se reduce al mínimo antes.
    m = pd.DataFrame({"i": i, "j": j, "w": w}).groupby(["i", "j"], as_index=False)["w"].min()
    # Un peso 0 se lee como "sin arista" en matrices dispersas: se sube a un épsilon.
    pesos = np.maximum(m["w"].to_numpy(), 1e-6)
    grafo = coo_matrix((pesos, (m["i"], m["j"])), shape=(n + 1, n + 1)).tocsr()
    d_nodo = dijkstra(grafo, directed=True, indices=n)[:n]

    arbol = cKDTree(nodos_xy)
    snap, idx = arbol.query(puntos_xy)
    d = d_nodo[idx] + snap
    d[(snap > snap_max) | ~np.isfinite(d)] = np.nan
    return d


# Qué no se camina. El resto de ``gis_osm_roads_free`` sí: veredas (``footway``),
# escaleras, pasajes, calles de todo rango. ``busway`` es el carril exclusivo del
# Metropolitano —la gente llega POR él, pero no caminando sobre él: baja en la estación
# y sale por el puente peatonal, que sí está en la red como ``footway``—.
NO_CAMINABLE = frozenset({"motorway", "motorway_link", "busway", "cycleway"})


def red_desde_lineas(lon_lat_lineas: Iterable[np.ndarray], a_metros) -> tuple[
        np.ndarray, np.ndarray]:
    """(nodos_xy, aristas) desde las polilíneas de OSM, con la topología de OSM.

    Dos vías se conectan sólo donde COMPARTEN un vértice, que es como OSM codifica una
    intersección. No se nodifica por cruce geométrico: un puente peatonal sobre la Vía
    Expresa cruza la calzada en el plano sin conectarse a ella, y nodificar lo uniría —
    inventando un cruce a nivel que no existe—. Por eso tampoco hace falta leer
    ``bridge``/``tunnel``.

    ``lon_lat_lineas``: arreglos (k, 2) en grados, tal como vienen del extracto;
    ``a_metros``: función (lon, lat) → (x, y) en EPSG:32718. Las aristas son (i, j, largo)
    con el largo medido en metros entre vértices consecutivos.
    """
    trozos = [np.asarray(c, dtype=float) for c in lon_lat_lineas if len(c) >= 2]
    todos = np.concatenate(trozos)
    # Mismo nodo OSM = misma coordenada exacta en el extracto; se redondea a 1e-7° (~1 cm)
    # sólo para absorber la representación en coma flotante.
    claves = np.round(todos * 1e7).astype(np.int64)
    unicos, inv = np.unique(claves, axis=0, return_inverse=True)
    inv = inv.ravel()
    x, y = a_metros(unicos[:, 0] / 1e7, unicos[:, 1] / 1e7)
    xy = np.column_stack([x, y])
    largos = np.cumsum([0] + [len(c) for c in trozos])
    i_list, j_list = [], []
    for k in range(len(trozos)):
        ids = inv[largos[k]:largos[k + 1]]
        i_list.append(ids[:-1])
        j_list.append(ids[1:])
    i, j = np.concatenate(i_list), np.concatenate(j_list)
    ok = i != j
    i, j = i[ok], j[ok]
    w = np.hypot(*(xy[i] - xy[j]).T)
    return xy, np.column_stack([i, j, w])


# ─── celda morfológica ───────────────────────────────────────────────────────
def saltos(adyacencia: dict, semillas: Iterable) -> dict:
    """BFS: número de saltos desde el conjunto de celdas semilla. Las no alcanzadas faltan."""
    dist = {}
    cola = deque()
    for s in semillas:
        if s not in dist:
            dist[s] = 0
            cola.append(s)
    while cola:
        u = cola.popleft()
        for v in adyacencia.get(u, ()):
            if v not in dist:
                dist[v] = dist[u] + 1
                cola.append(v)
    return dist


def adyacencia(pares: Iterable[tuple]) -> dict:
    """Lista de adyacencia no dirigida desde pares (u, v)."""
    ady: dict = {}
    for u, v in pares:
        if u == v:
            continue
        ady.setdefault(u, set()).add(v)
        ady.setdefault(v, set()).add(u)
    return ady


def contiguidad_entre_manzanas(celdas, tolerancia_m: float = 0.5) -> list[tuple[str, str]]:
    """Pares de celdas de manzanas DISTINTAS cuyos polígonos se tocan (± tolerancia).

    Complementa ``touched_to`` —que por construcción sólo une celdas de la misma manzana—
    con el cruce de calle. ``celdas`` es un GeoDataFrame con ``tess_id``, ``manzana`` y
    geometría en metros.
    """
    import shapely

    geoms = celdas.geometry.to_numpy()
    arbol = shapely.STRtree(geoms)
    izq, der = arbol.query(shapely.buffer(geoms, tolerancia_m), predicate="intersects")
    man = celdas["manzana"].to_numpy()
    ids = celdas["tess_id"].to_numpy()
    ok = (izq < der) & (man[izq] != man[der])
    return list(zip(ids[izq[ok]], ids[der[ok]], strict=True))


# ─── cortes igualados por área ───────────────────────────────────────────────
def cortes_por_area(valores: np.ndarray, areas: np.ndarray, objetivo: np.ndarray) -> np.ndarray:
    """Umbrales t_k tales que el área acumulada con valor < t_k se acerque a ``objetivo[k]``.

    ``valores`` es la distancia (de red o en saltos) de cada pieza de área —un píxel, una
    celda— y ``areas`` su área. Para valores discretos (saltos) el umbral cae en el entero
    cuya área acumulada queda más cerca del objetivo: no se parte un anillo de saltos.
    Devuelve un umbral por objetivo, no decreciente.
    """
    ok = np.isfinite(valores)
    v, a = valores[ok], areas[ok]
    orden = np.argsort(v, kind="stable")
    v, acum = v[orden], np.cumsum(a[orden])
    distintos, ultimo = np.unique(v), None
    # área acumulada con valor <= cada valor distinto
    fin = np.searchsorted(v, distintos, side="right") - 1
    acum_d = acum[fin]
    umbrales = []
    for obj in objetivo:
        k = int(np.argmin(np.abs(acum_d - obj)))
        t = float(distintos[k])
        # el umbral es exclusivo por arriba (banda = [t_{k-1}, t_k)), así que se corre
        # al siguiente valor para incluir el elegido
        t_ex = float(distintos[k + 1]) if k + 1 < len(distintos) else t + 1.0
        if ultimo is not None and t_ex < ultimo:
            t_ex = ultimo
        umbrales.append(t_ex)
        ultimo = t_ex
    return np.array(umbrales)


def banda(valores: np.ndarray, cortes: np.ndarray) -> np.ndarray:
    """Índice de banda por corte [c_k, c_{k+1}); −1 fuera o sin valor."""
    b = np.full(len(valores), -1, dtype=int)
    ok = np.isfinite(valores)
    k = np.searchsorted(cortes, valores[ok], side="right") - 1
    k[(k < 0) | (k >= len(cortes) - 1)] = -1
    b[ok] = k
    return b


# ─── correspondencia y masa ──────────────────────────────────────────────────
def correspondencia(etiquetas: pd.DataFrame, origen: str, destino: str,
                    area_pieza: float) -> pd.DataFrame:
    """Tabla banda_origen × banda_destino con área y los dos factores.

    ``etiquetas`` tiene una fila por pieza de área (píxel) y una columna de banda por
    unidad (−1 = fuera). Como en ``correspondencia_h3_tejido``, son dos factores porque
    las unidades no se anidan: ``frac_origen`` reparte de origen a destino y suma 1 sólo
    si toda la banda de origen cae dentro de alguna banda de destino; el déficit es área
    que el destino no cubre, y NO se normaliza.
    """
    e = etiquetas[etiquetas[origen] >= 0]
    tab = e.groupby([origen, destino]).size().rename("n_piezas").reset_index()
    tab["area_m2"] = tab["n_piezas"] * area_pieza
    tot_o = e.groupby(origen).size() * area_pieza
    tot_d = etiquetas[etiquetas[destino] >= 0].groupby(destino).size() * area_pieza
    tab["frac_origen"] = tab["area_m2"] / tab[origen].map(tot_o)
    tab["frac_destino"] = np.where(tab[destino] >= 0,
                                   tab["area_m2"] / tab[destino].map(tot_d).fillna(np.inf),
                                   np.nan)
    return tab.rename(columns={origen: "banda_origen", destino: "banda_destino"}).assign(
        unidad_origen=origen, unidad_destino=destino)


def desvio_de_masa(corr: pd.DataFrame) -> float:
    """Máximo |Σ frac_origen − 1| por banda de origen, contando la fila «fuera» (−1).

    Con la fila −1 incluida, toda banda de origen tiene que sumar exactamente 1: cada
    pieza de área cae en una banda de destino o fuera de todas, nunca en dos ni en
    ninguna. Un desvío mayor que el error de coma flotante es masa perdida o inventada.
    """
    if corr.empty:
        raise ValueError("correspondencia vacía: nada que verificar")
    # una tabla por (estadio, sentido): se agrupa por todo lo que la identifica
    claves = [c for c in ("estadio", "unidad_origen", "unidad_destino") if c in corr]
    s = corr.groupby([*claves, "banda_origen"])["frac_origen"].sum()
    return float((s - 1).abs().max())


# ─── orquestación sobre los datos reales ─────────────────────────────────────
UNIDADES = ("anillo", "banda_red", "banda_red_area", "morfologica")

# Margen de lectura de la red y del tejido más allá de la ventana: un camino de red que
# sale y vuelve a entrar necesita la calle de afuera para existir.
MARGEN_M = 1500.0


def _a_metros():
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", CRS_METRICO, always_xy=True)
    return lambda lon, lat: tr.transform(lon, lat)


def _pixeles(centro: np.ndarray, radio: float, lado: float = PIXEL_M) -> np.ndarray:
    """Centros de una rejilla de ``lado`` m dentro del disco de ``radio``."""
    r = np.arange(-radio + lado / 2, radio, lado)
    gx, gy = np.meshgrid(r, r)
    m = np.hypot(gx, gy) <= radio
    return np.column_stack([gx[m] + centro[0], gy[m] + centro[1]])


def cargar_red(ruta_gpkg, estadios_xy: dict, radio: float):
    """Red peatonal del extracto Geofabrik alrededor de los estadios."""
    import geopandas as gpd
    import pyogrio
    import shapely

    zona = shapely.union_all([shapely.Point(*c).buffer(radio + MARGEN_M)
                              for c in estadios_xy.values()])
    bbox = gpd.GeoSeries([zona], crs=CRS_METRICO).to_crs(4326).total_bounds
    vias = pyogrio.read_dataframe(ruta_gpkg, layer="gis_osm_roads_free", bbox=tuple(bbox))
    vias = vias[~vias["fclass"].isin(NO_CAMINABLE)]
    lineas = [np.asarray(g.coords) for g in vias.geometry]
    nodos_xy, aristas = red_desde_lineas(lineas, _a_metros())
    return nodos_xy, aristas, len(vias)


def cargar_tejido(dir_tejido, estadios_xy: dict, radio: float):
    """Celdas del tejido de E5 alrededor de los estadios, en metros, con su adyacencia.

    La geometría de ``tejido_geometria.parquet`` está en WGS84 (así la escribe el loader
    de E5); se proyecta acá.
    """
    import geopandas as gpd
    import shapely

    geo = pd.read_parquet(dir_tejido / "tejido_geometria.parquet")
    cel = pd.read_parquet(dir_tejido / "tejido_celdas.parquet")
    T = gpd.GeoDataFrame({"tess_id": geo["tess_id"].astype(str)},
                         geometry=shapely.from_wkb(geo["geometry_wkb"].to_numpy()),
                         crs=4326).to_crs(CRS_METRICO)
    zona = shapely.union_all([shapely.Point(*c).buffer(radio + MARGEN_M)
                              for c in estadios_xy.values()])
    T = T[T.intersects(zona)].copy()
    T = T.merge(cel[["tess_id", "enclosure_index"]].astype({"tess_id": str}),
                on="tess_id", how="left").rename(columns={"enclosure_index": "manzana"})
    ar = pd.read_parquet(dir_tejido / "tejido_aristas.parquet").astype(str)
    dentro = set(T["tess_id"])
    ar = ar[ar["src_tess"].isin(dentro) & ar["dst_tess"].isin(dentro)]
    pares_intra = list(zip(ar["src_tess"], ar["dst_tess"], strict=True))
    pares_inter = contiguidad_entre_manzanas(T)
    return T.reset_index(drop=True), pares_intra, pares_inter


def _celda_de(T, xy: np.ndarray) -> np.ndarray:
    """tess_id que contiene cada punto; None si cae fuera del tejido (masa perdida)."""
    import shapely

    arbol = shapely.STRtree(T.geometry.to_numpy())
    pi, ci = arbol.query(shapely.points(xy), predicate="within")
    salida = np.full(len(xy), None, dtype=object)
    ids = T["tess_id"].to_numpy()
    # en un borde compartido gana el primero; `within` estricto hace que casi no pase
    salida[pi[::-1]] = ids[ci[::-1]]
    return salida


def etiquetar(x: np.ndarray, y: np.ndarray, estadios_xy: dict, ruta_gpkg, dir_tejido,
              cortes_m=CORTES_M):
    """Banda de cada punto en cada unidad y estadio, y las tablas que la sostienen.

    Devuelve ``(bandas, cortes, correspondencia, masa)``:
      - ``bandas[(unidad, estadio)]`` — arreglo con la banda de cada punto (−1 = fuera).
      - ``cortes`` — umbrales efectivos y área de cada banda, por estadio y unidad.
      - ``correspondencia`` — anillo ↔ cada unidad, con los dos factores de área.
      - ``masa`` — puntos por banda y puntos perdidos, por estadio y unidad.
    """
    cortes_m = np.asarray(cortes_m, dtype=float)
    radio_max = float(cortes_m[-1])
    ventana = radio_max * 1.5  # holgura para los cortes igualados por área
    pts = np.column_stack([x, y])

    nodos_xy, aristas, n_vias = cargar_red(ruta_gpkg, estadios_xy, ventana)
    print(f"  red peatonal: {n_vias:,} vías → {len(nodos_xy):,} nodos, "
          f"{len(aristas):,} aristas")
    T, intra, inter = cargar_tejido(dir_tejido, estadios_xy, ventana)
    ady = adyacencia(intra + inter)
    print(f"  tejido: {len(T):,} celdas, {len(intra):,} aristas touched_to + "
          f"{len(inter):,} cruces de calle")
    area_celda = dict(zip(T["tess_id"], T.geometry.area, strict=True))

    bandas, f_cortes, f_corr, f_masa = {}, [], [], []
    for st, c in estadios_xy.items():
        r = np.hypot(x - c[0], y - c[1])
        cerca = np.flatnonzero(r < ventana)
        px = _pixeles(np.asarray(c), ventana)
        r_px = np.hypot(*(px - c).T)
        a_px = PIXEL_M ** 2

        # anillo: la réplica del hito 1
        b_anillo = banda(r, cortes_m)
        et = {"anillo": banda(r_px, cortes_m)}

        # banda de red, mismos metros
        d_pt = np.full(len(x), np.nan)
        d_pt[cerca] = distancia_red(nodos_xy, aristas, np.asarray(c), pts[cerca])
        d_px = distancia_red(nodos_xy, aristas, np.asarray(c), px)
        b_red = banda(d_pt, cortes_m)
        et["banda_red"] = banda(d_px, cortes_m)

        # banda de red igualada por área: cada banda acumulada con el área de red
        # alcanzable que tiene el disco euclidiano del mismo corte
        alcanzable = np.isfinite(d_px)
        objetivo = np.array([alcanzable[r_px < rk].sum() * a_px for rk in cortes_m[1:]])
        t_red = np.concatenate([[0.0], cortes_por_area(d_px, np.full(len(d_px), a_px),
                                                       objetivo)])
        b_red_a = banda(d_pt, t_red)
        et["banda_red_area"] = banda(d_px, t_red)

        # morfológica: saltos desde la celda del estadio
        semilla = _celda_de(T, np.asarray([c]))[0]
        if semilla is None:
            dist_c = T.geometry.distance(__import__("shapely").Point(*c)).to_numpy()
            semilla = T["tess_id"].iloc[int(np.argmin(dist_c))]
        h = saltos(ady, [semilla])
        celda_pt = np.full(len(x), None, dtype=object)
        celda_pt[cerca] = _celda_de(T, pts[cerca])
        celda_px = _celda_de(T, px)
        h_pt = np.array([h.get(k, np.nan) if k is not None else np.nan for k in celda_pt],
                        dtype=float)
        h_px = np.array([h.get(k, np.nan) if k is not None else np.nan for k in celda_px],
                        dtype=float)
        # objetivo: el área de TEJIDO dentro de cada disco euclidiano —no el área del
        # disco—, porque fuera del tejido no hay celda que elegir
        con_tejido = np.array([k is not None for k in celda_px])
        obj_m = np.array([(con_tejido & (r_px < rk)).sum() * a_px for rk in cortes_m[1:]])
        ids_h = np.array(list(h.keys()))
        v_h = np.array([h[k] for k in ids_h], dtype=float)
        a_h = np.array([area_celda[k] for k in ids_h])
        t_m = np.concatenate([[0.0], cortes_por_area(v_h, a_h, obj_m)])
        b_mor = banda(h_pt, t_m)
        et["morfologica"] = banda(h_px, t_m)

        for unidad, b in (("anillo", b_anillo), ("banda_red", b_red),
                          ("banda_red_area", b_red_a), ("morfologica", b_mor)):
            bandas[(unidad, st)] = b

        # tablas
        for unidad, t, metrica in (("anillo", cortes_m, "m euclidianos"),
                                   ("banda_red", cortes_m, "m de red"),
                                   ("banda_red_area", t_red, "m de red"),
                                   ("morfologica", t_m, "saltos de celda")):
            for k in range(len(cortes_m) - 1):
                f_cortes.append({
                    "estadio": st, "unidad": unidad, "banda": k,
                    "corte_lo": float(t[k]), "corte_hi": float(t[k + 1]), "metrica": metrica,
                    "area_m2": float((et[unidad] == k).sum() * a_px),
                    "area_disco_m2": float(np.pi * (cortes_m[k + 1] ** 2 - cortes_m[k] ** 2)),
                })
        tab = pd.DataFrame(et)
        for unidad in UNIDADES[1:]:
            for o, d in (("anillo", unidad), (unidad, "anillo")):
                f_corr.append(correspondencia(tab, o, d, a_px).assign(estadio=st))
        n_anillo = int((b_anillo >= 0).sum())
        for unidad, b in (("anillo", b_anillo), ("banda_red", b_red),
                          ("banda_red_area", b_red_a), ("morfologica", b_mor)):
            fila = {"estadio": st, "unidad": unidad,
                    "n_puntos_en_bandas": int((b >= 0).sum()),
                    "n_puntos_anillo": n_anillo,
                    # de los puntos que el anillo sí mide, cuántos se quedan sin banda en
                    # esta unidad porque no hay red o tejido debajo (no por estar lejos)
                    "n_perdidos_sin_unidad": int(((b_anillo >= 0)
                                                  & ~np.isfinite({"anillo": r,
                                                                  "banda_red": d_pt,
                                                                  "banda_red_area": d_pt,
                                                                  "morfologica": h_pt}
                                                                 [unidad])).sum())}
            for k in range(len(cortes_m) - 1):
                fila[f"n_banda_{k}"] = int((b == k).sum())
            f_masa.append(fila)
        print(f"  {st}: semilla morfológica {semilla}; cortes red_area="
              f"{np.round(t_red).tolist()} · morfológica={t_m.tolist()}")

    return (bandas, pd.DataFrame(f_cortes), pd.concat(f_corr, ignore_index=True),
            pd.DataFrame(f_masa))
