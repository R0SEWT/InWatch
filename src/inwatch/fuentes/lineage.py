"""Manifiesto ``<archivo>.lineage.json`` que viaja junto a cada copia.

Heredado de la regla de infelix: un artefacto derivado sin lineage no es fuente de
verdad. Acá acompaña a lo exportado a ``data/bronze/`` y a lo publicado en bocho, y es
lo que ``sync`` usa para rechazar una copia que llegó distinta de como salió.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def ruta_lineage(archivo: Path) -> Path:
    return archivo.with_name(archivo.name + ".lineage.json")


def construir(
    *,
    nombre: str,
    titularidad: str,
    sha256: str | None,
    bytes_: int,
    ruta_origen: str,
    git_ref: str | None,
) -> dict:
    return {
        "nombre": nombre,
        "titularidad": titularidad,
        "sha256": sha256,
        "bytes": bytes_,
        "ruta_origen": ruta_origen,
        "git_ref": git_ref,
        "generado_en": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
    }


def escribir(destino: Path, campos: dict) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(campos, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destino


def leer(archivo_lineage: Path) -> dict | None:
    if not archivo_lineage.is_file():
        return None
    return json.loads(archivo_lineage.read_text(encoding="utf-8"))
