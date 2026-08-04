"""Configuración del registro canónico, leída de ``pyproject.toml``.

Diferencia deliberada con el origen (``infelix/scripts/canon.py``): allí ``ROOT``,
``REGISTRY`` y ``WATCHED`` son constantes de módulo calculadas como
``Path(__file__).parent.parent``, lo que ata el paquete a un layout concreto y obliga
a un ``sys.path.insert`` en cada consumidor. Acá la raíz se descubre subiendo hasta
el ``pyproject.toml`` y el resto sale de ``[tool.inwatch.canon]``, así el mismo
paquete sirve a cualquier repo sin editar código.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_REGISTRY = "registry/canonical_numbers.json"
DEFAULT_WATCHED = ("analysis/*.md", "experiments/**/*.md")


class CanonConfigError(RuntimeError):
    """No se pudo ubicar la raíz del proyecto o leer su configuración."""


def find_root(start: Path | None = None) -> Path:
    """Raíz del proyecto = primer ancestro con ``pyproject.toml``.

    Falla fuerte en vez de adivinar: un registro escrito en la raíz equivocada es
    peor que un error, porque se descubre semanas después con números divergentes.
    """
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise CanonConfigError(
        f"no encontré pyproject.toml subiendo desde {here}; "
        "canon necesita saber cuál es la raíz del proyecto"
    )


@dataclass(frozen=True)
class CanonConfig:
    root: Path
    registry: Path
    watched: tuple[str, ...]


@lru_cache(maxsize=8)
def load_config(start: Path | None = None) -> CanonConfig:
    root = find_root(start)
    with open(root / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    section = data.get("tool", {}).get("inwatch", {}).get("canon", {})
    registry = root / section.get("registry", DEFAULT_REGISTRY)
    watched = tuple(section.get("watched", DEFAULT_WATCHED))
    return CanonConfig(root=root, registry=registry, watched=watched)
