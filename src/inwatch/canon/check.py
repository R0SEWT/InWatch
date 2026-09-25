"""Validador de números canónicos — el linter del hardening.

Verifica que cada número citado en un doc con ancla ``CANON:`` coincide con el
registro. Tres patas:

  1. cita-vs-canónico   citado == round(canónico, decimals) según la policy
  2. variante           citar una variante NO canónica exige ``variant-ok`` explícito
  3. frescura           una key cuyo emisor o insumo cambió sin re-emitir bloquea si
                        un doc staged la cita (un insumo ausente no cuenta)

Anclas — el número solo se checa donde un humano declaró el binding en un comentario::

    Markdown   <!-- CANON: multiplier.robo_hurto_callejero = 4.6 -->
    Python     # CANON: r_pooled.robo_hurto_callejero = 0.224
    non-canon  # CANON: multiplier.robo_hurto_callejero = 17 variant-ok

Portado de ``infelix/scripts/check_canon.py``, preservando sus cinco guardas
anti-evasión: anclas malformadas fallan en vez de saltarse, exceso de decimales
falla, comparación exacta en ``Decimal``, emisor staged sin re-emitir bloquea, y
registro staged escala la validación a todos los docs vigilados.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .config import CanonConfig, load_config
from .registry import (
    DEFAULT_DECIMALS,
    DEFAULT_ROUND_MODE,
    resolve_policy,
    round_canonical,
    stale_entries,
)

# CANON: <key> = <valor> [variant-ok]  — dentro de cualquier estilo de comentario.
ANCHOR_RE = re.compile(
    r"CANON:\s*(?P<key>[\w.\-]+)\s*=\s*(?P<val>[~×xX]?\s*[-\d.,]+)(?P<flag>\s+variant-ok)?",
)
# Literal numérico "portante" para --audit (multiplicadores/tasas, no años ni refs).
NUMISH_RE = re.compile(r"(?<![\w.])[×xX~]?\s*\d+\.\d+")
# Una línea que "quiso" ser ancla pero no parsea NO debe saltarse en silencio.
MALFORMED_RE = re.compile(r"(?i)\bcanon\b")


def watched_files(cfg: CanonConfig) -> list[Path]:
    out: list[Path] = []
    for pat in cfg.watched:
        out.extend(cfg.root.glob(pat))
    return sorted({p for p in out if p.is_file()})


def staged_files(cfg: CanonConfig) -> list[Path]:
    res = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=cfg.root,
        capture_output=True,
        text=True,
    )
    return [
        p
        for line in res.stdout.splitlines()
        if line.strip()
        if (p := cfg.root / line).is_file()
    ]


def _parse_cited(raw: str) -> Decimal | None:
    """Normaliza el valor citado: quita ×, ~, x y espacios; parsea a Decimal."""
    s = raw.strip().lstrip("×xX~").strip().replace(" ", "")
    if "," in s and "." in s:  # coma como separador de miles
        s = s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _loc(cfg: CanonConfig, f: Path, lineno: int) -> str:
    try:
        return f"{f.relative_to(cfg.root)}:{lineno}"
    except ValueError:
        return f"{f}:{lineno}"


def find_anchors(files: list[Path]) -> tuple[list[tuple], list[tuple]]:
    """-> (anchors, malformed).

    anchors:   [(file, lineno, key, cited_raw, has_variant_ok)]
    malformed: [(file, lineno, line)] — líneas con intención de ancla que no parsean.
    """
    anchors, malformed = [], []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            matched = False
            for m in ANCHOR_RE.finditer(line):
                anchors.append((f, i, m.group("key"), m.group("val"), bool(m.group("flag"))))
                matched = True
            if not matched and "=" in line and MALFORMED_RE.search(line):
                malformed.append((f, i, line.strip()))
    return anchors, malformed


def _resolve(key: str, entries: dict, policy: dict) -> tuple[dict | None, str | None, bool]:
    """Resuelve una key de ancla a su entrada.

    ``family.variant`` → entrada directa. ``family`` → la variante canónica de la
    policy, marcando ``by_family=True`` (citar la familia ya elige lo correcto).
    """
    if key in entries:
        return entries[key], key, False
    pol = resolve_policy(key, policy)
    if pol is not None:
        full = f"{key}.{pol.get('canonical_variant')}"
        if full in entries:
            return entries[full], full, True
    return None, None, False


def check(
    files: list[Path],
    reg: dict,
    staged_set: set[Path] | None,
    cfg: CanonConfig,
) -> list[str]:
    """Devuelve la lista de fallos (vacía = todo OK)."""
    entries = reg.get("entries", {})
    policy = reg.get("policy", {})
    stale = stale_entries(reg, cfg)
    fails: list[str] = []

    anchors, malformed = find_anchors(files)
    for f, lineno, line in malformed:
        fails.append(
            f"{_loc(cfg, f, lineno)} · ancla CANON malformada "
            f"(parece intención de ancla, no parsea): {line}"
        )

    for f, lineno, key, cited_raw, variant_ok in anchors:
        loc = _loc(cfg, f, lineno)
        entry, rkey, by_family = _resolve(key, entries, policy)
        if entry is None:
            fails.append(
                f"{loc} · CANON key desconocida: '{key}' "
                "(no está en el registro ni en la policy)"
            )
            continue
        if entry.get("needs_policy"):
            fails.append(
                f"{loc} · '{key}' sin policy declarada "
                f"(agrega policy['{entry.get('family')}'])"
            )
            continue
        if not by_family and not entry.get("canonical") and not variant_ok:
            fails.append(
                f"{loc} · '{key}' es variante NO canónica; cita la familia canónica "
                "o marca 'variant-ok' a sabiendas"
            )
            continue
        key = rkey

        fam = resolve_policy(entry.get("family", ""), policy) or {}
        decimals = fam.get("decimals", DEFAULT_DECIMALS)
        mode = fam.get("round_mode", DEFAULT_ROUND_MODE)
        cited = _parse_cited(cited_raw)
        if cited is None:
            fails.append(f"{loc} · valor citado ilegible: '{cited_raw.strip()}'")
            continue
        canonical = round_canonical(entry["value"], decimals, mode)
        # Comparación EXACTA a la precisión declarada: sin esto un citado dentro de la
        # cuenca de redondeo (4.55 → 4.6) pasaría, que es justo el drift del incidente.
        if max(0, -cited.as_tuple().exponent) > decimals:
            fails.append(
                f"{loc} · '{key}' citado con más decimales ({cited}) que la policy "
                f"({decimals} dp); usa la forma canónica exacta {canonical}"
            )
            continue
        if cited != canonical:
            prov = entry.get("provenance", {})
            fails.append(
                f"{loc} · '{key}' cita {cited} pero el canónico es {canonical} "
                f"(emitido en {prov.get('git_commit')} desde {prov.get('script')})"
            )
            continue

        if key in stale:
            msg = f"{loc} · '{key}' STALE — {stale[key]}"
            if staged_set is not None and f in staged_set:
                fails.append(msg)
            else:
                print(f"  ⚠ aviso (stale, no bloquea en este modo): {msg}", file=sys.stderr)

    return fails


def audit(files: list[Path], cfg: CanonConfig) -> None:
    """Heurístico (nunca gatea): literales numéricos sin ancla CANON cercana."""
    print("=== AUDIT: literales numéricos sin ancla CANON cercana (heurístico, ruidoso) ===")
    total = 0
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        hits = []
        for i, line in enumerate(lines):
            if NUMISH_RE.search(line) and "CANON:" not in line:
                prev = lines[i - 1] if i else ""
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if "CANON:" not in prev and "CANON:" not in nxt:
                    hits.append(i + 1)
        if hits:
            total += len(hits)
            print(f"  {f.relative_to(cfg.root)}: {len(hits)} líneas sin ancla (p.ej. L{hits[0]})")
    print(f"→ {total} líneas candidatas. Ancla las portantes; el resto queda humano.")


def staged_emitter_fails(reg: dict, staged: set[Path], cfg: CanonConfig) -> list[str]:
    """Si un emisor está staged pero sus entradas quedaron stale, bloquea.

    Es el replay exacto del incidente original: el pivote se commiteó y la detección
    se difirió semanas.
    """
    entries = reg.get("entries", {})
    emitter_rels = {e.get("provenance", {}).get("script") for e in entries.values()}
    emitter_rels.discard(None)
    staged_rels = set()
    for p in staged:
        # Un path staged fuera de la raíz no es un emisor de este repo: se ignora.
        with contextlib.suppress(ValueError):
            staged_rels.add(str(p.relative_to(cfg.root)))
    if not (staged_emitters := emitter_rels & staged_rels):
        return []
    stale = stale_entries(reg, cfg)
    offending = sorted(
        k
        for k, e in entries.items()
        if e.get("provenance", {}).get("script") in staged_emitters and k in stale
    )
    if not offending:
        return []
    return [
        f"emisor staged sin re-emitir el registro ({', '.join(sorted(staged_emitters))}): "
        f"corre el pipeline y stagea {cfg.registry.name} [stale: {', '.join(offending)}]"
    ]


def run(mode: str, cfg: CanonConfig | None = None) -> int:
    """Ejecuta el validador. `mode` ∈ {'all', 'staged', 'audit'}. 0 = OK."""
    from .registry import load

    cfg = cfg or load_config()
    reg = load(cfg)
    watched = {p.resolve() for p in watched_files(cfg)}

    if mode == "audit":
        audit(sorted(watched), cfg)
        return 0

    extra_fails: list[str] = []
    if mode == "staged":
        staged = {p.resolve() for p in staged_files(cfg)}
        extra_fails = staged_emitter_fails(reg, staged, cfg)
        # Registro staged → un cambio de pipeline no puede colar docs viejos.
        if cfg.registry.resolve() in staged:
            print("  registro staged → validando TODOS los docs vigilados", file=sys.stderr)
            files = sorted(watched)
        else:
            files = sorted(staged & watched)
        staged_set = staged
    else:
        files = sorted(watched)
        staged_set = None

    fails = extra_fails + check(files, reg, staged_set, cfg)
    if fails:
        print(
            "✗ check_canon: números fuera de sincronía con el registro canónico:\n",
            file=sys.stderr,
        )
        for msg in fails:
            print(f"  ✗ {msg}", file=sys.stderr)
        print(
            f"\n{len(fails)} fallo(s). Corrige el doc, re-emite el registro, o ajusta la policy.",
            file=sys.stderr,
        )
        return 1
    n = len(find_anchors(files)[0])
    print(f"✓ check_canon: {n} ancla(s) verificada(s) contra el registro.")
    return 0
