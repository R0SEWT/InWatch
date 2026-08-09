"""Tests de `tejido-vs-hexagono`.

El grueso corre con geometría **sintética** y sin marcador, porque el CI excluye
`needs_data` y un archivo que fuera todo `needs_data` no verificaría nada. La
geometría inventada acá es cuadrada a propósito: un cuadrado de 100 m tiene área
exacta 10 000 m² y deja que un fallo de reparto de masa se lea como aritmética, no
como error de redondeo de una proyección.

El test que el contrato de unidades exige por escrito —"que la correspondencia no
pierde ni inventa masa"— es `test_correspondencia_conserva_el_area_de_la_celda`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

# El extra `geo` no está en el entorno base y el CI corre sin él: sin city2graph este
# archivo se salta entero en vez de romper la recolección.
gpd = pytest.importorskip("geopandas")
pytest.importorskip("city2graph")
from shapely.geometry import Polygon  # noqa: E402


def _cargar_loader():
    """Carga `loader.py` bajo un nombre de módulo **único**, no como `import loader`.

    Cada experimento tiene su propio `loader.py`, y un `import loader` los mete a todos
    bajo la misma clave de `sys.modules`: el segundo en importarse recibe en silencio el
    módulo del primero, y sus tests corren contra el loader equivocado. Es un fallo que
    no se ve —los tests pasan o fallan por el motivo incorrecto— así que la carga va por
    ruta explícita.
    """
    ruta = Path(__file__).parent / "loader.py"
    spec = importlib.util.spec_from_file_location("loader_tejido_vs_hexagono", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


loader = _cargar_loader()

AREA_MINIMA_M2 = loader.AREA_MINIMA_M2
VIAS_BARRERA = loader.VIAS_BARRERA
_a_coordenadas = loader._a_coordenadas
cobertura_por_hexagono = loader.cobertura_por_hexagono
correspondencia = loader.correspondencia
desolapar = loader.desolapar
desvio_de_masa = loader.desvio_de_masa
mascara_construida = loader.mascara_construida
recortar_a_construido = loader.recortar_a_construido
leer_aristas_h3 = loader.leer_aristas_h3
tabla_celdas = loader.tabla_celdas

CRS = "EPSG:32718"


def _cuadrado(x0: float, y0: float, lado: float) -> Polygon:
    return Polygon([(x0, y0), (x0 + lado, y0), (x0 + lado, y0 + lado), (x0, y0 + lado)])


def _grilla_falsa() -> gpd.GeoDataFrame:
    """Tres "hexágonos" cuadrados de 200 m en fila. La forma no importa: el reparto de
    área no sabe cuántos lados tiene el polígono que lo contiene.

    El tercero se queda **sin tejido encima** a propósito: es el caso que la regla dura
    número uno protege, y sin él ningún test notaría que se cayó de la tabla.
    """
    return gpd.GeoDataFrame(
        {
            "h3_index": ["hex_izq", "hex_der", "hex_desierto"],
            "distrito": ["Centro", "Centro", "Arenal"],
            "departamento": ["Lima", "Lima", "Lima"],
        },
        geometry=[_cuadrado(0, 0, 200), _cuadrado(200, 0, 200), _cuadrado(400, 0, 200)],
        crs=CRS,
    )


def _tejido_falso() -> gpd.GeoDataFrame:
    """Tres celdas: una dentro del hexágono izquierdo, una dentro del derecho, y una
    a caballo sobre el borde — el caso que el hexágono promedia en silencio."""
    return gpd.GeoDataFrame(
        {"tess_id": ["dentro_izq", "dentro_der", "a_caballo"], "enclosure_index": [0, 1, 2]},
        geometry=[
            _cuadrado(10, 10, 100),
            _cuadrado(250, 10, 100),
            _cuadrado(150, 50, 100),  # 50 m de ancho en cada hexágono, entera dentro
        ],
        crs=CRS,
    )


# ─── la exigencia del contrato de unidades ────────────────────────────────────
def test_correspondencia_conserva_el_area_de_la_celda():
    """Σ frac_tess == 1 para toda celda contenida en la grilla: ni pierde ni inventa.

    Es el test que `design/contrato-unidades.md` pide antes de admitir una unidad
    nueva. Si esto falla, cualquier cantidad repartida del tejido hacia H3 sale con
    masa distinta de la que entró, y ningún mapa posterior es comparable.
    """
    corr = correspondencia(_tejido_falso(), _grilla_falsa())
    suma = corr.groupby("tess_id")["frac_tess"].sum()
    assert set(suma.index) == {"dentro_izq", "dentro_der", "a_caballo"}
    assert suma.round(9).eq(1.0).all(), suma.to_dict()

    area = corr.groupby("tess_id")["area_m2"].sum()
    assert area.round(6).eq(10_000.0).all(), area.to_dict()


def test_correspondencia_reparte_la_celda_a_caballo_en_mitades():
    """La celda del borde se parte 50/50, y las dos mitades quedan explícitas.

    El punto entero del experimento: sin esta tabla, el valor de esa celda entraría
    completo a un hexágono elegido por un `merge` implícito.
    """
    corr = correspondencia(_tejido_falso(), _grilla_falsa())
    caballo = corr[corr["tess_id"] == "a_caballo"].set_index("h3_index")["frac_tess"]
    assert len(caballo) == 2
    assert caballo.round(9).eq(0.5).all(), caballo.to_dict()


def test_correspondencia_no_inventa_cobertura_donde_no_hay_tejido():
    """Σ frac_h3 por hexágono es < 1 donde el tejido no cubre, y eso no es un error.

    `frac_h3` mide qué parte del hexágono ocupa el tejido. Que no sume 1 es la regla
    dura número uno expresada en aritmética: el hueco es ausencia de evidencia, y
    normalizarlo a 1 lo convertiría en evidencia de ausencia.
    """
    corr = correspondencia(_tejido_falso(), _grilla_falsa())
    cobertura = corr.groupby("h3_index")["frac_h3"].sum()
    assert (cobertura < 1.0).all(), cobertura.to_dict()
    # izquierdo: 10 000 de `dentro_izq` + 5 000 de la mitad a caballo, sobre 40 000 m².
    assert cobertura["hex_izq"] == pytest.approx(15_000 / 40_000)


def test_correspondencia_descarta_astillas_de_precision():
    """Una intersección por debajo de `AREA_MINIMA_M2` no cuenta como celda partida.

    Sin el piso, el borde compartido entre dos hexágonos genera slivers de área
    microscópica y "celda partida" mediría el épsilon de la librería geométrica.
    """
    astilla = gpd.GeoDataFrame(
        {"tess_id": ["casi_dentro"], "enclosure_index": [0]},
        # Sobresale 1 mm hacia el hexágono derecho: 200 m × 0,001 m = 0,2 m².
        geometry=[Polygon([(100, 0), (200.001, 0), (200.001, 200), (100, 200)])],
        crs=CRS,
    )
    corr = correspondencia(astilla, _grilla_falsa())
    assert corr["h3_index"].tolist() == ["hex_izq"]
    assert (corr["area_m2"] >= AREA_MINIMA_M2).all()


def test_desvio_de_masa_es_cero_en_una_tabla_sana():
    corr = correspondencia(_tejido_falso(), _grilla_falsa())
    assert desvio_de_masa(corr) == pytest.approx(0.0, abs=1e-9)


def test_desvio_de_masa_falla_si_ninguna_celda_queda_completa():
    """Sin una sola celda completa no hay nada contra qué verificar el reparto.

    Devolver 0 ahí sería el peor resultado posible: un check verde que no comprobó
    nada. Se prefiere el error ruidoso.
    """
    corr = pd.DataFrame(
        {"tess_id": ["a", "b"], "h3_index": ["h", "h"], "area_m2": [1.0, 1.0],
         "frac_tess": [0.4, 0.5], "frac_h3": [0.1, 0.1]}
    )
    with pytest.raises(ValueError, match="ninguna celda"):
        desvio_de_masa(corr)


# ─── cobertura: el hexágono sin tejido no puede desaparecer ───────────────────
def test_cobertura_conserva_los_hexagonos_sin_tejido():
    """Una fila por hexágono de la grilla, incluidos los que no tienen ni una celda.

    Es la regla dura número uno en forma de esquema. Un `groupby` sobre la
    correspondencia daría la tabla "correcta" y más chica, y borraría exactamente las
    celdas que hay que dibujar deshilachadas — el mapa siguiente diría que ahí no hay
    nada que mirar cuando lo que no hay es dato.
    """
    grilla = _grilla_falsa()
    corr = correspondencia(_tejido_falso(), grilla)
    cob = cobertura_por_hexagono(corr, grilla).set_index("h3_index")

    assert len(cob) == len(grilla)
    assert "hex_desierto" in cob.index
    assert not cob.loc["hex_desierto", "tiene_tejido"]
    assert cob.loc["hex_desierto", "celdas_tejido"] == 0
    assert cob.loc["hex_desierto", "cobertura_areal"] == 0.0


def test_cobertura_no_confunde_cero_con_no_medido():
    """El cero de un hexágono sin tejido ES el dato, no un faltante: nada queda en NaN.

    Si `cobertura_areal` saliera NaN, cualquier comparación contra un piso lo excluiría
    en silencio en vez de dibujarlo, que es el error opuesto y también fatal.
    """
    grilla = _grilla_falsa()
    cob = cobertura_por_hexagono(correspondencia(_tejido_falso(), grilla), grilla)
    assert cob["cobertura_areal"].notna().all()
    assert cob["celdas_tejido"].notna().all()
    assert cob["tiene_tejido"].sum() == 2


def test_cobertura_areal_es_la_suma_de_frac_h3():
    grilla = _grilla_falsa()
    corr = correspondencia(_tejido_falso(), grilla)
    cob = cobertura_por_hexagono(corr, grilla).set_index("h3_index")
    # 10 000 de `dentro_izq` + 5 000 de la mitad a caballo, sobre 40 000 m².
    assert cob.loc["hex_izq", "cobertura_areal"] == pytest.approx(15_000 / 40_000, rel=1e-6)


# ─── adyacencia ───────────────────────────────────────────────────────────────
def test_aristas_h3_se_normalizan_a_no_dirigidas(tmp_path):
    """El artefacto de origen guarda ida y vuelta; comparar sin normalizar duplicaría
    el grado del hexágono y regalaría el hallazgo."""
    ruta = tmp_path / "edges.parquet"
    pd.DataFrame(
        {"src_h3": ["a", "b", "a", "c", "a"], "dst_h3": ["b", "a", "c", "a", "a"]}
    ).to_parquet(ruta, index=False)

    par = leer_aristas_h3(ruta)
    assert len(par) == 2  # {a,b} y {a,c}; el autolazo a→a se descarta
    assert set(map(tuple, par.to_numpy())) == {("a", "b"), ("a", "c")}


def test_grado_cero_es_dato_y_no_faltante():
    """Una celda sola en su manzana tiene cero vecinos. Eso es una medición, no un
    hueco: dejarla en NaN la borraría de cualquier promedio de grado."""
    celdas = _tejido_falso()
    aristas = pd.DataFrame({"src_tess": ["dentro_izq"], "dst_tess": ["dentro_der"]})
    tabla = tabla_celdas(celdas, aristas).set_index("tess_id")

    assert tabla.loc["a_caballo", "grado"] == 0
    assert tabla["grado"].notna().all()
    assert tabla.loc["dentro_izq", "grado"] == 1
    assert tabla.loc["dentro_izq", "area_m2"] == pytest.approx(10_000.0)


# ─── geometría para la capa de presentación ───────────────────────────────────
def test_a_coordenadas_devuelve_solo_el_anillo_exterior():
    """El notebook corre en Pyodide y no tiene shapely: recibe listas de números.

    Un hueco interior en una celda de tesselación es un artefacto de precisión, no un
    patio, y arrastrarlo obligaría al notebook a saber de topología.
    """
    con_hueco = Polygon(
        [(0, 0), (100, 0), (100, 100), (0, 100)],
        [[(40, 40), (60, 40), (60, 60), (40, 60)]],
    )
    gdf = gpd.GeoDataFrame({"tess_id": ["x"]}, geometry=[con_hueco], crs=CRS)

    out = _a_coordenadas(gdf, "tess_id")
    assert list(out.columns) == ["tess_id", "lng", "lat"]
    assert len(out) == 1
    assert len(out.loc[0, "lng"]) == len(out.loc[0, "lat"]) == 5  # anillo cerrado
    assert all(isinstance(v, float) for v in out.loc[0, "lng"])


def test_a_coordenadas_omite_geometria_vacia():
    gdf = gpd.GeoDataFrame(
        {"tess_id": ["vacia", "buena"]},
        geometry=[Polygon(), _cuadrado(0, 0, 10)],
        crs=CRS,
    )
    assert _a_coordenadas(gdf, "tess_id")["tess_id"].tolist() == ["buena"]


# ─── la decisión de qué es barrera ────────────────────────────────────────────
def test_el_peatonal_interno_no_es_barrera():
    """Un pasaje o una escalera atraviesan la manzana; no separan dos tejidos.

    Usarlos como barrera fragmentaría la manzana en astillas sin significado
    morfológico. El test fija la decisión para que un cambio de criterio sea
    deliberado y no un `fclass` que entró de contrabando.
    """
    for interna in ("footway", "steps", "path", "cycleway", "bridleway", "track"):
        assert interna not in VIAS_BARRERA
    for calle in ("residential", "primary", "service", "living_street"):
        assert calle in VIAS_BARRERA


# ─── caché de la tesselación ──────────────────────────────────────────────────
@pytest.fixture
def osm_falso(tmp_path):
    """Un archivo cualquiera que haga de gpkg: la clave solo mira su tamaño y su mtime.

    Sin esto los tests dependerían del gpkg real de infelix, que no existe en el CI —
    y un test de la clave del caché no necesita 1,1 GB para comprobar que discrimina.
    """
    ruta = tmp_path / "peru.gpkg"
    ruta.write_bytes(b"no soy un gpkg")
    return ruta


def test_la_clave_del_cache_cambia_si_cambian_los_insumos(osm_falso):
    """Un caché que no se invalida es peor que no tener caché.

    La clave no hashea el gpkg de 1,1 GB —costaría más que el ahorro— así que tiene que
    reaccionar a todo lo demás que puede mover la tesselación. Si dos escenarios
    distintos comparten clave, una corrida devuelve en silencio el tejido de la otra.
    """
    edificios = gpd.GeoDataFrame(geometry=[_cuadrado(0, 0, 20)], crs=CRS)
    vias = gpd.GeoDataFrame(geometry=[_cuadrado(0, 0, 5)], crs=CRS)
    limite = _cuadrado(-500, -500, 2000)

    def clave(e=edificios, v=vias, lim=limite, osm=osm_falso):
        return loader._clave_tejido(e, v, lim, osm=osm)

    base = clave()
    assert base == clave(), "la clave es determinista"

    mas_edificios = gpd.GeoDataFrame(
        geometry=[_cuadrado(0, 0, 20), _cuadrado(300, 300, 20)], crs=CRS
    )
    assert clave(e=mas_edificios) != base
    assert clave(lim=_cuadrado(-500, -500, 2500)) != base

    # y el propio archivo OSM: si cambia el extracto, el tejido cambia
    osm_falso.write_bytes(b"otro extracto, otro tamano")
    assert clave() != base


def test_la_clave_del_cache_cambia_si_cambia_el_algoritmo(osm_falso):
    """Un caché que solo mira los insumos publica el resultado del algoritmo viejo.

    Es el fallo que motivó el registro canónico de este repo —un número que sobrevive a
    su pipeline— construido dentro del caché. La clave lleva la huella del código de
    `construir_tejido` y la versión de city2graph justamente para que no pueda pasar.
    """
    edificios = gpd.GeoDataFrame(geometry=[_cuadrado(0, 0, 20)], crs=CRS)
    vias = gpd.GeoDataFrame(geometry=[_cuadrado(0, 0, 5)], crs=CRS)
    clave = loader._clave_tejido(edificios, vias, _cuadrado(-500, -500, 2000), osm=osm_falso)

    assert "constructor_sha256" in clave
    assert "city2graph" in clave
    # la huella es del código realmente vigente, no de una constante que alguien olvidará
    import hashlib
    import inspect

    esperado = hashlib.sha256(
        inspect.getsource(loader.construir_tejido).encode("utf-8")
    ).hexdigest()[:16]
    assert clave["constructor_sha256"] == esperado


def test_la_arista_cuyo_borde_compartido_quedo_fuera_de_la_mascara_no_sobrevive():
    """Sin esto, el grado describiría el grafo previo al recorte y el área el posterior.

    Dos celdas de la misma manzana cuyos edificios están lejos: cada una se queda con su
    entorno construido y entre medio hay hueco. Ya no se tocan, así que ya no son
    vecinas — aunque `touched_to` dijera que lo eran antes de recortar.
    """
    celdas = gpd.GeoDataFrame(
        {"tess_id": ["t1", "t2", "t3"]},
        # t1 y t2 se tocan; t3 está separada por un hueco
        geometry=[_cuadrado(0, 0, 100), _cuadrado(100, 0, 100), _cuadrado(500, 0, 100)],
        crs=CRS,
    )
    aristas = pd.DataFrame(
        {"src_tess": ["t1", "t1"], "dst_tess": ["t2", "t3"]}
    )

    vigentes = loader.aristas_vigentes(aristas, celdas)

    assert list(zip(vigentes["src_tess"], vigentes["dst_tess"], strict=True)) == [("t1", "t2")]


def test_la_arista_hacia_una_celda_que_desaparecio_no_sobrevive():
    """Una manzana sin edificación no tiene tejido que conectar."""
    celdas = gpd.GeoDataFrame(
        {"tess_id": ["t1", "t2"]},
        geometry=[_cuadrado(0, 0, 100), _cuadrado(100, 0, 100)],
        crs=CRS,
    )
    aristas = pd.DataFrame({"src_tess": ["t1", "t1"], "dst_tess": ["t2", "borrada"]})

    vigentes = loader.aristas_vigentes(aristas, celdas)

    assert list(vigentes["dst_tess"]) == ["t2"]


def test_la_clave_del_cache_incluye_las_vias_barrera(osm_falso):
    """Cambiar qué cuenta como barrera cambia el tejido, y el caché tiene que enterarse."""
    edificios = gpd.GeoDataFrame(geometry=[_cuadrado(0, 0, 20)], crs=CRS)
    vias = gpd.GeoDataFrame(geometry=[_cuadrado(0, 0, 5)], crs=CRS)
    clave = loader._clave_tejido(edificios, vias, _cuadrado(-500, -500, 2000), osm=osm_falso)
    assert clave["vias_barrera"] == sorted(VIAS_BARRERA)


# ─── la máscara de área construida: el hueco hay que construirlo ──────────────
def test_la_mascara_recorta_la_celda_que_se_estira_sobre_el_vacio():
    """El fallo de inwatch-72j en miniatura.

    La tesselación encerrada no deja huecos: la celda del único edificio se estira sobre
    todo el límite. Sin máscara, ese vacío se reporta como tejido; con máscara, la celda
    se queda con lo que su edificio sostiene y el resto vuelve a ser hueco.
    """
    edificios = gpd.GeoDataFrame(geometry=[_cuadrado(0, 0, 20)], crs=CRS)
    grilla = gpd.GeoDataFrame({"h3_index": ["h"]}, geometry=[_cuadrado(-500, -500, 2000)], crs=CRS)
    # una sola celda gigante, como la que devuelve `morphological_graph` sobre desierto
    celdas = gpd.GeoDataFrame(
        {"tess_id": ["t1"], "enclosure_index": [0]},
        geometry=[_cuadrado(-500, -500, 2000)],
        crs=CRS,
    )
    mascara = mascara_construida(edificios, grilla, radio=100.0)
    recortada, sin_edificio = recortar_a_construido(celdas, mascara)

    assert sin_edificio == 0, "la celda tiene su edificio semilla: no puede desaparecer"
    assert len(recortada) == 1
    assert recortada.geometry.area.iloc[0] < celdas.geometry.area.iloc[0] / 10
    # el edificio sigue dentro de su celda; lo que se fue es el vacío de alrededor
    assert recortada.geometry.iloc[0].contains(edificios.geometry.iloc[0])


def test_la_celda_de_una_manzana_sin_edificios_desaparece_entera():
    """El caso que tumbó la primera corrida con máscara, y que resultó ser el hallazgo.

    La tesselación encerrada no reparte solo el espacio *entre* edificios: también le da
    una celda a la manzana cerrada que no tiene ninguno. Esas celdas son el hueco. Tienen
    que salir de la tabla, no quedarse con área cero ni abortar el loader.
    """
    edificios = gpd.GeoDataFrame(geometry=[_cuadrado(0, 0, 20)], crs=CRS)
    grilla = gpd.GeoDataFrame({"h3_index": ["h"]}, geometry=[_cuadrado(-500, -500, 3000)], crs=CRS)
    celdas = gpd.GeoDataFrame(
        {"tess_id": ["con_edificio", "desierto"], "enclosure_index": [0, 1]},
        # la segunda está lejísimos de cualquier edificio
        geometry=[_cuadrado(-50, -50, 200), _cuadrado(2000, 2000, 400)],
        crs=CRS,
    )
    recortada, sin_edificio = recortar_a_construido(
        celdas, mascara_construida(edificios, grilla, radio=100.0)
    )

    assert sin_edificio == 1
    assert list(recortada["tess_id"]) == ["con_edificio"]


def test_el_radio_de_la_mascara_es_la_perilla_del_experimento():
    """Subirlo agranda el área construida. Si no lo hiciera, no sería un parámetro."""
    edificios = gpd.GeoDataFrame(geometry=[_cuadrado(0, 0, 20)], crs=CRS)
    grilla = gpd.GeoDataFrame({"h3_index": ["h"]}, geometry=[_cuadrado(-500, -500, 2000)], crs=CRS)
    chica = mascara_construida(edificios, grilla, radio=50.0).geometry.area.sum()
    grande = mascara_construida(edificios, grilla, radio=200.0).geometry.area.sum()
    assert grande > chica


def test_la_mascara_troceada_cubre_lo_mismo_que_sin_trocear():
    """El troceado por la grilla es por velocidad; la geometría resultante es la misma."""
    # el primero queda a caballo del borde x=500, así que su buffer se parte en dos
    edificios = gpd.GeoDataFrame(
        geometry=[_cuadrado(450, 100, 20), _cuadrado(900, 100, 20)], crs=CRS
    )
    # dos hexágonos sintéticos contiguos: la máscara cruza el borde entre ellos
    grilla = gpd.GeoDataFrame(
        {"h3_index": ["a", "b"]},
        geometry=[_cuadrado(-500, -500, 1000), _cuadrado(500, -500, 1000)],
        crs=CRS,
    )
    troceada = mascara_construida(edificios, grilla, radio=100.0)
    entera = edificios.geometry.buffer(100.0).union_all()
    recorte = entera.intersection(grilla.geometry.union_all())

    assert len(troceada) > 1, "la máscara debe partirse en pedazos por hexágono"
    assert troceada.geometry.area.sum() == pytest.approx(recorte.area)
    assert troceada.geometry.union_all().area == pytest.approx(recorte.area)


def test_desolapar_deja_de_contar_dos_veces_el_suelo_disputado():
    """Σ de áreas > área de la unión es masa inventada, y la tabla la repartiría."""
    a = _cuadrado(0, 0, 100)          # 10 000 m²
    b = _cuadrado(50, 0, 100)         # 10 000 m², solapa 5 000 m² con `a`
    celdas = gpd.GeoDataFrame({"tess_id": ["t1", "t2"]}, geometry=[a, b], crs=CRS)
    assert celdas.geometry.area.sum() == pytest.approx(20_000)

    partido, disputada = desolapar(celdas)

    assert disputada == pytest.approx(5_000)
    assert partido.geometry.area.sum() == pytest.approx(15_000)
    assert partido.geometry.union_all().area == pytest.approx(15_000)
    # gana el tess_id menor, y está declarado: `t1` conserva su área entera
    assert partido.set_index("tess_id").geometry["t1"].area == pytest.approx(10_000)


def test_desolapar_atrapa_la_celda_contenida_en_otra():
    """El caso que se escapó en la primera versión y dejó 7 hexágonos sobre 1.

    `overlaps` de shapely exige que ninguna geometría contenga a la otra, así que una
    celda **dentro** de otra no era «overlaps» y su área se contaba dos veces enteras.
    """
    grande = _cuadrado(0, 0, 100)      # 10 000 m²
    chica = _cuadrado(25, 25, 50)      # 2 500 m², enteramente dentro de `grande`
    celdas = gpd.GeoDataFrame({"tess_id": ["t1", "t2"]}, geometry=[grande, chica], crs=CRS)

    partido, disputada = desolapar(celdas)

    assert disputada == pytest.approx(2_500)
    assert partido.geometry.area.sum() == pytest.approx(10_000)
    assert partido.geometry.union_all().area == pytest.approx(10_000)
    # gana el tess_id menor: `t1` queda entero y `t2` se vacía
    assert partido.set_index("tess_id").geometry["t1"].area == pytest.approx(10_000)


def test_desolapar_no_toca_celdas_que_solo_se_tocan():
    """Dos celdas contiguas comparten borde y no área. Recortarlas sería un bug."""
    celdas = gpd.GeoDataFrame(
        {"tess_id": ["t1", "t2"]},
        geometry=[_cuadrado(0, 0, 100), _cuadrado(100, 0, 100)],
        crs=CRS,
    )
    partido, disputada = desolapar(celdas)
    assert disputada == 0.0
    assert partido.geometry.area.sum() == pytest.approx(20_000)


# ─── artefactos reales ────────────────────────────────────────────────────────
@pytest.fixture
def artefactos():
    """Salida real del loader; se salta sola si `data/` no está poblado."""
    celdas = loader.OUT / "tejido_celdas.parquet"
    corr = loader.OUT / "correspondencia_h3_tejido.parquet"
    if not (celdas.exists() and corr.exists()):
        pytest.skip(f"faltan artefactos en {loader.OUT}; corre el loader")
    return pd.read_parquet(celdas), pd.read_parquet(corr)


@pytest.mark.needs_data
def test_artefactos_cumplen_el_contrato_de_unidades(artefactos):
    """Sobre la salida real: clave declarada, sin geometría, y masa conservada."""
    celdas, corr = artefactos

    assert "tess_id" in celdas and celdas["tess_id"].is_unique
    assert not any(c in celdas.columns for c in ("geometry", "geometry_wkb"))
    assert (celdas["grado"] >= 0).all()

    suma = corr.groupby("tess_id")["frac_tess"].sum()
    completas = suma[suma >= 1.0 - 1e-6]
    assert not completas.empty
    assert (completas - 1.0).abs().max() < 1e-6

    # Toda celda de la correspondencia existe en la tabla de celdas: la tabla no puede
    # repartir masa hacia una unidad que no declaró.
    assert set(corr["tess_id"]) <= set(celdas["tess_id"])


@pytest.mark.needs_data
def test_ningun_hexagono_real_queda_cubierto_mas_de_una_vez(artefactos):
    """El invariante que faltaba, y por eso inwatch-72j llegó hasta la emisión.

    `Σ frac_h3 ≤ 1` se verificaba solo sobre geometría sintética, donde se cumplía
    siempre. Sobre el artefacto real no: 46 hexágonos lo superaban, el peor con 1,0683,
    porque las celdas de la tesselación se solapaban. Un hexágono cubierto al 106 % es
    suelo contado dos veces, y cualquier reparto con esta tabla inventaría masa.
    """
    _, corr = artefactos
    cobertura = corr.groupby("h3_index")["frac_h3"].sum()
    peor = cobertura.max()
    assert peor <= 1.0 + 1e-6, (
        f"{int((cobertura > 1.0 + 1e-6).sum())} hexágonos cubiertos más de una vez "
        f"(peor: {peor:.4f})"
    )


@pytest.mark.needs_data
def test_el_artefacto_real_deja_hueco_donde_no_hay_edificacion(artefactos):
    """Que existan hexágonos sin tejido es el hallazgo, no un faltante.

    Con la tesselación encerrada sin recortar, esto daba cero por construcción y la
    ausencia de dato se dibujaba como ciudad. Si vuelve a dar cero, la máscara dejó de
    aplicarse y el mapa volvió a mentir en la dirección peligrosa.
    """
    _, corr = artefactos
    cobertura = corr.groupby("h3_index")["frac_h3"].sum()
    assert (cobertura < 1.0).any(), "ningún hexágono queda parcialmente cubierto"
    assert cobertura.median() < 1.0
