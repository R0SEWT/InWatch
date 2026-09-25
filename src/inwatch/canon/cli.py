"""CLI del registro canónico: ``canon show | check | audit``."""

from __future__ import annotations

import argparse

from .check import run as run_check
from .config import load_config
from .registry import absent_inputs, load, stale_entries


def _show() -> int:
    cfg = load_config()
    reg = load(cfg)
    entries = reg.get("entries", {})
    policy = reg.get("policy", {})
    rel = cfg.registry.relative_to(cfg.root)
    print(f"Registro: {rel}  ·  {len(entries)} entradas  ·  {len(policy)} familias en policy")
    stale = stale_entries(reg, cfg)
    for key in sorted(entries):
        e = entries[key]
        tags = []
        if e.get("canonical"):
            tags.append("canónico")
        if e.get("needs_policy"):
            tags.append("NEEDS-POLICY")
        if key in stale:
            tags.append("STALE")
        suffix = f"  ({', '.join(tags)})" if tags else ""
        print(f"  {key:<42} {e.get('display'):>10}{suffix}")
    ausentes = absent_inputs(reg, cfg)
    if ausentes:
        faltan = sorted({i for lista in ausentes.values() for i in lista})
        print(
            f"\nℹ {len(ausentes)} entrada(s) con insumos que no están en esta máquina "
            f"({len(faltan)} archivo(s)); sin el archivo no se sabe si cambiaron:"
        )
        for insumo in faltan:
            print(f"  {insumo}")
    if stale:
        print(f"\n⚠ {len(stale)} entrada(s) STALE — el emisor o un insumo cambió sin re-emitir:")
        for key, why in sorted(stale.items()):
            print(f"  {key}: {why}")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="canon", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="resumen del registro (sale 1 si hay entradas stale)")
    sub.add_parser("check", help="valida todos los docs vigilados")
    sub.add_parser("staged", help="valida solo archivos staged (pre-commit)")
    sub.add_parser("audit", help="heurístico de literales sin ancla (nunca gatea)")
    args = ap.parse_args()

    if args.cmd == "show":
        return _show()
    return run_check({"check": "all", "staged": "staged", "audit": "audit"}[args.cmd])


if __name__ == "__main__":
    raise SystemExit(main())
