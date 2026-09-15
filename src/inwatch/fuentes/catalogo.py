"""Lectura y validación de ``registry/fuentes.toml``.

El catálogo existe porque los cinco loaders de InWatch nacieron con
``SOURCE = Path("/home/<usuario>/Code/tesis/infelix/data/silver")``. Eso ataba el repo
a una laptop, al árbol de infelix y, vía ``canon``, dejaba rutas de máquina dentro de un
registro versionado (inwatch-8sm). Acá cada dataset tiene un nombre, una titularidad y
una lista de lugares donde puede estar; el código pide el nombre.

La validación es estricta a propósito: un typo en un origen o una fuente sin
titularidad se descubre al cargar, no semanas después cuando un loader lee otra cosa.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .config import FuentesConfig

CLAVES_FUENTE = frozenset(
    {"descripcion", "titularidad", "lake", "curado", "transicion", "git_ref"}
)


class CatalogoInvalido(ValueError):
    """El catálogo no existe o su contenido no respeta el contrato."""


@dataclass(frozen=True)
class Fuente:
    nombre: str
    titularidad: str
    descripcion: str = ""
    lake: str | None = None
    # Insumo chico y versionado en el repo: existe al clonar, sin bocho ni infelix.
    curado: str | None = None
    transicion: tuple[str, ...] = ()
    git_ref: str | None = None


@dataclass(frozen=True)
class Catalogo:
    origenes: dict[str, Path]
    remoto: str | None
    fuentes: dict[str, Fuente]


def clave_entorno(nombre: str) -> str:
    """``h3_admin`` → ``H3_ADMIN``: el sufijo de ``INWATCH_FUENTE_*`` e ``INWATCH_ORIGEN_*``."""
    return re.sub(r"[^A-Z0-9]", "_", nombre.upper())


def partir_candidato(candidato: str) -> tuple[str, str]:
    """``"infelix:data/x.csv"`` → ``("infelix", "data/x.csv")``."""
    origen, sep, rel = candidato.partition(":")
    if not sep or not origen or not rel:
        raise CatalogoInvalido(f"candidato '{candidato}' mal formado: se espera origen:ruta")
    return origen, rel


def _relativa(nombre: str, campo: str, ruta: str) -> str:
    p = PurePosixPath(ruta)
    if p.is_absolute() or ".." in p.parts:
        raise CatalogoInvalido(f"fuente '{nombre}': `{campo}` debe ser relativa y sin '..': {ruta}")
    return ruta


def _fuente(nombre: str, d: dict, origenes: Mapping[str, Path]) -> Fuente:
    sobrantes = set(d) - CLAVES_FUENTE
    if sobrantes:
        raise CatalogoInvalido(f"fuente '{nombre}': claves desconocidas {sorted(sobrantes)}")
    titularidad = d.get("titularidad")
    if not isinstance(titularidad, str) or not titularidad.strip():
        raise CatalogoInvalido(f"fuente '{nombre}': falta titularidad")

    transicion = d.get("transicion", [])
    if not isinstance(transicion, list) or not all(isinstance(c, str) for c in transicion):
        raise CatalogoInvalido(f"fuente '{nombre}': `transicion` debe ser una lista de strings")
    for candidato in transicion:
        origen, rel = partir_candidato(candidato)
        if origen not in origenes:
            raise CatalogoInvalido(
                f"fuente '{nombre}': el origen '{origen}' no está declarado en [origenes]"
            )
        _relativa(nombre, "transicion", rel)

    lake = d.get("lake")
    if lake is not None:
        _relativa(nombre, "lake", lake)
    curado = d.get("curado")
    if curado is not None:
        _relativa(nombre, "curado", curado)
    if lake is None and curado is None and not transicion:
        raise CatalogoInvalido(f"fuente '{nombre}': necesita `lake`, `curado` o `transicion`")

    return Fuente(
        nombre=nombre,
        titularidad=titularidad,
        descripcion=d.get("descripcion", ""),
        lake=lake,
        curado=curado,
        transicion=tuple(transicion),
        git_ref=d.get("git_ref"),
    )


def cargar_catalogo(cfg: FuentesConfig, env: Mapping[str, str] | None = None) -> Catalogo:
    env = os.environ if env is None else env
    if not cfg.catalogo.is_file():
        raise CatalogoInvalido(f"no existe el catálogo {cfg.catalogo}")
    with open(cfg.catalogo, "rb") as f:
        data = tomllib.load(f)

    origenes = {
        nombre: Path(env.get(f"INWATCH_ORIGEN_{clave_entorno(nombre)}", raiz)).expanduser()
        for nombre, raiz in data.get("origenes", {}).items()
    }
    remoto = env.get("INWATCH_LAKE_REMOTO") or data.get("lake", {}).get("remoto")
    fuentes = {
        nombre: _fuente(nombre, d, origenes) for nombre, d in data.get("fuente", {}).items()
    }
    return Catalogo(origenes=origenes, remoto=remoto, fuentes=fuentes)
