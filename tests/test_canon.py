"""Tests del registro canónico.

Ejercitan las tres patas del validador (cita-vs-canónico, variante, frescura) y las
guardas anti-evasión sobre un registro sintético y docs temporales — nunca sobre el
registro real del repo.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

from inwatch.canon import check as check_mod
from inwatch.canon.config import CanonConfig, find_root
from inwatch.canon.registry import resolve_policy, round_canonical


@pytest.fixture
def cfg(tmp_path: Path) -> CanonConfig:
    """Proyecto sintético con registro propio y un solo glob vigilado."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\n", encoding="utf-8")
    (tmp_path / "analysis").mkdir()
    registry = tmp_path / "registry" / "canonical_numbers.json"
    registry.parent.mkdir()
    emitter = tmp_path / "emit.py"
    emitter.write_text("# emisor sintético\n", encoding="utf-8")
    from inwatch.canon.registry import _sha256

    registry.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "policy": {
                    "multiplier.*": {
                        "canonical_variant": "victim",
                        "decimals": 1,
                        "round_mode": "half_up",
                    }
                },
                "entries": {
                    "multiplier.robo.victim": {
                        "value": 4.627059,
                        "display": "4.6",
                        "unit": "adim.",
                        "estimator": "pooled",
                        "family": "multiplier.robo",
                        "variant": "victim",
                        "canonical": True,
                        "needs_policy": False,
                        "provenance": {
                            "script": "emit.py",
                            "script_sha256": _sha256(emitter),
                            "git_commit": "abc1234",
                            "dirty": False,
                            "inputs_sha256": {},
                            "emitted_at": "2026-08-04T00:00:00-05:00",
                        },
                    },
                    "multiplier.robo.incident": {
                        "value": 17.0,
                        "display": "17.0",
                        "unit": "adim.",
                        "estimator": "pooled",
                        "family": "multiplier.robo",
                        "variant": "incident",
                        "canonical": False,
                        "needs_policy": False,
                        "provenance": {
                            "script": "emit.py",
                            "script_sha256": _sha256(emitter),
                            "git_commit": "abc1234",
                            "dirty": False,
                            "inputs_sha256": {},
                            "emitted_at": "2026-08-04T00:00:00-05:00",
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return CanonConfig(root=tmp_path, registry=registry, watched=("analysis/*.md",))


def _doc(cfg: CanonConfig, body: str) -> None:
    (cfg.root / "analysis" / "r.md").write_text(textwrap.dedent(body), encoding="utf-8")


def _fails(cfg: CanonConfig) -> list[str]:
    from inwatch.canon.registry import load

    files = check_mod.watched_files(cfg)
    return check_mod.check(files, load(cfg), None, cfg)


# ─── pata 1: cita vs canónico ─────────────────────────────────────────────────
def test_cita_correcta_por_familia_pasa(cfg):
    _doc(cfg, "<!-- CANON: multiplier.robo = 4.6 -->\n")
    assert _fails(cfg) == []


def test_cita_incorrecta_falla(cfg):
    _doc(cfg, "<!-- CANON: multiplier.robo = 5.5 -->\n")
    assert any("cita 5.5" in f for f in _fails(cfg))


def test_key_desconocida_falla(cfg):
    _doc(cfg, "<!-- CANON: multiplier.inexistente = 1.0 -->\n")
    assert any("desconocida" in f for f in _fails(cfg))


# ─── pata 2: variante ─────────────────────────────────────────────────────────
def test_variante_no_canonica_sin_flag_falla(cfg):
    _doc(cfg, "<!-- CANON: multiplier.robo.incident = 17.0 -->\n")
    assert any("NO canónica" in f for f in _fails(cfg))


def test_variante_no_canonica_con_flag_pasa(cfg):
    _doc(cfg, "<!-- CANON: multiplier.robo.incident = 17.0 variant-ok -->\n")
    assert _fails(cfg) == []


# ─── guardas anti-evasión ─────────────────────────────────────────────────────
def test_exceso_de_decimales_falla(cfg):
    """4.63 cae en la cuenca de redondeo de 4.6 — sin esta guarda pasaría."""
    _doc(cfg, "<!-- CANON: multiplier.robo = 4.63 -->\n")
    assert any("más decimales" in f for f in _fails(cfg))


def test_ancla_malformada_falla_en_vez_de_saltarse(cfg):
    _doc(cfg, "<!-- canon multiplier.robo == 4.6 -->\n")
    assert any("malformada" in f for f in _fails(cfg))


def test_prefijo_multiplicativo_se_normaliza(cfg):
    _doc(cfg, "<!-- CANON: multiplier.robo = ×4.6 -->\n")
    assert _fails(cfg) == []


def test_emisor_cambiado_marca_stale(cfg):
    (cfg.root / "emit.py").write_text("# emisor modificado\n", encoding="utf-8")
    from inwatch.canon.registry import load, stale_entries

    stale = stale_entries(load(cfg), cfg)
    assert "multiplier.robo.victim" in stale


def test_emisor_staged_sin_reemitir_bloquea(cfg):
    (cfg.root / "emit.py").write_text("# emisor modificado\n", encoding="utf-8")
    from inwatch.canon.registry import load

    fails = check_mod.staged_emitter_fails(load(cfg), {cfg.root / "emit.py"}, cfg)
    assert fails and "sin re-emitir" in fails[0]


# ─── procedencia: el guard anti-churn no debe congelar lo provisional ─────────
@pytest.fixture
def git_cfg(tmp_path: Path) -> CanonConfig:
    """Proyecto sintético **con git**, para ejercitar `git_commit`/`dirty` de verdad.

    El `cfg` de arriba no es un repo: ahí `_git` devuelve None y la procedencia sale
    siempre `uncommitted`/`False`, que es justo lo que este bloque necesita medir.
    """
    _git_run(tmp_path, "init", "-q")
    _git_run(tmp_path, "config", "user.email", "t@t.t")
    _git_run(tmp_path, "config", "user.name", "t")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\n", encoding="utf-8")
    registry = tmp_path / "registry" / "canonical_numbers.json"
    registry.parent.mkdir()
    _git_run(tmp_path, "add", "-A")
    _git_run(tmp_path, "commit", "-qm", "base")
    return CanonConfig(root=tmp_path, registry=registry, watched=("analysis/*.md",))


def _git_run(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)


def _emit(cfg: CanonConfig, value: float = 1.0) -> dict:
    from inwatch.canon.registry import emit, load

    emit(
        "f",
        value,
        variant="v",
        unit="u",
        estimator="e",
        inputs=[],
        script=str(cfg.root / "emit.py"),
        cfg=cfg,
    )
    return load(cfg)["entries"]["f.v"]["provenance"]


def test_procedencia_provisional_se_corrige_al_commitear_el_emisor(git_cfg):
    """El flujo natural es escribir el emisor, correrlo, y commitear todo junto.

    Esa primera corrida graba `dirty: true` y el HEAD ANTERIOR — un commit donde el
    emisor todavía no existía. Al commitear y re-correr, nada material cambió (el sha
    es del contenido, no del commit), así que la rama 'unchanged' preservaba esa
    procedencia provisional PARA SIEMPRE. Acá se exige que converja.
    """
    (git_cfg.root / "emit.py").write_text("# emisor\n", encoding="utf-8")
    provisional = _emit(git_cfg)
    assert provisional["dirty"] is True

    _git_run(git_cfg.root, "add", "emit.py")
    _git_run(git_cfg.root, "commit", "-qm", "agrega el emisor")
    corregida = _emit(git_cfg)

    assert corregida["dirty"] is False
    assert corregida["git_commit"] != provisional["git_commit"]
    # el valor no cambió: el momento de emisión sigue siendo el de la primera corrida
    assert corregida["emitted_at"] == provisional["emitted_at"]


def test_reemision_desde_arbol_limpio_no_produce_churn(git_cfg):
    """La razón de ser del guard: un re-run no-op no puede ensuciar el registro."""
    (git_cfg.root / "emit.py").write_text("# emisor\n", encoding="utf-8")
    _git_run(git_cfg.root, "add", "emit.py")
    _git_run(git_cfg.root, "commit", "-qm", "agrega el emisor")

    assert _emit(git_cfg) == _emit(git_cfg)


def test_reemision_con_emisor_aun_sucio_no_produce_churn(git_cfg):
    """Durante el desarrollo se re-corre muchas veces con el árbol sucio.

    Recalcular procedencia en ese caso no debe reintroducir el churn que el guard
    existe para evitar: mismo HEAD y mismo estado sucio ⇒ misma entrada.
    """
    (git_cfg.root / "emit.py").write_text("# emisor\n", encoding="utf-8")

    assert _emit(git_cfg) == _emit(git_cfg)


# ─── policy: exacta > patrón más largo ────────────────────────────────────────
def test_policy_exacta_gana_sobre_patron():
    policy = {"r.*": {"decimals": 2}, "r.estafa": {"decimals": 4}}
    assert resolve_policy("r.estafa", policy)["decimals"] == 4
    assert resolve_policy("r.robo", policy)["decimals"] == 2


def test_entre_patrones_gana_el_mas_largo():
    policy = {"r.*": {"decimals": 2}, "r.sub.*": {"decimals": 6}}
    assert resolve_policy("r.sub.x", policy)["decimals"] == 6


def test_redondeo_respeta_el_modo():
    assert str(round_canonical(4.65, 1, "half_up")) == "4.7"
    assert str(round_canonical(4.65, 1, "floor")) == "4.6"


# ─── config ───────────────────────────────────────────────────────────────────
def test_find_root_sube_hasta_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\n", encoding="utf-8")
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert find_root(deep) == tmp_path.resolve()
