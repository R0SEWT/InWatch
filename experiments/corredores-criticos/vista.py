"""Lógica de presentación de `corredores-criticos`: qué entra al mapa y con qué color.

Acompaña a ``notebook.py``, que solo lee artefactos y dibuja. Nada de acá calcula desde
datos crudos: todo opera sobre las tablas que ya dejaron ``centralidad.py`` y ``capas.py``.

**Por qué es un módulo aparte y no celdas del notebook.** El CI corre
``uv sync --extra geo``: no instala ``marimo``. Si esta lógica viviera dentro del
notebook, su test se saltaría entero en CI — y un test que se salta no verifica nada,
que es peor que uno rojo (``CLAUDE.md``, sección *Convenciones*). Acá no se importa
marimo, ni matplotlib, ni geopandas: solo pandas y numpy, así que el filtro del top, la
marca de "sin dato" y la normalización del color se verifican en cada push.

Dos decisiones que el código hace explícitas, cada una por un error que evita:

- **Un tramo sin ``highway`` no es un tramo local.** Es la regla dura del repo dentro de
  una función de tres líneas: si la ausencia cayera en la clase más baja de la jerarquía,
  el mapa afirmaría "vía menor" donde OSM no dijo nada.
- **Un ``NaN`` no se normaliza a cero.** Pintar el hueco con el color del mínimo es
  exactamente *sin datos = seguro*, la afirmación que este repo existe para no hacer.
  El cero medido sí es un dato: ``a_tramos`` deja en 0 las paralelas que ningún camino
  mínimo usa, y eso se dibuja como lo que es.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

import numpy as np
import pandas as pd

# ─── jerarquía declarada por OSM ──────────────────────────────────────────────
# El enunciado pide contrastar los corredores calculados contra las vías que OSM ya
# declara arteriales. Los `_link` van con su clase: una rampa de autopista es parte de
# la autopista, y dejarla en "local" partiría el corredor en el dibujo.
ARTERIAL = frozenset(
    {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"}
)
SECUNDARIA = frozenset(
    {"secondary", "secondary_link", "tertiary", "tertiary_link"}
)
# El corredor exclusivo del Metropolitano. Es su propia clase y no "local" porque es la
# limitación declarada del experimento: OSM lo marca `access=no` y aun así está en el
# grafo. Verlo en el mapa vale más que leerlo en una nota.
BUSWAY = "busway"
SIN_DECLARAR = "sin declarar"
CLASES = ("arterial", "secundaria", "local", BUSWAY, SIN_DECLARAR)

GAMMA_BC = 0.4
"""Compresión de la cola al llevar betweenness a color.

La betweenness de una red vial es de cola pesada: unas decenas de tramos se llevan
casi todo y el resto se aplasta contra el mínimo. Con gamma 1 el mapa sale negro sobre
blanco y no muestra estructura. El gamma es **solo de presentación** — la barra de
color lleva los valores reales en su posición transformada, así que el eje no miente.
"""


def _vacio(valor) -> bool:
    if valor is None:
        return True
    if isinstance(valor, float) and math.isnan(valor):
        return True
    return isinstance(valor, str) and not valor.strip()


def clase_vial(highway) -> str:
    """Clase de la jerarquía OSM de un tramo. Sin ``highway`` es ``SIN_DECLARAR``."""
    if _vacio(highway):
        return SIN_DECLARAR
    h = str(highway).strip().lower()
    if h in ARTERIAL:
        return "arterial"
    if h in SECUNDARIA:
        return "secundaria"
    if h == BUSWAY:
        return BUSWAY
    return "local"


def clasificar(tramos: pd.DataFrame, columna: str = "highway") -> pd.Series:
    """Una clase por tramo, en el orden de la tabla."""
    if columna not in tramos:
        raise KeyError(f"la tabla de tramos no trae la columna '{columna}'")
    return tramos[columna].map(clase_vial).rename("clase")


# ─── sin dato ≠ valor bajo ────────────────────────────────────────────────────
def sin_dato(tabla: pd.DataFrame, columna: str) -> pd.Series:
    """Máscara de las filas sin medición en ``columna``. Un 0 medido no entra acá."""
    if columna not in tabla:
        raise KeyError(f"la tabla no trae la columna '{columna}'")
    return tabla[columna].isna().rename("sin_dato")


# ─── el top del ranking ───────────────────────────────────────────────────────
def tabla_top(tabla: pd.DataFrame, *, columna: str, clave: str, top: int) -> pd.DataFrame:
    """Las ``top`` filas de mayor ``columna``, numeradas desde 1 y sin las que no tienen dato.

    Desempata por ``clave`` ascendente, igual que ``capas.ranking``: con betweenness
    iguales, ordenar solo por valor deja el resultado a merced del orden de las filas del
    parquet y el top cambiaría entre corridas.

    Se **recorta** a las filas disponibles en vez de fallar: acá el ``top`` lo mueve un
    deslizador y pedir más de lo que hay no es un error del usuario.
    """
    if columna not in tabla:
        raise KeyError(f"la tabla no trae la columna '{columna}'")
    if clave not in tabla:
        raise KeyError(f"la tabla no trae la clave '{clave}'")
    if top < 1:
        raise ValueError(f"top={top}: hace falta pedir al menos una fila")
    con_dato = tabla[tabla[columna].notna()]
    orden = con_dato.sort_values([columna, clave], ascending=[False, True])
    salida = orden.head(int(top)).copy()
    salida["rango"] = range(1, len(salida) + 1)
    return salida.reset_index(drop=True)


# ─── normalización de color ───────────────────────────────────────────────────
def normalizar(valores, *, gamma: float = 1.0) -> np.ndarray:
    """Lleva ``valores`` a [0, 1] conservando los huecos como ``NaN``.

    Con todos los valores iguales devuelve 0,5 y no 0: "no hay variación" no es "todos
    están en el mínimo", y un mapa entero del color más pálido diría lo segundo.
    """
    if gamma <= 0:
        raise ValueError(f"gamma={gamma}: tiene que ser positivo")
    v = np.asarray(pd.Series(valores), dtype=float)
    finitos = np.isfinite(v)
    salida = np.full(v.shape, np.nan, dtype=float)
    if not finitos.any():
        return salida
    lo = float(v[finitos].min())
    hi = float(v[finitos].max())
    if hi == lo:
        salida[finitos] = 0.5
        return salida
    salida[finitos] = ((v[finitos] - lo) / (hi - lo)) ** gamma
    return salida


# ─── barra de escala ──────────────────────────────────────────────────────────
def longitud_barra(extension_m: float, *, fraccion: float = 0.25) -> float:
    """Longitud redonda (1, 2 o 5 × 10ⁿ metros) que entra en ``fraccion`` del ancho.

    El mapa se dibuja en EPSG:32718, donde una unidad del eje **es** un metro: la barra
    se mide en coordenadas de datos y no hay factor que estimar.
    """
    if extension_m <= 0:
        raise ValueError(f"extensión={extension_m}: el mapa no tiene ancho que medir")
    objetivo = fraccion * extension_m
    exponente = math.floor(math.log10(objetivo))
    for mantisa in (5, 2, 1):
        candidata = mantisa * 10.0**exponente
        if candidata <= objetivo:
            return candidata
    return 10.0**exponente  # inalcanzable: 1×10^⌊log10⌋ siempre entra


# ─── capas de puntos sobre el ranking ─────────────────────────────────────────
def nombres_cercanos(claves: Iterable[str], capas: pd.DataFrame, *, clave: str) -> dict[str, str]:
    """Para cada clave pedida, los nombres de capa cercanos, de la más próxima a la más lejana.

    Devuelve cadena vacía —no la de otra clave, no un nombre inventado— donde no hay
    ninguna capa cerca. El artefacto de capas solo trae los pares que caen dentro del
    radio, así que la ausencia de fila es la respuesta.
    """
    claves = [str(k) for k in claves]
    salida = {k: "" for k in claves}
    if capas.empty:
        return salida
    faltan = {clave, "nombre"} - set(capas.columns)
    if faltan:
        raise KeyError(f"la tabla de capas no trae {sorted(faltan)}")
    orden = ["dist_m", "nombre"] if "dist_m" in capas else ["nombre"]
    cerca = capas[capas[clave].astype(str).isin(salida)].sort_values(orden)
    for k, grupo in cerca.groupby(cerca[clave].astype(str), sort=False):
        salida[k] = " · ".join(dict.fromkeys(grupo["nombre"].astype(str)))
    return salida


def cobertura(top: Iterable[str], con_capa: set[str]) -> float:
    """Fracción del top que tiene una capa cerca. Falla con un top vacío.

    Devolver 0 ahí diría "ninguno tiene estación cerca" cuando en realidad no se midió
    nada — el mismo error que pintar de verde una celda sin registro.
    """
    top = [str(k) for k in top]
    if not top:
        raise ValueError("el top está vacío: no hay nada de lo que medir cobertura")
    return sum(1 for k in top if k in con_capa) / len(top)
