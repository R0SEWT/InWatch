"""CLI del catálogo: ``fuentes estado | ruta | exportar | sync | publicar``."""

from __future__ import annotations

import argparse
import sys

from . import lake
from .catalogo import CatalogoInvalido, cargar_catalogo
from .config import load_config
from .exportar import exportar
from .resolucion import FuenteDesconocida, FuenteNoEncontrada, resolver

ERRORES = (
    CatalogoInvalido,
    FuenteDesconocida,
    FuenteNoEncontrada,
    lake.LakeNoConfigurado,
    lake.LakeInaccesible,
    lake.ConflictoLake,
    lake.IntegridadLake,
)


def _estado() -> int:
    cfg = load_config()
    cat = cargar_catalogo(cfg)
    try:
        remoto = lake.remoto_desde(cat)
    except lake.LakeNoConfigurado as exc:
        print(f"⚠ {exc}")
        remoto = None
    filas = lake.estado(remoto, cfg=cfg)
    for f in filas:
        marca = "  ← transición: falta subir a bocho" if f.es_transicion else ""
        print(f"  {f.nombre:<34} {f.origen:<10} bocho={f.remoto:<14}{marca}")
    transicion = sum(f.es_transicion for f in filas)
    faltan = sum(f.origen == "falta" for f in filas)
    print(f"\n{len(filas)} fuentes · {transicion} en transición · {faltan} sin resolver")
    return 0


def _remoto():
    cfg = load_config()
    remoto = lake.remoto_desde(cargar_catalogo(cfg))
    if not remoto.disponible():
        raise lake.LakeInaccesible(f"bocho ({remoto.host}) no responde por SSH")
    return cfg, remoto


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fuentes", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("estado", help="origen resuelto de cada fuente y su situación en bocho")
    p = sub.add_parser("ruta", help="imprime la ruta resuelta de una fuente")
    p.add_argument("nombre")
    p = sub.add_parser("exportar", help="materializa fuentes de transición en data/bronze/")
    p.add_argument("nombres", nargs="+")
    p = sub.add_parser("sync", help="baja de bocho a data/lake/ (todas si no se nombra ninguna)")
    p.add_argument("nombres", nargs="*")
    p = sub.add_parser("publicar", help="sube fuentes a bocho; nunca sobrescribe")
    p.add_argument("nombres", nargs="+")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "estado":
            return _estado()
        if args.cmd == "ruta":
            print(resolver(args.nombre, sha=False).ruta)
            return 0
        if args.cmd == "exportar":
            for nombre in args.nombres:
                r = exportar(nombre)
                print(f"  {nombre}: {r.ruta} (sha {r.sha256[:12]}…)")
            return 0
        cfg, remoto = _remoto()
        if args.cmd == "sync":
            nombres = args.nombres or [
                n for n, f in sorted(cargar_catalogo(cfg).fuentes.items()) if f.lake
            ]
            for nombre in nombres:
                print(f"  {nombre}: {lake.sync(nombre, remoto, cfg=cfg)}")
            return 0
        for nombre in args.nombres:
            print(f"  {nombre}: {lake.publicar(nombre, remoto, cfg=cfg)}")
        return 0
    except ERRORES as exc:
        print(f"fuentes: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
