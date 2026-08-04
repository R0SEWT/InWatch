"""Registro de números canónicos: emisión, validación y consumo.

Uso desde un emisor del pipeline::

    from inwatch import canon

    canon.emit("multiplier.robo_hurto_callejero", lat / obs,
               variant="victim", unit="latente/observado (adim.)",
               estimator="pooled Σλ*/Σy 2018-2024, r̂ EB victim-level",
               inputs=[rate_file], script=__file__)

Uso desde un notebook o una capa de presentación::

    from inwatch import canon
    canon.display("multiplier.robo_hurto_callejero")   # "4.6" — ya redondeado por policy
"""

from __future__ import annotations

# Se exporta como `check_docs`, no `check`: un nombre de función que ensombrece al
# submódulo `inwatch.canon.check` rompe `from inwatch.canon import check` de forma
# silenciosa y confusa.
from .check import run as check_docs
from .config import CanonConfig, CanonConfigError, load_config
from .registry import (
    display_str,
    dump,
    emit,
    load,
    resolve_policy,
    round_canonical,
    stale_entries,
)

__all__ = [
    "CanonConfig",
    "CanonConfigError",
    "check_docs",
    "display",
    "display_str",
    "dump",
    "emit",
    "entry",
    "load",
    "load_config",
    "resolve_policy",
    "round_canonical",
    "stale_entries",
    "value",
]


def entry(key: str, *, cfg: CanonConfig | None = None) -> dict:
    """Entrada del registro por key completa o por familia (resuelve la canónica).

    Falla fuerte si no existe: una UI que muestra un número mudo es peor que una que
    no compila. Es el mismo contrato que ``canon.typ`` tiene en el repo de origen.
    """
    reg = load(cfg)
    entries = reg.get("entries", {})
    if key in entries:
        return entries[key]
    pol = resolve_policy(key, reg.get("policy", {}))
    if pol is not None:
        full = f"{key}.{pol.get('canonical_variant')}"
        if full in entries:
            return entries[full]
    raise KeyError(f"canon: key desconocida '{key}' (ni entrada ni familia con policy)")


def display(key: str, *, cfg: CanonConfig | None = None) -> str:
    """String ya redondeado por la policy. La UI no decide precisión."""
    return entry(key, cfg=cfg)["display"]


def value(key: str, *, cfg: CanonConfig | None = None) -> float:
    """Valor float completo, para cálculo — no para mostrar."""
    return entry(key, cfg=cfg)["value"]
