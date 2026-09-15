"""Contraste de la betweenness con la jerarquía que OSM declara (bead ``inwatch-92d.5``).

La betweenness dice qué tramos concentran el flujo **potencial**; el atributo ``highway``
dice cuáles la comunidad de OSM considera vías principales. Este módulo mide cuánto
coinciden y, sobre todo, **dónde no**: los dos desacuerdos son el hallazgo, no el ruido.

Tres decisiones, cada una por un error que evita:

- **La tasa base va siempre pegada a la precisión.** Un top-k con 20 % de arteriales no
  significa nada si el 20 % de la red entera es arterial: sería lo mismo que sortear
  tramos al azar. Por eso ``precision_en_k`` devuelve también la tasa base y el exceso
  sobre ella, y la curva las lleva en columnas propias.
- **El ``busway`` es su propia clase, no una vía local.** El corredor exclusivo del
  Metropolitano entra al grafo ``drive`` aunque OSM lo marque ``access=no`` (decisión
  registrada en ``inwatch-92d.8``: se mantiene y se declara). Dejarlo caer en la bolsa
  "local" lo convertiría en el primer "corredor de hecho que la clasificación no
  reconoce", cuando es un artefacto del filtro de descarga.
- **Nada acá habla de tránsito observado.** No hay aforos. Un tramo con betweenness alta
  es un tramo por el que pasarían muchos caminos mínimos, no un tramo por el que pasan
  muchos vehículos.

Las funciones son puras y operan sobre tablas; ``main()`` es la única que lee artefactos
y emite al registro canónico.

    uv run python experiments/corredores-criticos/arterias.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SLUG = "corredores-criticos"
VARIANTE = "area_a_drive"
OUT = Path(__file__).resolve().parents[2] / "data" / "silver" / SLUG
GRAPHML = "area_a_drive.graphml"
PESOS = ("length", "travel_time")
TOP = 100
# Escalera de k para la curva: densa abajo, porque es donde la precisión se mueve, y
# rala arriba, donde ya converge a la tasa base. Los que no caben en la red se descartan.
KS_CURVA = (10, 25, 50, 100, 250, 500, 1000, 2500)
# Umbral del segundo desacuerdo: arterial declarada por debajo de la mediana de la red.
PERCENTIL_BAJO = 50.0

# La jerarquía como dato explícito y no como una lista suelta dentro de una función:
# es la definición que el artículo tiene que citar, y cambiarla cambia cada cifra de acá.
JERARQUIA_OSM: dict[str, tuple[str, ...]] = {
    "arterial": ("motorway", "trunk", "primary",
                 "motorway_link", "trunk_link", "primary_link"),
    "intermedia": ("secondary", "secondary_link"),
    # Ver el docstring del módulo y el bead inwatch-92d.8: clase aparte, nunca "local".
    "busway": ("busway",),
}
CLASE_LOCAL = "local"
CLASE_SIN_DATO = "sin_dato"
CLASE_ARTERIAL = "arterial"
CLASE_BUSWAY = "busway"

_DE_TIPO_A_CLASE: dict[str, str] = {
    tipo: clase for clase, tipos in JERARQUIA_OSM.items() for tipo in tipos
}


def _tipo(valor) -> str | None:
    """Normaliza un ``highway`` de osmnx: listas al primer elemento, vacío a ``None``."""
    if isinstance(valor, list | tuple):
        valor = valor[0] if len(valor) else None
    if valor is None or not isinstance(valor, str):
        return None
    limpio = valor.strip().lower()
    return limpio or None


def clase_osm(valor) -> str:
    """Clase de jerarquía de un ``highway``. Lo no declarado no se disfraza de local."""
    tipo = _tipo(valor)
    if tipo is None:
        return CLASE_SIN_DATO
    return _DE_TIPO_A_CLASE.get(tipo, CLASE_LOCAL)


def clasificar(t: pd.DataFrame) -> pd.DataFrame:
    """Añade ``clase`` y ``arterial`` a una tabla de tramos con ``highway``."""
    if "highway" not in t:
        raise ValueError("la tabla de tramos no tiene columna 'highway'")
    salida = t.copy()
    salida["clase"] = [clase_osm(v) for v in t["highway"]]
    salida["arterial"] = salida["clase"] == CLASE_ARTERIAL
    return salida


def tasa_base(t: pd.DataFrame) -> dict[str, float]:
    """Qué parte de la red entera es arterial declarada, por tramos y por longitud.

    Las dos, porque no dicen lo mismo: una avenida es varias veces más larga que un
    pasaje, así que el % de kilómetros arteriales supera al % de tramos arteriales.
    Sin esta cifra, una precisión@k no se puede leer.
    """
    if "largo_m" not in t:
        raise ValueError("la tabla de tramos no tiene columna 'largo_m'")
    if t.empty:
        raise ValueError("tabla de tramos vacía: no hay tasa base que medir")
    largo_total = float(t["largo_m"].sum())
    return {
        "n_tramos": int(len(t)),
        "n_arteriales": int(t["arterial"].sum()),
        "pct_tramos": 100 * float(t["arterial"].mean()),
        "pct_largo": 100 * float(t.loc[t["arterial"], "largo_m"].sum()) / largo_total,
    }


# ─── la tabla de partida ──────────────────────────────────────────────────────
COLUMNAS_OSM = ("tramo_id", "name", "highway", "largo_m")


def unir(tramos: pd.DataFrame, bc: pd.DataFrame, *, pesos: tuple[str, ...] = PESOS
         ) -> pd.DataFrame:
    """Une los atributos OSM del tramo con su betweenness, y clasifica.

    Falla si algún tramo se queda sin betweenness en vez de dejar el ``NaN`` del
    ``left join``: un tramo sin cifra se ordena al fondo y saldría como "arteria sin
    flujo potencial", que es justo una de las conclusiones que este módulo reporta.
    """
    faltan = [c for c in COLUMNAS_OSM if c not in tramos]
    if faltan:
        raise ValueError(f"la tabla de tramos no tiene {faltan}")
    columnas_bc = [f"bc_{p}" for p in pesos]
    faltan_bc = [c for c in columnas_bc if c not in bc]
    if faltan_bc:
        raise ValueError(f"la tabla de betweenness no tiene {faltan_bc}")

    # Sin la geometría del GeoDataFrame: el contrato de unidades la deja fuera de las
    # tablas de features y se reconstruye al dibujar, desde el tramo_id.
    u = tramos[[*COLUMNAS_OSM]].merge(
        bc[["tramo_id", *columnas_bc]], on="tramo_id", how="left", validate="one_to_one"
    )
    sin_bc = u.loc[u[columnas_bc].isna().any(axis=1), "tramo_id"]
    if len(sin_bc):
        raise ValueError(f"{len(sin_bc)} tramos sin betweenness, p. ej. {list(sin_bc[:3])}")
    return clasificar(u)


# ─── orden, precisión@k y curva ───────────────────────────────────────────────
def ordenar(t: pd.DataFrame, *, peso: str) -> pd.DataFrame:
    """Tramos de mayor a menor betweenness, con ``rango`` y ``percentil_bc``.

    El ``rango`` empata (``method="min"``): dos tramos con la misma betweenness están
    igual de arriba y fingir lo contrario inventaría una diferencia. El **orden de las
    filas** sí se desempata por ``tramo_id``, para que el top-k no dependa de cómo vino
    ordenado el parquet. ``percentil_bc`` es ascendente: 100 es la más alta de la red.
    """
    columna = f"bc_{peso}"
    if columna not in t:
        raise ValueError(f"la tabla de tramos no tiene columna '{columna}'")
    if "tramo_id" not in t:
        raise ValueError("la tabla de tramos no tiene columna 'tramo_id'")
    o = t.copy()
    o["rango"] = o[columna].rank(ascending=False, method="min").astype(int)
    o["percentil_bc"] = 100 * o[columna].rank(ascending=True, pct=True, method="average")
    o = o.sort_values([columna, "tramo_id"], ascending=[False, True], kind="mergesort")
    return o.reset_index(drop=True)


def precision_en_k(t: pd.DataFrame, *, peso: str, k: int) -> dict[str, float]:
    """Qué fracción del top-k por betweenness es arterial declarada, contra la tasa base.

    Devuelve las tres cifras juntas a propósito. La precisión sola no se puede leer: un
    40 % es un hallazgo si la red es 8 % arterial y es nada si la red es 40 % arterial.
    El ``lift`` (precisión / tasa base) es la lectura directa — 1,0 significa que el
    top-k es indistinguible de sortear tramos al azar — y queda en ``NaN``, no en cero ni
    en infinito, cuando no hay ni una arterial declarada contra la cual comparar.
    """
    o = ordenar(t, peso=peso)
    if not 1 <= k <= len(o):
        raise ValueError(f"k={k} fuera de rango: la red tiene {len(o)} tramos")
    base = tasa_base(t)
    n_arteriales = int(o.head(k)["arterial"].sum())
    precision = 100 * n_arteriales / k
    return {
        "peso": peso,
        "k": int(k),
        "n_arteriales": n_arteriales,
        "precision": precision,
        "tasa_base": base["pct_tramos"],
        "exceso_pp": precision - base["pct_tramos"],
        "lift": precision / base["pct_tramos"] if base["pct_tramos"] > 0 else float("nan"),
    }


def curva_coincidencia(
    t: pd.DataFrame, *, pesos: tuple[str, ...] = PESOS, ks: tuple[int, ...] = KS_CURVA
) -> pd.DataFrame:
    """Precisión@k en función de k, para cada peso: la tabla lista para graficar.

    Los ``k`` mayores que la red se descartan en vez de recortarse a ``n``: un punto en
    ``k = n`` ya está en la curva y repetirlo con otra etiqueta dibujaría una meseta que
    no existe.
    """
    cabe = sorted({int(k) for k in ks if 1 <= k <= len(t)})
    if not cabe:
        raise ValueError(f"ningún k de {tuple(ks)} cabe en una red de {len(t)} tramos")
    filas = [precision_en_k(t, peso=peso, k=k) for peso in pesos for k in cabe]
    return pd.DataFrame(filas)[
        ["peso", "k", "n_arteriales", "precision", "tasa_base", "exceso_pp", "lift"]
    ]


# ─── los dos desacuerdos ──────────────────────────────────────────────────────
COLUMNAS_DESACUERDO = ("peso", "tramo_id", "name", "highway", "clase",
                       "bc", "percentil_bc", "rango")


def _desacuerdo(o: pd.DataFrame, *, peso: str) -> pd.DataFrame:
    """Recorta un subconjunto ya ordenado a las columnas con que se lee un desacuerdo."""
    d = o.copy()
    d["peso"] = peso
    d["bc"] = d[f"bc_{peso}"]
    for campo in ("name", "highway"):
        if campo not in d:
            d[campo] = None
    return d[[*COLUMNAS_DESACUERDO]].reset_index(drop=True)


def corredores_no_declarados(t: pd.DataFrame, *, peso: str, k: int = TOP) -> pd.DataFrame:
    """Tramos del top-k por betweenness que OSM **no** declara arteriales.

    Son corredores de hecho: la red los usa aunque la jerarquía declarada no los
    reconozca. La ``clase`` va en la tabla porque los tres casos se leen distinto — una
    ``secondary`` que se comporta como arteria, una calle local que absorbe tránsito de
    paso, y un ``busway``, que no es ninguna de las dos sino el corredor exclusivo del
    Metropolitano colándose en el grafo ``drive`` (ver ``inwatch-92d.8``).
    """
    o = ordenar(t, peso=peso)
    if not 1 <= k <= len(o):
        raise ValueError(f"k={k} fuera de rango: la red tiene {len(o)} tramos")
    top = o.head(k)
    return _desacuerdo(top[~top["arterial"]], peso=peso)


def arterias_de_baja_betweenness(
    t: pd.DataFrame, *, peso: str, percentil_maximo: float = PERCENTIL_BAJO
) -> pd.DataFrame:
    """Arterias declaradas que quedan bajo un percentil de betweenness, la peor primero.

    El otro lado del desacuerdo: vías que OSM jerarquiza como principales y por las que
    casi ningún camino mínimo pasa. Es flujo **potencial**, así que esto no dice que la
    avenida esté vacía: dice que la topología de la red no la necesita como paso.
    """
    o = ordenar(t, peso=peso)
    bajas = o[o["arterial"] & (o["percentil_bc"] <= percentil_maximo)]
    bajas = bajas.sort_values([f"bc_{peso}", "tramo_id"], ascending=[True, True],
                              kind="mergesort")
    return _desacuerdo(bajas, peso=peso)


def resumen_busway(t: pd.DataFrame, *, peso: str, k: int = TOP) -> dict:
    """Cuánto pesa el corredor del Metropolitano en el top-k, dicho aparte y no diluido.

    ``encabeza`` responde la pregunta incómoda: ¿el tramo más central de toda la red es
    una vía por la que un auto particular no puede circular?
    """
    o = ordenar(t, peso=peso)
    if not 1 <= k <= len(o):
        raise ValueError(f"k={k} fuera de rango: la red tiene {len(o)} tramos")
    es_busway = o["clase"] == CLASE_BUSWAY
    return {
        "peso": peso,
        "k": int(k),
        "n_busway": int(es_busway.sum()),
        "n_en_top": int(es_busway.head(k).sum()),
        "encabeza": bool(es_busway.iloc[0]),
    }


def tabla_por_tramo(t: pd.DataFrame, *, pesos: tuple[str, ...] = PESOS) -> pd.DataFrame:
    """La tabla del artefacto: clase, betweenness, rango y percentil por peso.

    Sin geometría, como pide el contrato de unidades: se reconstruye al dibujar desde el
    ``tramo_id``. Sale ordenada por el primer peso, que es como se lee un ranking.
    """
    salida = t.copy()
    for peso in pesos:
        o = ordenar(t, peso=peso).set_index("tramo_id")
        salida[f"rango_{peso}"] = salida["tramo_id"].map(o["rango"])
        salida[f"percentil_{peso}"] = salida["tramo_id"].map(o["percentil_bc"])
    columnas = ["tramo_id", "name", "highway", "clase", "arterial", "largo_m"]
    for peso in pesos:
        columnas += [f"bc_{peso}", f"rango_{peso}", f"percentil_{peso}"]
    salida = salida.sort_values([f"bc_{pesos[0]}", "tramo_id"], ascending=[False, True],
                                kind="mergesort")
    return salida[columnas].reset_index(drop=True)


# ─── las cifras portantes ─────────────────────────────────────────────────────
def cifras(t: pd.DataFrame, *, k: int = TOP,
           percentil_maximo: float = PERCENTIL_BAJO) -> dict[str, tuple[float, str, str]]:
    """``clave canon → (valor, unidad, estimador)``. Es lo que ``main()`` emite.

    Vive acá y no dentro de ``main()`` para que las cifras portantes se puedan probar
    con una red sintética sin tocar el registro: el error que el registro canónico
    existe para evitar empieza siempre por un número que nadie verificó.

    El **lift** no se emite, y no es un olvido: no pertenece a ninguna de las dos
    familias con policy (no es un porcentaje ni un conteo) y estrenar una familia es una
    decisión humana — la policy es hand-written. Va en la tabla de la curva, junto al
    exceso en puntos porcentuales, que sí es un porcentaje y sí se emite.
    """
    base = tasa_base(t)
    jerarquia = "arterial = motorway/trunk/primary y sus _link"
    salida: dict[str, tuple[float, str, str]] = {
        "corredores.pct.arterial_declarada_tramos": (
            base["pct_tramos"], "% de tramos", f"tasa base de la red; {jerarquia}"),
        "corredores.pct.arterial_declarada_largo": (
            base["pct_largo"], "% de longitud", f"tasa base ponderada por largo_m; {jerarquia}"),
        "corredores.conteo.tramos_clasificados": (
            base["n_tramos"], "tramos no dirigidos", "tramos con betweenness y highway"),
        "corredores.conteo.arterias_declaradas": (
            base["n_arteriales"], "tramos no dirigidos", jerarquia),
    }
    for peso in PESOS:
        p = precision_en_k(t, peso=peso, k=k)
        bajas = arterias_de_baja_betweenness(t, peso=peso, percentil_maximo=percentil_maximo)
        busway = resumen_busway(t, peso=peso, k=k)
        estimador = f"top-{k} de tramos por bc_{peso}; {jerarquia}"
        salida[f"corredores.pct.precision_top{k}_{peso}"] = (
            p["precision"], f"% del top-{k}", estimador)
        salida[f"corredores.pct.exceso_sobre_base_top{k}_{peso}"] = (
            p["exceso_pp"], "puntos porcentuales sobre la tasa base", estimador)
        salida[f"corredores.pct.arterias_bajo_mediana_{peso}"] = (
            100 * len(bajas) / base["n_arteriales"] if base["n_arteriales"] else float("nan"),
            "% de arterias declaradas",
            f"percentil de bc_{peso} ≤ {percentil_maximo:g} sobre la red entera")
        salida[f"corredores.conteo.busway_en_top{k}_{peso}"] = (
            busway["n_en_top"], "tramos no dirigidos",
            f"highway=busway dentro del top-{k} por bc_{peso}")
    return salida


# ─── ejecución ────────────────────────────────────────────────────────────────
BETWEENNESS = "betweenness_tramos.parquet"
ARTEFACTOS = {
    "clasificacion": "arterias_clasificacion.parquet",
    "curva": "arterias_curva_coincidencia.parquet",
    "no_declarados": "arterias_no_declarados.parquet",
    "baja_betweenness": "arterias_baja_betweenness.parquet",
}


def main() -> None:
    from inwatch import canon
    from inwatch.unidades import red_vial

    rutas = {"grafo": OUT / GRAPHML, "bc": OUT / BETWEENNESS}
    for quien, ruta in (("loader.py", rutas["grafo"]), ("centralidad.py", rutas["bc"])):
        if not ruta.exists():
            raise FileNotFoundError(f"falta {ruta}: corre antes experiments/{SLUG}/{quien}")

    G, _ = red_vial.cargar(rutas["grafo"])
    t = unir(red_vial.tramos(G), pd.read_parquet(rutas["bc"]))

    tablas = {
        "clasificacion": tabla_por_tramo(t),
        "curva": curva_coincidencia(t),
        "no_declarados": pd.concat(
            [corredores_no_declarados(t, peso=p) for p in PESOS], ignore_index=True),
        "baja_betweenness": pd.concat(
            [arterias_de_baja_betweenness(t, peso=p) for p in PESOS], ignore_index=True),
    }

    for clave, (valor, unidad, estimador) in cifras(t).items():
        canon.emit(clave, float(valor), variant=VARIANTE, unit=unidad, estimator=estimador,
                   inputs=list(rutas.values()), script=__file__)

    OUT.mkdir(parents=True, exist_ok=True)
    for nombre, tabla in tablas.items():
        tabla.to_parquet(OUT / ARTEFACTOS[nombre], index=False)

    base = tasa_base(t)
    print(f"  → {OUT}  ({base['n_tramos']:,} tramos · "
          f"{base['n_arteriales']:,} arteriales declaradas, {base['pct_tramos']:.1f} %)")
    for peso in PESOS:
        p = precision_en_k(t, peso=peso)
        bus = resumen_busway(t, peso=peso)
        print(f"     {peso:>11}: precisión@{TOP} {p['precision']:.1f} % "
              f"(lift ×{p['lift']:.2f}) · {bus['n_en_top']} busway en el top"
              f"{' · encabeza el ranking' if bus['encabeza'] else ''}")


if __name__ == "__main__":
    main()
