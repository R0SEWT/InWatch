"""Materializa una fuente de transición en ``data/bronze/fuentes/``, con lineage.

Generaliza ``exportar_epoca_ancla`` de pulso-estadios: leer del origen con ``git show``
es lectura pura —no toca índice, worktree ni refs—, y la frontera de infelix prohíbe
escribir allí pero autoriza exportar. Con ``git_ref`` se exporta la versión congelada;
sin él, el archivo vivo.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path

from . import lineage
from .catalogo import partir_candidato
from .config import FuentesConfig
from .resolucion import FuenteNoEncontrada, Resolucion, _contexto, ruta_exportada, sha_de


def _git_show(repo: Path, ref: str, rel: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), "show", f"{ref}:{rel}"], capture_output=True, check=True
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise FuenteNoEncontrada(
            f"git show {ref}:{rel} falló en {repo}: {exc.stderr.decode(errors='replace').strip()}"
        ) from exc


def exportar(
    nombre: str, *, cfg: FuentesConfig | None = None, env: Mapping[str, str] | None = None
) -> Resolucion:
    cfg, cat, fuente, env = _contexto(nombre, cfg, env)
    if not fuente.transicion:
        raise FuenteNoEncontrada(f"'{nombre}' no tiene origen de transición del que exportar")

    origen, rel = partir_candidato(fuente.transicion[0])
    raiz = cat.origenes[origen]
    destino = ruta_exportada(cfg, fuente)
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + ".parcial")

    if fuente.git_ref:
        parcial.write_bytes(_git_show(raiz, fuente.git_ref, rel))
    else:
        fuente_viva = raiz / rel
        if not fuente_viva.is_file():
            raise FuenteNoEncontrada(f"'{nombre}': no existe {fuente_viva}")
        shutil.copyfile(fuente_viva, parcial)
    parcial.replace(destino)

    digest = sha_de(cfg, destino)
    lineage.escribir(
        lineage.ruta_lineage(destino),
        lineage.construir(
            nombre=nombre,
            titularidad=fuente.titularidad,
            sha256=digest,
            bytes_=destino.stat().st_size,
            ruta_origen=f"{origen}:{rel}",
            git_ref=fuente.git_ref,
        ),
    )
    return Resolucion(
        nombre=nombre, ruta=destino, origen="exportado", sha256=digest, git_ref=fuente.git_ref
    )
