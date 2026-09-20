"""Catálogo de fuentes: cada dataset por nombre, con procedencia.

Uso desde un loader::

    from inwatch import fuentes

    admin = fuentes.ruta("h3_admin")                  # Path, sin calcular sha
    r = fuentes.resolver("denuncias_lima")            # ruta + origen + sha256
    canon.emit(..., inputs=[r.ruta], script=__file__)

Uso desde la terminal::

    uv run fuentes estado            # de dónde sale cada fuente y qué falta subir a bocho
    uv run fuentes sync              # baja el lake de bocho a data/lake/
    uv run fuentes exportar <nombre> # materializa una fuente de transición en data/bronze/
    uv run fuentes publicar <nombre> # sube a bocho, nunca sobrescribe
"""

from __future__ import annotations

from . import lake
from .catalogo import Catalogo, CatalogoInvalido, Fuente, cargar_catalogo
from .config import FuentesConfig, load_config
from .exportar import exportar
from .resolucion import (
    FuenteDesconocida,
    FuenteNoEncontrada,
    Resolucion,
    origen_de,
    resolver,
    ruta,
)

__all__ = [
    "Catalogo",
    "CatalogoInvalido",
    "Fuente",
    "FuenteDesconocida",
    "FuenteNoEncontrada",
    "FuentesConfig",
    "Resolucion",
    "cargar_catalogo",
    "exportar",
    "lake",
    "load_config",
    "origen_de",
    "resolver",
    "ruta",
]
