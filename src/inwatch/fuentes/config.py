"""Configuración del catálogo de fuentes, leída de ``pyproject.toml``.

Misma forma que ``canon.config``: la raíz se descubre subiendo hasta el
``pyproject.toml`` y las rutas salen de ``[tool.inwatch.fuentes]``. No se cachea: los
tests reescriben el catálogo entre llamadas y un valor viejo sería un bug invisible.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from inwatch.canon.config import find_root

DEFAULT_CATALOGO = "registry/fuentes.toml"
DEFAULT_LAKE = "data/lake"
DEFAULT_DATOS = "data"


@dataclass(frozen=True)
class FuentesConfig:
    root: Path
    catalogo: Path
    lake: Path
    datos: Path


def load_config(start: Path | None = None) -> FuentesConfig:
    root = find_root(start)
    with open(root / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    section = data.get("tool", {}).get("inwatch", {}).get("fuentes", {})
    return FuentesConfig(
        root=root,
        catalogo=root / section.get("catalogo", DEFAULT_CATALOGO),
        lake=root / section.get("lake", DEFAULT_LAKE),
        datos=root / section.get("datos", DEFAULT_DATOS),
    )
