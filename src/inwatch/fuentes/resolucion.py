"""De un nombre a un archivo, con procedencia, sin tocar la red.

Orden de resolución, y por qué:

1. ``INWATCH_FUENTE_<NOMBRE>`` — override puntual. Si se declara y el archivo no está,
   falla: un override que cae en silencio al siguiente candidato miente sobre qué se leyó.
2. ``data/lake/<lake>`` — la copia local de bocho. bocho es el data lake y la fuente
   principal, pero se lee su espejo: resolver nunca usa la red, así que CI, notebooks y el
   trabajo sin conexión funcionan igual.
3. ``data/bronze/fuentes/<nombre>/`` — lo materializado con ``fuentes exportar``.
4. ``<origen>:<ruta>`` — infelix o Wachi en solo lectura, como transición.

Con ``git_ref`` el paso 4 se salta: el archivo vivo del origen es OTRA versión. Es el
fallo que destapó pulso-estadios, cuyos CSV de hoy traen 94 filas que su ancla no vio.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .catalogo import Catalogo, Fuente, cargar_catalogo, clave_entorno, partir_candidato
from .config import FuentesConfig, load_config

ORIGENES_PROPIOS = frozenset({"entorno", "lake", "curado", "exportado"})

_MEMO: dict[tuple[str, int, int], str] = {}


class FuenteDesconocida(LookupError):
    """El nombre no está en el catálogo."""


class FuenteNoEncontrada(FileNotFoundError):
    """La fuente existe en el catálogo pero ninguno de sus candidatos está en disco."""


@dataclass(frozen=True)
class Resolucion:
    nombre: str
    ruta: Path
    origen: str
    sha256: str | None = None
    git_ref: str | None = None

    @property
    def es_transicion(self) -> bool:
        """Se leyó de un origen ajeno: falta subirla a bocho."""
        return self.origen not in ORIGENES_PROPIOS


# ─── sha con caché en disco ───────────────────────────────────────────────────
def _hash_archivo(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _archivo_cache(cfg: FuentesConfig) -> Path:
    return cfg.datos / ".cache" / "fuentes_sha.json"


def sha_de(cfg: FuentesConfig, path: Path) -> str:
    """SHA-256 memoizado por (ruta, tamaño, mtime_ns), en memoria y en disco.

    En disco porque ``osm_peru_gpkg`` pesa 1,1 GB y cada corrida de un loader lo pasaría
    entero por sha256 solo para registrar procedencia.
    """
    real = path.resolve()
    st = real.stat()
    clave = (str(real), st.st_size, st.st_mtime_ns)
    if (memo := _MEMO.get(clave)) is not None:
        return memo

    cache = _archivo_cache(cfg)
    disco: dict[str, str] = json.loads(cache.read_text("utf-8")) if cache.is_file() else {}
    clave_disco = f"{clave[0]}|{clave[1]}|{clave[2]}"
    if (guardado := disco.get(clave_disco)) is not None:
        _MEMO[clave] = guardado
        return guardado

    digest = _hash_archivo(real)
    _MEMO[clave] = digest
    # Las entradas viejas del mismo archivo sobran: su (tamaño, mtime) ya no existe.
    disco = {k: v for k, v in disco.items() if not k.startswith(f"{clave[0]}|")}
    disco[clave_disco] = digest
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporal = cache.with_name(cache.name + ".tmp")
    temporal.write_text(json.dumps(disco, indent=0, sort_keys=True), encoding="utf-8")
    temporal.replace(cache)
    return digest


# ─── candidatos ───────────────────────────────────────────────────────────────
def ruta_exportada(cfg: FuentesConfig, fuente: Fuente) -> Path:
    """Dónde aterriza `fuentes exportar`. El nombre del archivo sale del primer
    candidato que lo declare: lake, curado o el origen de transición."""
    referencia = fuente.lake or fuente.curado
    if referencia is None:
        if not fuente.transicion:
            return cfg.datos / "bronze" / "fuentes" / fuente.nombre / fuente.nombre
        referencia = partir_candidato(fuente.transicion[0])[1]
    return cfg.datos / "bronze" / "fuentes" / fuente.nombre / PurePosixPath(referencia).name


def candidatos(
    cfg: FuentesConfig, cat: Catalogo, fuente: Fuente, env: Mapping[str, str]
) -> list[tuple[str, Path]]:
    salida: list[tuple[str, Path]] = []
    if fuente.lake:
        salida.append(("lake", cfg.lake / fuente.lake))
    if fuente.curado:
        salida.append(("curado", cfg.root / fuente.curado))
    salida.append(("exportado", ruta_exportada(cfg, fuente)))
    if not fuente.git_ref:
        for candidato in fuente.transicion:
            origen, rel = partir_candidato(candidato)
            salida.append((origen, cat.origenes[origen] / rel))
    return salida


def _contexto(
    nombre: str, cfg: FuentesConfig | None, env: Mapping[str, str] | None
) -> tuple[FuentesConfig, Catalogo, Fuente, Mapping[str, str]]:
    cfg = cfg or load_config()
    env = os.environ if env is None else env
    cat = cargar_catalogo(cfg, env)
    if nombre not in cat.fuentes:
        raise FuenteDesconocida(
            f"fuente desconocida '{nombre}': no está en {cfg.catalogo.relative_to(cfg.root)}"
        )
    return cfg, cat, cat.fuentes[nombre], env


def resolver(
    nombre: str,
    *,
    cfg: FuentesConfig | None = None,
    env: Mapping[str, str] | None = None,
    sha: bool = True,
) -> Resolucion:
    cfg, cat, fuente, env = _contexto(nombre, cfg, env)

    def _resuelta(origen: str, ruta: Path) -> Resolucion:
        return Resolucion(
            nombre=nombre,
            ruta=ruta,
            origen=origen,
            sha256=sha_de(cfg, ruta) if sha and ruta.is_file() else None,
            git_ref=fuente.git_ref if origen == "exportado" else None,
        )

    override = env.get(f"INWATCH_FUENTE_{clave_entorno(nombre)}")
    if override:
        ruta = Path(override).expanduser()
        if not ruta.exists():
            raise FuenteNoEncontrada(
                f"'{nombre}': INWATCH_FUENTE_{clave_entorno(nombre)} apunta a {ruta}, "
                "que no existe"
            )
        return _resuelta("entorno", ruta)

    probadas = []
    for origen, ruta in candidatos(cfg, cat, fuente, env):
        if ruta.exists():
            return _resuelta(origen, ruta)
        probadas.append(f"  {origen:<10} {ruta}")

    pistas = []
    if fuente.lake:
        pistas.append(f"  `fuentes sync {nombre}` para bajarla de bocho")
    if fuente.git_ref:
        pistas.append(
            f"  `fuentes exportar {nombre}` para materializar la versión congelada en "
            f"{fuente.git_ref} (el archivo vivo del origen es otra versión)"
        )
    raise FuenteNoEncontrada(
        f"'{nombre}' no está en ningún candidato. Probé:\n"
        + "\n".join(probadas)
        + ("\nPrueba:\n" + "\n".join(pistas) if pistas else "")
    )


def ruta(
    nombre: str, *, cfg: FuentesConfig | None = None, env: Mapping[str, str] | None = None
) -> Path:
    """Atajo para loaders: la ruta resuelta, sin calcular sha."""
    return resolver(nombre, cfg=cfg, env=env, sha=False).ruta


def origen_de(
    path: Path, *, cfg: FuentesConfig | None = None, env: Mapping[str, str] | None = None
) -> str | None:
    """Expresa una ruta como ``lake:<rel>`` u ``<origen>:<rel>``; None si ninguno la cubre.

    Es lo que ``canon`` registra en vez de ``/home/<usuario>/...`` (inwatch-8sm).
    """
    cfg = cfg or load_config()
    env = os.environ if env is None else env
    real = Path(path).expanduser().resolve()
    raices = [("lake", cfg.lake)] + sorted(
        cargar_catalogo(cfg, env).origenes.items(),
        key=lambda kv: -len(kv[1].expanduser().resolve().parts),
    )
    for alias, raiz in raices:
        try:
            rel = real.relative_to(raiz.expanduser().resolve())
        except ValueError:
            continue
        return f"{alias}:{rel.as_posix()}"
    return None
