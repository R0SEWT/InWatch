"""bocho como data lake: ``sync`` baja, ``publicar`` sube, ``estado`` compara.

Tres reglas, cada una con su motivo:

- **Nunca se borra ni se sobrescribe en bocho.** ``publicar`` se detiene si ya hay otra
  versión con otro sha. Pisar el silver de bocho rompería en silencio la procedencia de
  todo lo que se emitió contra la versión anterior.
- **``sync`` verifica contra el lineage** y, si no cuadra, descarta la copia: una copia
  corrupta en ``data/lake/`` ganaría sobre todo lo demás en la resolución.
- **SSH es ``/usr/bin/ssh`` en modo batch.** En la terminal del usuario ``ssh`` es el
  kitten de kitty, que exige un TTY y falla desde cualquier proceso no interactivo.

El remoto es un protocolo (``disponible``, ``sha256``, ``leer_lineage``, ``subir``,
``bajar``) para que los tests usen un directorio en lugar de bocho.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from . import lineage
from .catalogo import Catalogo, CatalogoInvalido, cargar_catalogo
from .config import FuentesConfig, load_config
from .resolucion import (
    FuenteNoEncontrada,
    _contexto,
    _hash_archivo,
    origen_de,
    resolver,
    sha_de,
)

SSH = "/usr/bin/ssh"
OPCIONES_SSH = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=5")
SSH_SIN_CONEXION = 255
# El host va como argv a ssh. Uno que empiece con `-` lo lee como opción —
# `-oProxyCommand=…` ejecuta un comando— y `[lake].remoto` está versionado en un repo
# público: un PR de un tercero correría código en la máquina de quien haga `fuentes estado`.
HOST_VALIDO = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*(@[A-Za-z0-9_][A-Za-z0-9_.-]*)?$")


class LakeNoConfigurado(RuntimeError):
    """No hay ``host:/ruta`` válido para bocho."""


class LakeInaccesible(RuntimeError):
    """bocho no respondió o el comando remoto falló."""


class ConflictoLake(RuntimeError):
    """Publicar pisaría otra versión, o no hay nada que publicar."""


class IntegridadLake(RuntimeError):
    """La copia bajada no cuadra con su lineage."""


class Remoto(Protocol):
    def disponible(self) -> bool: ...
    def sha256(self, rel: str) -> str | None: ...
    def leer_lineage(self, rel: str) -> dict | None: ...
    def subir(self, local: Path, rel: str) -> None: ...
    def bajar(self, rel: str, local: Path) -> None: ...


def _ejecutar(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


class RemotoSSH:
    def __init__(
        self,
        destino: str,
        ejecutar: Callable[[list[str]], subprocess.CompletedProcess] = _ejecutar,
    ) -> None:
        host, sep, base = destino.partition(":")
        if not sep or not host or not base.startswith("/"):
            raise LakeNoConfigurado(f"remoto '{destino}' mal formado: se espera host:/ruta")
        if not HOST_VALIDO.match(host):
            raise LakeNoConfigurado(
                f"host '{host}' inválido: solo letras, dígitos, punto, guion y guion bajo, "
                "opcionalmente con usuario@. Un host que empieza con '-' lo lee ssh como opción"
            )
        self.host = host
        self.base = base.rstrip("/")
        self._ejecutar = ejecutar

    def _remota(self, rel: str) -> str:
        return f"{self.base}/{rel}"

    def _ssh(self, comando: str) -> subprocess.CompletedProcess:
        return self._ejecutar([SSH, *OPCIONES_SSH, self.host, comando])

    def _exigir(self, r: subprocess.CompletedProcess, que: str) -> None:
        if r.returncode == SSH_SIN_CONEXION:
            raise LakeInaccesible(f"bocho ({self.host}) no respondió al {que}: {r.stderr}")

    def _rsync(self, origen: str, destino: str, *extra: str) -> None:
        cmd = ["rsync", "-a", "--partial", *extra, "-e", " ".join((SSH, *OPCIONES_SSH))]
        r = self._ejecutar([*cmd, origen, destino])
        if r.returncode != 0:
            raise LakeInaccesible(f"rsync {origen} → {destino} falló ({r.returncode}): {r.stderr}")

    def disponible(self) -> bool:
        return self._ssh("true").returncode == 0

    def sha256(self, rel: str) -> str | None:
        r = self._ssh(f"sha256sum -- {shlex.quote(self._remota(rel))}")
        self._exigir(r, "sha256sum")
        return r.stdout.split()[0] if r.returncode == 0 and r.stdout.strip() else None

    def leer_lineage(self, rel: str) -> dict | None:
        r = self._ssh(f"cat -- {shlex.quote(self._remota(rel + '.lineage.json'))}")
        self._exigir(r, "leer el lineage")
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None

    def subir(self, local: Path, rel: str) -> None:
        carpeta = str(PurePosixPath(self._remota(rel)).parent)
        r = self._ssh(f"mkdir -p -- {shlex.quote(carpeta)}")
        self._exigir(r, "crear la carpeta")
        self._rsync(str(local), f"{self.host}:{self._remota(rel)}", "--ignore-existing")

    def bajar(self, rel: str, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        self._rsync(f"{self.host}:{self._remota(rel)}", str(local))


def remoto_desde(cat: Catalogo) -> RemotoSSH:
    if not cat.remoto or cat.remoto.strip().upper() == "PENDIENTE":
        raise LakeNoConfigurado(
            "el lake remoto no está configurado: completa [lake].remoto en "
            "registry/fuentes.toml o exporta INWATCH_LAKE_REMOTO=host:/ruta"
        )
    return RemotoSSH(cat.remoto)


def _rel_lake(nombre: str, lake: str | None) -> str:
    if not lake:
        raise CatalogoInvalido(f"'{nombre}' no declara `lake`: no tiene lugar en bocho")
    return lake


# ─── publicar ─────────────────────────────────────────────────────────────────
def publicar(
    nombre: str,
    remoto: Remoto,
    *,
    cfg: FuentesConfig | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Sube a bocho la fuente tal como resuelve hoy. Devuelve ``publicado`` o ``ya_estaba``."""
    cfg, _, fuente, env = _contexto(nombre, cfg, env)
    rel = _rel_lake(nombre, fuente.lake)
    r = resolver(nombre, cfg=cfg, env=env, sha=True)
    if r.origen == "lake":
        raise ConflictoLake(f"'{nombre}' ya se sirve desde el lake ({r.ruta}): nada que publicar")

    remoto_sha = remoto.sha256(rel)
    if remoto_sha is not None and remoto_sha != r.sha256:
        raise ConflictoLake(
            f"{rel}: bocho tiene otra versión (sha {remoto_sha[:12]}…) y la local es "
            f"{(r.sha256 or '')[:12]}…; no se sobrescribe"
        )

    previo = lineage.leer(lineage.ruta_lineage(r.ruta)) if r.origen == "exportado" else None
    campos = lineage.construir(
        nombre=nombre,
        titularidad=fuente.titularidad,
        sha256=r.sha256,
        bytes_=r.ruta.stat().st_size,
        ruta_origen=(previo or {}).get("ruta_origen")
        or origen_de(r.ruta, cfg=cfg, env=env)
        or str(r.ruta),
        git_ref=(previo or {}).get("git_ref", r.git_ref),
    )
    temporal = lineage.escribir(
        cfg.datos / ".cache" / "publicar" / f"{nombre}.lineage.json", campos
    )

    if remoto_sha is None:
        remoto.subir(r.ruta, rel)
    if remoto.leer_lineage(rel) is None:
        remoto.subir(temporal, rel + ".lineage.json")
    return "publicado" if remoto_sha is None else "ya_estaba"


# ─── sync ─────────────────────────────────────────────────────────────────────
def sync(
    nombre: str,
    remoto: Remoto,
    *,
    cfg: FuentesConfig | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Baja de bocho a ``data/lake/``. Devuelve ``verificado`` o ``sin_lineage``."""
    cfg, _, fuente, env = _contexto(nombre, cfg, env)
    rel = _rel_lake(nombre, fuente.lake)
    destino = cfg.lake / rel
    parcial = destino.with_name(destino.name + ".parcial")
    remoto.bajar(rel, parcial)

    campos = remoto.leer_lineage(rel)
    if campos is None:
        # bocho ya era data lake antes de este catálogo: su silver histórico no trae
        # lineage. Se acepta, pero el resultado lo declara en vez de callarlo.
        parcial.replace(destino)
        return "sin_lineage"

    local = _hash_archivo(parcial)
    if local != campos.get("sha256"):
        parcial.unlink()
        raise IntegridadLake(
            f"{rel}: la copia bajada tiene sha {local[:12]}… y su lineage dice "
            f"{str(campos.get('sha256'))[:12]}…; se descartó"
        )
    parcial.replace(destino)
    lineage.escribir(lineage.ruta_lineage(destino), campos)
    return "verificado"


# ─── estado ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class FilaEstado:
    nombre: str
    origen: str
    ruta: Path | None
    es_transicion: bool
    remoto: str


def _comparar(cfg: FuentesConfig, remoto: Remoto, rel: str) -> str:
    campos = remoto.leer_lineage(rel)
    remoto_sha = (campos or {}).get("sha256") or remoto.sha256(rel)
    if remoto_sha is None:
        return "ausente"
    copia = cfg.lake / rel
    if not copia.is_file():
        return "solo_remoto"
    return "igual" if sha_de(cfg, copia) == remoto_sha else "distinto"


def estado(
    remoto: Remoto | None,
    *,
    cfg: FuentesConfig | None = None,
    env: Mapping[str, str] | None = None,
) -> list[FilaEstado]:
    """Una fila por fuente. Con bocho caído o sin configurar, no falla: lo declara."""
    cfg = cfg or load_config()
    cat = cargar_catalogo(cfg, env)
    try:
        arriba = remoto is not None and remoto.disponible()
    except LakeInaccesible:
        arriba = False

    filas = []
    for nombre, fuente in sorted(cat.fuentes.items()):
        try:
            r = resolver(nombre, cfg=cfg, env=env, sha=False)
            origen, ruta, transicion = r.origen, r.ruta, r.es_transicion
        except FuenteNoEncontrada:
            origen, ruta, transicion = "falta", None, False

        if remoto is None:
            situacion = "no_configurado"
        elif not arriba:
            situacion = "sin_conexion"
        elif not fuente.lake:
            situacion = "sin_lake"
        else:
            try:
                situacion = _comparar(cfg, remoto, fuente.lake)
            except LakeInaccesible:
                situacion = "sin_conexion"
        filas.append(FilaEstado(nombre, origen, ruta, transicion, situacion))
    return filas
