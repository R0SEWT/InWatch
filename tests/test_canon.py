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


def _modificar_emisor(cfg):
    """Cambia el emisor con otro tamaño, no solo otro contenido.

    `_sha256` memoiza por (ruta, tamaño, mtime_ns). "# emisor sintético" y
    "# emisor modificado" pesan lo mismo (20 bytes), y en ext4 dos escrituras seguidas
    caen en el mismo tick de mtime: la clave coincidía, el caché devolvía el hash viejo
    y el test fallaba en unas máquinas y pasaba en otras.
    """
    (cfg.root / "emit.py").write_text("# emisor modificado, con otra longitud\n", encoding="utf-8")


def test_emisor_cambiado_marca_stale(cfg):
    _modificar_emisor(cfg)
    from inwatch.canon.registry import load, stale_entries

    stale = stale_entries(load(cfg), cfg)
    assert "multiplier.robo.victim" in stale


def test_emisor_staged_sin_reemitir_bloquea(cfg):
    _modificar_emisor(cfg)
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


def test_una_policy_de_muchos_decimales_no_pierde_precision_al_guardar(git_cfg):
    """El `value` guardado no puede ser más grueso que el `display` que la policy pide.

    `emit` redondeaba `value` a 6 decimales fijos. Con una policy de 9 —las hay, y a
    propósito: son las cifras que sostienen una afirmación de conservación— el valor se
    guardaba truncado mientras `display` salía del número entero. `check` recomputa desde
    `value`, así que el linter terminaba fallando contra la salida de su propio emisor.
    """
    (git_cfg.root / "emit.py").write_text("# emisor\n", encoding="utf-8")
    reg = {
        "schema_version": 1,
        "policy": {"f": {"canonical_variant": "v", "decimals": 9, "round_mode": "half_up"}},
        "entries": {},
    }
    git_cfg.registry.write_text(json.dumps(reg), encoding="utf-8")

    from inwatch.canon.registry import load, round_canonical

    _emit(git_cfg, value=9.9e-7)
    entrada = load(git_cfg)["entries"]["f.v"]

    assert entrada["display"] == "0.000000990"
    # y lo esencial: recomputar desde el `value` guardado devuelve el mismo display
    assert f"{round_canonical(entrada['value'], 9, 'half_up'):.9f}" == entrada["display"]


def test_reemision_con_emisor_aun_sucio_no_produce_churn(git_cfg):
    """Durante el desarrollo se re-corre muchas veces con el árbol sucio.

    Recalcular procedencia en ese caso no debe reintroducir el churn que el guard
    existe para evitar: mismo HEAD y mismo estado sucio ⇒ misma entrada.
    """
    (git_cfg.root / "emit.py").write_text("# emisor\n", encoding="utf-8")

    assert _emit(git_cfg) == _emit(git_cfg)


# ─── procedencia: un commit de rama muere con el squash-merge (inwatch-1r4) ───
@pytest.fixture
def flow_cfg(git_cfg: CanonConfig, tmp_path_factory) -> CanonConfig:
    """`git_cfg` con un `origin` de verdad y la base publicada en `origin/develop`."""
    remoto = tmp_path_factory.mktemp("origin") / "origin.git"
    _git_run(git_cfg.root, "init", "-q", "--bare", str(remoto))
    _git_run(git_cfg.root, "remote", "add", "origin", str(remoto))
    _git_run(git_cfg.root, "branch", "-M", "develop")
    _git_run(git_cfg.root, "push", "-q", "origin", "develop")
    return git_cfg


def _commit_de_rama(cfg: CanonConfig) -> None:
    _git_run(cfg.root, "checkout", "-qb", "feat/x")
    (cfg.root / "emit.py").write_text("# emisor\n", encoding="utf-8")
    _git_run(cfg.root, "add", "emit.py")
    _git_run(cfg.root, "commit", "-qm", "agrega el emisor")


def _es_ancestro(cfg: CanonConfig, commit: str, ref: str) -> bool:
    r = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, ref], cwd=cfg.root, capture_output=True
    )
    return r.returncode == 0


def test_emitir_desde_un_commit_de_rama_avisa(flow_cfg, capsys):
    """El commit de una rama no sobrevive al squash: la procedencia quedaría colgando."""
    _commit_de_rama(flow_cfg)
    prov = _emit(flow_cfg)

    err = capsys.readouterr().err
    assert prov["git_commit"] in err
    assert "origin/develop" in err


def test_emitir_desde_develop_publicado_no_avisa(flow_cfg, capsys):
    (flow_cfg.root / "emit.py").write_text("# emisor\n", encoding="utf-8")
    _git_run(flow_cfg.root, "add", "emit.py")
    _git_run(flow_cfg.root, "commit", "-qm", "agrega el emisor")
    _git_run(flow_cfg.root, "push", "-q", "origin", "develop")
    _emit(flow_cfg)

    assert capsys.readouterr().err == ""


def test_sin_remoto_no_avisa(git_cfg, capsys):
    """Sin `origin` no hay contra qué comparar: callar es mejor que un falso positivo."""
    (git_cfg.root / "emit.py").write_text("# emisor\n", encoding="utf-8")
    _git_run(git_cfg.root, "add", "emit.py")
    _git_run(git_cfg.root, "commit", "-qm", "agrega el emisor")
    _emit(git_cfg)

    assert capsys.readouterr().err == ""


def test_tras_el_squash_la_procedencia_se_resella_con_un_commit_vivo(flow_cfg):
    """El criterio de aceptación: emitir en la rama, squashear, re-correr en develop.

    Nada material cambió, así que la rama 'unchanged' preservaba el commit de la rama —
    que el squash dejó fuera de toda rama estable. Como con `dirty`, una procedencia
    que no está en origin es provisional y se re-sella hasta que lo esté.
    """
    _commit_de_rama(flow_cfg)
    de_rama = _emit(flow_cfg)

    _git_run(flow_cfg.root, "checkout", "-q", "develop")
    _git_run(flow_cfg.root, "merge", "-q", "--squash", "feat/x")
    _git_run(flow_cfg.root, "commit", "-qm", "squash (#1)")
    _git_run(flow_cfg.root, "push", "-q", "origin", "develop")
    _git_run(flow_cfg.root, "branch", "-qD", "feat/x")
    assert not _es_ancestro(flow_cfg, de_rama["git_commit"], "origin/develop")

    viva = _emit(flow_cfg)
    assert _es_ancestro(flow_cfg, viva["git_commit"], "origin/develop")
    assert viva["emitted_at"] == de_rama["emitted_at"]
    # y ya en develop, re-correr no produce churn
    assert _emit(flow_cfg) == viva


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


# ─── inputs fuera de la raíz: alias de origen, no ruta de una laptop (inwatch-8sm) ──
def _proyecto_con_catalogo(tmp_path: Path) -> tuple[CanonConfig, Path]:
    """Repo sintético cuyo catálogo de fuentes declara un origen fuera de la raíz."""
    raiz = tmp_path / "repo"
    origen = tmp_path / "infelix"
    (origen / "data").mkdir(parents=True)
    insumo = origen / "data" / "insumo.csv"
    insumo.write_text("a,b\n1,2\n", encoding="utf-8")
    (raiz / "registry").mkdir(parents=True)
    (raiz / "pyproject.toml").write_text("[project]\nname='t'\n", encoding="utf-8")
    (raiz / "registry" / "fuentes.toml").write_text(
        f'[origenes]\ninfelix = "{origen}"\n', encoding="utf-8"
    )
    registry = raiz / "registry" / "canonical_numbers.json"
    return CanonConfig(root=raiz, registry=registry, watched=("analysis/*.md",)), insumo


def test_input_de_un_origen_se_registra_como_alias_relativo(tmp_path):
    """El registro está versionado: una clave `/home/<usuario>/...` lo ata a una máquina."""
    from inwatch.canon.registry import emit, load

    cfg, insumo = _proyecto_con_catalogo(tmp_path)
    emit("f", 1.0, variant="v", unit="u", estimator="e", inputs=[insumo],
         script=str(cfg.root / "emit.py"), cfg=cfg)
    claves = list(load(cfg)["entries"]["f.v"]["provenance"]["inputs_sha256"])
    assert claves == ["infelix:data/insumo.csv"]


def test_input_fuera_de_todo_origen_conserva_la_ruta(tmp_path):
    """Sin origen que lo cubra no hay alias honesto: se deja la ruta tal cual."""
    from inwatch.canon.registry import emit, load

    cfg, _ = _proyecto_con_catalogo(tmp_path)
    suelto = tmp_path / "suelto.csv"
    suelto.write_text("x\n", encoding="utf-8")
    emit("f", 1.0, variant="v", unit="u", estimator="e", inputs=[suelto],
         script=str(cfg.root / "emit.py"), cfg=cfg)
    claves = list(load(cfg)["entries"]["f.v"]["provenance"]["inputs_sha256"])
    assert claves == [str(suelto)]
