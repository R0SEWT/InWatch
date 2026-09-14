"""Registro de números canónicos — hardening anti número-stale.

Fuente única de verdad para las cifras portantes. El pipeline **emite** cada número
acá con procedencia; los docs lo citan por ``key`` con anclas ``CANON:`` y
``inwatch.canon.check`` verifica que lo citado == round(canónico, decimales).

Portado de ``infelix/scripts/canon.py``, que nació de un fallo real: un multiplicador
stale (robo ×5.48) sobrevivió a un re-run del pipeline que lo movió a ×4.6 y se coló
a un paper enviado. El mecanismo entero existe para que eso no pueda repetirse.

Dos zonas en el registro:

- ``policy``  → **hand-written**. La única parte humana: por *familia*, qué
  ``canonical_variant`` es canónica, ``decimals`` y ``round_mode``. Un script **no
  puede autoproclamarse canónico**: ``emit()`` deriva ``canonical`` de la policy.
  Una clave puede ser un patrón glob (``r_direct.*``) para cubrir una familia
  paramétrica; la exacta gana sobre el patrón y entre patrones gana el más largo.
- ``entries`` → **machine-written** por ``emit()``. Determinista (``sort_keys``): una
  entrada solo cambia si cambia el valor redondeado o el hash de los inputs.

Frescura por **hash de contenido** del emisor (no mtime, no ancestría git): clone-safe
y sin depender del orden emit/commit.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from fnmatch import fnmatch
from pathlib import Path

from .config import CanonConfig, load_config

SCHEMA_VERSION = 1
DEFAULT_ROUND_MODE = "half_up"
DEFAULT_DECIMALS = 4

_ROUND = {"half_up": ROUND_HALF_UP, "half_even": ROUND_HALF_EVEN, "floor": ROUND_FLOOR}

_SHA_CACHE: dict[tuple[str, int, int], str] = {}


# ─── procedencia ──────────────────────────────────────────────────────────────
def _sha256(path: Path) -> str | None:
    """SHA-256 de un archivo; None si no existe (input regenerable/gitignored).

    Memoizado por (path, size, mtime_ns) para no re-hashear inputs grandes en cada
    emisión de una misma corrida.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    ckey = (str(path), st.st_size, st.st_mtime_ns)
    if (cached := _SHA_CACHE.get(ckey)) is not None:
        return cached
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    _SHA_CACHE[ckey] = h.hexdigest()
    return _SHA_CACHE[ckey]


def _git(cfg: CanonConfig, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=cfg.root, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _relpath(cfg: CanonConfig, path: Path) -> str:
    """Clave de un input en el registro: relativa a la raíz, o ``<origen>:<ruta>``.

    Los inputs de casi todo experimento vienen de infelix, fuera de la raíz. Guardarlos
    como ``/home/<usuario>/...`` ataba un registro versionado a una laptop (inwatch-8sm).
    Si el catálogo de fuentes declara un origen que cubre la ruta, se usa su alias; si no
    hay catálogo o ningún origen la cubre, se conserva la ruta: no hay alias honesto.
    """
    try:
        return str(Path(path).resolve().relative_to(cfg.root))
    except ValueError:
        pass
    # Import diferido: `fuentes` depende de `canon.config`, y el ciclo solo existe si
    # se resolviera al importar el módulo.
    from inwatch.fuentes import CatalogoInvalido, load_config, origen_de

    try:
        alias = origen_de(Path(path), cfg=load_config(cfg.root))
    except CatalogoInvalido:
        alias = None
    return alias or str(path)


# ─── redondeo canónico ────────────────────────────────────────────────────────
def round_canonical(value: float, decimals: int, mode: str = DEFAULT_ROUND_MODE) -> Decimal:
    """Redondea `value` a `decimals` con el modo declarado en la policy."""
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-decimals), rounding=_ROUND[mode])


def display_str(value: float, decimals: int, mode: str = DEFAULT_ROUND_MODE) -> str:
    return f"{round_canonical(value, decimals, mode):.{decimals}f}"


# ─── resolución de policy (exacta > patrón más largo) ─────────────────────────
def resolve_policy(family: str, policy: dict) -> dict | None:
    """Policy aplicable a `family`: exacta, si no el patrón más específico.

    Reglas deliberadamente conservadoras y deterministas: la exacta siempre gana
    (permite excepcionar una categoría suelta); entre patrones gana el más largo y,
    a igual longitud, el orden alfabético — nunca el orden de inserción del JSON.
    """
    if family in policy:
        return policy[family]
    cands = [k for k in policy if "*" in k and fnmatch(family, k)]
    if not cands:
        return None
    return policy[sorted(cands, key=lambda k: (-len(k), k))[0]]


# ─── registro ─────────────────────────────────────────────────────────────────
def load(cfg: CanonConfig | None = None) -> dict:
    cfg = cfg or load_config()
    if cfg.registry.exists():
        with open(cfg.registry, encoding="utf-8") as f:
            return json.load(f)
    return {"schema_version": SCHEMA_VERSION, "policy": {}, "entries": {}}


def dump(reg: dict, cfg: CanonConfig | None = None) -> None:
    cfg = cfg or load_config()
    cfg.registry.parent.mkdir(parents=True, exist_ok=True)
    with open(cfg.registry, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def emit(
    family: str,
    value: float,
    *,
    variant: str,
    unit: str,
    estimator: str,
    inputs: list,
    script: str,
    cfg: CanonConfig | None = None,
) -> str:
    """Registra/actualiza una entrada canónica. Devuelve la key ``family.variant``.

    Nunca crashea el pipeline: si falta la policy de la familia, escribe la entrada
    con ``needs_policy=True`` y ``canonical=False`` en vez de abortar. La decisión de
    precisión y variante es humana, no del script.
    """
    cfg = cfg or load_config()
    reg = load(cfg)
    reg.setdefault("schema_version", SCHEMA_VERSION)
    reg.setdefault("policy", {})
    reg.setdefault("entries", {})

    pol = resolve_policy(family, reg["policy"])
    decimals = pol.get("decimals", DEFAULT_DECIMALS) if pol else DEFAULT_DECIMALS
    mode = pol.get("round_mode", DEFAULT_ROUND_MODE) if pol else DEFAULT_ROUND_MODE
    canonical = (pol.get("canonical_variant") == variant) if pol else False

    key = f"{family}.{variant}"
    script_rel = _relpath(cfg, Path(script))
    inputs_sha = {_relpath(cfg, Path(p)): _sha256(Path(p)) for p in inputs}
    display = display_str(value, decimals, mode)
    script_sha = _sha256(Path(script))
    needs_policy = pol is None
    # El redondeo del `value` guardado existe para que el ruido de coma flotante no
    # produzca churn — pero NUNCA puede ser más grueso que lo que la policy muestra, o el
    # registro se contradice a sí mismo: `display` sale del valor sin redondear y
    # `check` lo recomputa desde `value`, así que los dos dejarían de coincidir y el
    # linter fallaría contra la salida de su propio emisor. Pasó con
    # `correspondencia.desvio_masa` (decimals=9): 9.90e-7 se guardaba como 1e-6 mientras
    # `display` decía 0.000000990. El margen de 3 dígitos deja sitio para el redondeo de
    # presentación sin volver a dejar entrar el ruido.
    value_r = round(float(value), max(6, decimals + 3))

    prev = reg["entries"].get(key, {})
    prev_prov = prev.get("provenance", {})
    # Si NADA material cambió, preserva la procedencia previa → un re-run no-op no
    # produce diff. Sin esto el registro sería incommiteable por churn.
    unchanged = (
        prev.get("value") == value_r
        and prev.get("display") == display
        and prev.get("canonical") == canonical
        and prev.get("needs_policy", False) == needs_policy
        and prev_prov.get("inputs_sha256") == inputs_sha
        and prev_prov.get("script_sha256") == script_sha
    )
    # ...salvo que la previa fuera PROVISIONAL. Emitir con el emisor sin commitear
    # graba `dirty: true` y el HEAD anterior — un commit donde el emisor ni existía.
    # Preservar eso lo congelaba para siempre: el sha es del contenido y no del
    # commit, así que el re-run post-commit no cambia nada material y ganaba esta
    # rama. Re-sellar mientras esté sucia hace que converja sola. No reintroduce
    # churn: con el mismo HEAD y el mismo estado sucio el resultado es idéntico.
    if unchanged and not prev_prov.get("dirty", False):
        git_commit = prev_prov.get("git_commit")
        dirty = prev_prov.get("dirty")
        emitted_at = prev_prov.get("emitted_at")
    else:
        git_commit = _git(cfg, "rev-parse", "--short", "HEAD") or "uncommitted"
        dirty = bool(_git(cfg, "status", "--porcelain", "--", script_rel))
        # el valor no cambió: el momento de emisión sigue siendo el de la corrida
        # que lo produjo, y preservarlo evita diff en la corrida que solo re-sella.
        emitted_at = (
            prev_prov.get("emitted_at")
            if unchanged
            else datetime.now(UTC).astimezone().isoformat(timespec="seconds")
        )

    reg["entries"][key] = {
        "value": value_r,
        "display": display,
        "unit": unit,
        "estimator": estimator,
        "family": family,
        "variant": variant,
        "canonical": canonical,
        "needs_policy": needs_policy,
        "provenance": {
            "script": script_rel,
            "script_sha256": script_sha,
            "git_commit": git_commit,
            "dirty": dirty,
            "inputs_sha256": inputs_sha,
            "emitted_at": emitted_at,
        },
    }
    dump(reg, cfg)
    flag = "" if canonical else ("  [NEEDS POLICY]" if pol is None else "  [non-canonical]")
    print(f"  canon.emit {key} = {display}{flag}")
    return key


def stale_entries(reg: dict | None = None, cfg: CanonConfig | None = None) -> dict[str, str]:
    """Entradas cuyo script emisor cambió de contenido desde que se emitieron.

    Devuelve ``{key: motivo}``. Vacío = todo fresco.
    """
    cfg = cfg or load_config()
    reg = reg if reg is not None else load(cfg)
    out: dict[str, str] = {}
    for key, e in reg.get("entries", {}).items():
        prov = e.get("provenance", {})
        current = _sha256(cfg.root / prov.get("script", ""))
        if current is None:
            out[key] = f"script emisor ausente: {prov.get('script')}"
        elif prov.get("script_sha256") != current:
            out[key] = (
                f"script {prov.get('script')} cambió desde la emisión "
                "(re-corre el emisor y commitea el registro)"
            )
    return out
