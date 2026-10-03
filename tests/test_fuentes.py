"""Tests del catálogo de fuentes.

Todo corre sobre un proyecto sintético en ``tmp_path``: un repo con su catálogo, un
origen de solo lectura que imita a infelix y un lake remoto falso que imita a bocho.
Nunca se toca el catálogo real con datos, ni la red, ni bocho.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from inwatch import fuentes
from inwatch.fuentes import lake as lake_mod
from inwatch.fuentes import resolucion as resolucion_mod

SIN_ENTORNO: dict[str, str] = {}


@dataclass
class Proyecto:
    raiz: Path
    infelix: Path
    cfg: fuentes.FuentesConfig


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def proyecto(tmp_path: Path) -> Proyecto:
    raiz = tmp_path / "repo"
    (raiz / "registry").mkdir(parents=True)
    (raiz / "pyproject.toml").write_text(
        '[project]\nname = "t"\n\n[tool.inwatch.fuentes]\ncatalogo = "registry/fuentes.toml"\n',
        encoding="utf-8",
    )
    infelix = tmp_path / "infelix"
    (infelix / "data/silver/h3_features").mkdir(parents=True)
    (infelix / "data/silver/h3_features/h3_admin.parquet").write_bytes(b"admin-infelix")
    (infelix / "analysis").mkdir()
    (infelix / "analysis/matchdays.csv").write_text("vivo\n", encoding="utf-8")

    (raiz / "registry/fuentes.toml").write_text(
        textwrap.dedent(
            f"""
            [lake]
            remoto = "bocho:/srv/lake"

            [origenes]
            infelix = "{infelix}"

            [fuente.h3_admin]
            descripcion = "límites administrativos por celda"
            titularidad = "infelix (CC BY-NC-SA 4.0)"
            lake = "infelix/h3_features/h3_admin.parquet"
            transicion = ["infelix:data/silver/h3_features/h3_admin.parquet"]

            [fuente.matchdays_ancla]
            titularidad = "infelix (CC BY-NC-SA 4.0)"
            lake = "infelix/estadios/matchdays_ancla.csv"
            transicion = ["infelix:analysis/matchdays.csv"]
            git_ref = "PENDIENTE_EN_TEST"

            [fuente.solo_lake]
            titularidad = "propia"
            lake = "propia/solo_lake.parquet"

            [fuente.con_curado]
            titularidad = "INEI (dato público)"
            curado = "data/curado/limites.zip"
            lake = "admin/limites.zip"
            transicion = ["infelix:data/silver/h3_features/h3_admin.parquet"]

            [fuente.solo_curado]
            titularidad = "INEI (dato público)"
            curado = "data/curado/area.zip"
            """
        ),
        encoding="utf-8",
    )
    return Proyecto(raiz=raiz, infelix=infelix, cfg=fuentes.load_config(raiz))


def _escribir_lake(p: Proyecto, rel: str, data: bytes) -> Path:
    destino = p.cfg.lake / rel
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(data)
    return destino


# ─── catálogo ─────────────────────────────────────────────────────────────────
def test_config_lee_rutas_por_defecto_desde_pyproject(proyecto):
    cfg = proyecto.cfg
    assert cfg.root == proyecto.raiz.resolve()
    assert cfg.catalogo == cfg.root / "registry" / "fuentes.toml"
    assert cfg.lake == cfg.root / "data" / "lake"
    assert cfg.datos == cfg.root / "data"


def test_catalogo_lee_origenes_y_fuentes(proyecto):
    cat = fuentes.cargar_catalogo(proyecto.cfg, env=SIN_ENTORNO)
    assert cat.origenes["infelix"] == proyecto.infelix
    assert cat.remoto == "bocho:/srv/lake"
    admin = cat.fuentes["h3_admin"]
    assert admin.titularidad == "infelix (CC BY-NC-SA 4.0)"
    assert admin.lake == "infelix/h3_features/h3_admin.parquet"
    assert admin.transicion == ("infelix:data/silver/h3_features/h3_admin.parquet",)
    assert cat.fuentes["matchdays_ancla"].git_ref == "PENDIENTE_EN_TEST"


def test_origen_se_sobrescribe_por_entorno(proyecto, tmp_path):
    otra = tmp_path / "otra_copia"
    cat = fuentes.cargar_catalogo(proyecto.cfg, env={"INWATCH_ORIGEN_INFELIX": str(otra)})
    assert cat.origenes["infelix"] == otra


def test_remoto_se_sobrescribe_por_entorno(proyecto):
    cat = fuentes.cargar_catalogo(proyecto.cfg, env={"INWATCH_LAKE_REMOTO": "otro:/lake"})
    assert cat.remoto == "otro:/lake"


def test_transicion_con_origen_no_declarado_falla_al_cargar(proyecto):
    catalogo = proyecto.cfg.catalogo
    catalogo.write_text(
        catalogo.read_text(encoding="utf-8") + '\n[fuente.rota]\ntitularidad = "x"\n'
        'transicion = ["wachi:data/raw/LIMA.parquet"]\n',
        encoding="utf-8",
    )
    with pytest.raises(fuentes.CatalogoInvalido, match="wachi"):
        fuentes.cargar_catalogo(proyecto.cfg, env=SIN_ENTORNO)


def test_fuente_sin_titularidad_falla_al_cargar(proyecto):
    catalogo = proyecto.cfg.catalogo
    catalogo.write_text(
        catalogo.read_text(encoding="utf-8") + '\n[fuente.huerfana]\nlake = "x/y.parquet"\n',
        encoding="utf-8",
    )
    with pytest.raises(fuentes.CatalogoInvalido, match="titularidad"):
        fuentes.cargar_catalogo(proyecto.cfg, env=SIN_ENTORNO)


# ─── orden de resolución ──────────────────────────────────────────────────────
def test_sin_lake_resuelve_desde_transicion_y_lo_marca(proyecto):
    r = fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO, sha=False)
    assert r.ruta == proyecto.infelix / "data/silver/h3_features/h3_admin.parquet"
    assert r.origen == "infelix"
    assert r.es_transicion


def test_lake_gana_sobre_transicion(proyecto):
    copia = _escribir_lake(proyecto, "infelix/h3_features/h3_admin.parquet", b"admin-lake")
    r = fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO, sha=False)
    assert r.ruta == copia
    assert r.origen == "lake"
    assert not r.es_transicion


def test_datos_del_repo_gana_sobre_transicion_pero_no_sobre_lake(proyecto):
    exportado = proyecto.cfg.datos / "bronze/fuentes/h3_admin/h3_admin.parquet"
    exportado.parent.mkdir(parents=True)
    exportado.write_bytes(b"admin-exportado")
    r = fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO, sha=False)
    assert (r.ruta, r.origen) == (exportado, "exportado")

    copia = _escribir_lake(proyecto, "infelix/h3_features/h3_admin.parquet", b"admin-lake")
    r = fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO, sha=False)
    assert (r.ruta, r.origen) == (copia, "lake")


def test_curado_gana_sobre_transicion_y_no_es_transicion(proyecto):
    """Un insumo chico y versionado en el repo: existe al clonar, sin bocho ni infelix."""
    curado = proyecto.cfg.root / "data/curado/limites.zip"
    curado.parent.mkdir(parents=True)
    curado.write_bytes(b"limites-versionados")
    r = fuentes.resolver("con_curado", cfg=proyecto.cfg, env=SIN_ENTORNO, sha=False)
    assert (r.ruta, r.origen) == (curado, "curado")
    assert not r.es_transicion


def test_el_lake_gana_sobre_el_curado(proyecto):
    """Si bocho ya la sirve, esa es la copia viva; el curado es el respaldo del repo."""
    curado = proyecto.cfg.root / "data/curado/limites.zip"
    curado.parent.mkdir(parents=True)
    curado.write_bytes(b"limites-versionados")
    copia = _escribir_lake(proyecto, "admin/limites.zip", b"limites-lake")
    r = fuentes.resolver("con_curado", cfg=proyecto.cfg, env=SIN_ENTORNO, sha=False)
    assert (r.ruta, r.origen) == (copia, "lake")


def test_una_fuente_solo_curada_resuelve_sin_lake_ni_transicion(proyecto):
    """El caso real de distritos_limites_area_a: sin lake y sin origen del que exportar."""
    curado = proyecto.cfg.root / "data/curado/area.zip"
    curado.parent.mkdir(parents=True, exist_ok=True)
    curado.write_bytes(b"area-a")
    r = fuentes.resolver("solo_curado", cfg=proyecto.cfg, env=SIN_ENTORNO)
    assert (r.ruta, r.origen, r.sha256) == (curado, "curado", _sha(b"area-a"))


def test_una_fuente_solo_curada_que_falta_da_error_accionable(proyecto):
    with pytest.raises(fuentes.FuenteNoEncontrada, match="data/curado/area.zip"):
        fuentes.resolver("solo_curado", cfg=proyecto.cfg, env=SIN_ENTORNO)


def test_curado_debe_ser_relativo_al_repo(proyecto):
    catalogo = proyecto.cfg.catalogo
    catalogo.write_text(
        catalogo.read_text(encoding="utf-8").replace(
            'curado = "data/curado/limites.zip"', 'curado = "/etc/passwd"'
        ),
        encoding="utf-8",
    )
    with pytest.raises(fuentes.CatalogoInvalido, match="curado"):
        fuentes.cargar_catalogo(proyecto.cfg, env=SIN_ENTORNO)


def test_entorno_de_la_fuente_gana_sobre_todo(proyecto, tmp_path):
    _escribir_lake(proyecto, "infelix/h3_features/h3_admin.parquet", b"admin-lake")
    puntual = tmp_path / "puntual.parquet"
    puntual.write_bytes(b"admin-puntual")
    r = fuentes.resolver(
        "h3_admin", cfg=proyecto.cfg, env={"INWATCH_FUENTE_H3_ADMIN": str(puntual)}, sha=False
    )
    assert (r.ruta, r.origen) == (puntual, "entorno")


def test_ruta_es_el_atajo_de_resolver(proyecto):
    assert fuentes.ruta("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO) == (
        proyecto.infelix / "data/silver/h3_features/h3_admin.parquet"
    )


def test_fuente_desconocida_falla_con_su_nombre(proyecto):
    with pytest.raises(fuentes.FuenteDesconocida, match="no_existe"):
        fuentes.resolver("no_existe", cfg=proyecto.cfg, env=SIN_ENTORNO)


def test_sin_candidatos_el_error_lista_lo_probado_y_sugiere_sync(proyecto):
    with pytest.raises(fuentes.FuenteNoEncontrada) as exc:
        fuentes.resolver("solo_lake", cfg=proyecto.cfg, env=SIN_ENTORNO)
    msg = str(exc.value)
    assert str(proyecto.cfg.lake / "propia/solo_lake.parquet") in msg
    assert "fuentes sync solo_lake" in msg


def test_sin_candidatos_el_error_nombra_la_variable_de_la_fuente(proyecto):
    """En una máquina ajena la salida es la variable, no bocho (inwatch-92d.10)."""
    with pytest.raises(fuentes.FuenteNoEncontrada, match="INWATCH_FUENTE_SOLO_LAKE="):
        fuentes.resolver("solo_lake", cfg=proyecto.cfg, env=SIN_ENTORNO)


def test_sin_remoto_configurado_no_sugiere_sync(proyecto):
    catalogo = proyecto.cfg.catalogo
    catalogo.write_text(
        catalogo.read_text(encoding="utf-8").replace(
            'remoto = "bocho:/srv/lake"', 'remoto = "PENDIENTE"'
        ),
        encoding="utf-8",
    )
    with pytest.raises(fuentes.FuenteNoEncontrada) as exc:
        fuentes.resolver("solo_lake", cfg=proyecto.cfg, env=SIN_ENTORNO)
    msg = str(exc.value)
    assert "INWATCH_FUENTE_SOLO_LAKE=" in msg
    assert "fuentes sync" not in msg


def test_git_ref_no_resuelve_contra_el_archivo_vivo(proyecto):
    """Con `git_ref`, el archivo vivo del origen NO es la fuente: es otra versión.

    Resolverlo en silencio es exactamente el fallo de pulso-estadios: los CSV de hoy
    traen 94 filas que el ancla no vio.
    """
    with pytest.raises(fuentes.FuenteNoEncontrada, match="fuentes exportar matchdays_ancla"):
        fuentes.resolver("matchdays_ancla", cfg=proyecto.cfg, env=SIN_ENTORNO)


# ─── sha y su caché ───────────────────────────────────────────────────────────
def test_resolver_devuelve_el_sha_del_archivo(proyecto):
    r = fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO)
    assert r.sha256 == _sha(b"admin-infelix")


def test_el_sha_se_cachea_en_disco_y_no_se_recalcula(proyecto, monkeypatch):
    fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO)
    assert (proyecto.cfg.datos / ".cache" / "fuentes_sha.json").is_file()

    resolucion_mod._MEMO.clear()

    def prohibido(_path):
        raise AssertionError("re-hasheó un archivo que no cambió")

    monkeypatch.setattr(resolucion_mod, "_hash_archivo", prohibido)
    r = fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO)
    assert r.sha256 == _sha(b"admin-infelix")


def test_la_cache_se_invalida_con_el_mismo_tamanio_y_otro_mtime(proyecto):
    """Aísla el mtime: una clave que solo mirara el tamaño pasaría el test de abajo."""
    archivo = proyecto.infelix / "data/silver/h3_features/h3_admin.parquet"
    antes = fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO).sha256
    archivo.write_bytes(b"ADMIN-INFELIX")  # mismo tamaño, otro contenido
    st = archivo.stat()
    os.utime(archivo, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    assert fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO).sha256 != antes


def test_una_cache_corrupta_no_tumba_al_emisor(proyecto):
    """La caché es descartable: nunca debe poder matar a un loader a media corrida."""
    fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO)
    cache = proyecto.cfg.datos / ".cache" / "fuentes_sha.json"
    cache.write_text("{esto no es json", encoding="utf-8")
    resolucion_mod._MEMO.clear()
    assert fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO).sha256 == _sha(
        b"admin-infelix"
    )


def test_la_cache_usa_un_temporal_propio_por_proceso(proyecto):
    """Con un temporal de nombre fijo, dos procesos se publican el archivo a medio escribir."""
    fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO)
    cache = proyecto.cfg.datos / ".cache" / "fuentes_sha.json"
    ajenos = [p for p in cache.parent.iterdir() if p != cache]
    assert not ajenos, f"quedaron temporales sin limpiar: {ajenos}"
    assert resolucion_mod._temporal_de(cache) != resolucion_mod._temporal_de(cache, pid=1)


def test_la_cache_se_invalida_si_cambia_el_archivo(proyecto):
    archivo = proyecto.infelix / "data/silver/h3_features/h3_admin.parquet"
    antes = fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO).sha256
    archivo.write_bytes(b"admin-infelix-v2, con otro tamanio")
    st = archivo.stat()
    os.utime(archivo, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    despues = fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO).sha256
    assert antes != despues == _sha(b"admin-infelix-v2, con otro tamanio")


# ─── origen_de (inwatch-8sm) ──────────────────────────────────────────────────
def test_origen_de_expresa_rutas_de_un_origen_como_alias_relativo(proyecto):
    archivo = proyecto.infelix / "data/silver/h3_features/h3_admin.parquet"
    assert (
        fuentes.origen_de(archivo, cfg=proyecto.cfg, env=SIN_ENTORNO)
        == "infelix:data/silver/h3_features/h3_admin.parquet"
    )


def test_origen_de_expresa_el_lake_como_alias(proyecto):
    copia = _escribir_lake(proyecto, "infelix/h3_features/h3_admin.parquet", b"x")
    assert (
        fuentes.origen_de(copia, cfg=proyecto.cfg, env=SIN_ENTORNO)
        == "lake:infelix/h3_features/h3_admin.parquet"
    )


def test_origen_de_devuelve_none_fuera_de_todo_origen(proyecto, tmp_path):
    assert fuentes.origen_de(tmp_path / "suelto.csv", cfg=proyecto.cfg, env=SIN_ENTORNO) is None


# ─── exportar ─────────────────────────────────────────────────────────────────
def _solo_lectura(raiz: Path) -> None:
    for p in [raiz, *raiz.rglob("*")]:
        modo = p.stat().st_mode
        p.chmod(modo & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _escribible(raiz: Path) -> None:
    for p in [raiz, *raiz.rglob("*")]:
        p.chmod(p.stat().st_mode | stat.S_IWUSR)


def test_exportar_copia_a_bronze_con_lineage_sin_tocar_el_origen(proyecto):
    antes = sorted((p, p.stat().st_mtime_ns) for p in proyecto.infelix.rglob("*"))
    _solo_lectura(proyecto.infelix)
    try:
        r = fuentes.exportar("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO)
    finally:
        _escribible(proyecto.infelix)
    assert r.origen == "exportado"
    assert r.ruta.read_bytes() == b"admin-infelix"
    lineage = json.loads(r.ruta.with_name(r.ruta.name + ".lineage.json").read_text("utf-8"))
    assert lineage["nombre"] == "h3_admin"
    assert lineage["sha256"] == _sha(b"admin-infelix")
    assert lineage["ruta_origen"] == "infelix:data/silver/h3_features/h3_admin.parquet"
    assert lineage["titularidad"] == "infelix (CC BY-NC-SA 4.0)"
    assert sorted((p, p.stat().st_mtime_ns) for p in proyecto.infelix.rglob("*")) == antes


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_exportar_con_git_ref_lee_la_version_congelada(proyecto):
    repo = proyecto.infelix
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "analysis/matchdays.csv").write_text("version-ancla\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ancla")
    ancla = _git(repo, "rev-parse", "--short", "HEAD")
    (repo / "analysis/matchdays.csv").write_text("version-ancla\n94 filas nuevas\n", "utf-8")
    _git(repo, "commit", "-qam", "despues")

    catalogo = proyecto.cfg.catalogo
    catalogo.write_text(
        catalogo.read_text(encoding="utf-8").replace("PENDIENTE_EN_TEST", ancla),
        encoding="utf-8",
    )
    r = fuentes.exportar("matchdays_ancla", cfg=proyecto.cfg, env=SIN_ENTORNO)
    assert r.ruta.read_text(encoding="utf-8") == "version-ancla\n"
    lineage = json.loads(r.ruta.with_name(r.ruta.name + ".lineage.json").read_text("utf-8"))
    assert lineage["git_ref"] == ancla
    # y desde ahora la fuente resuelve, a la versión congelada
    resuelta = fuentes.resolver("matchdays_ancla", cfg=proyecto.cfg, env=SIN_ENTORNO)
    assert (resuelta.ruta, resuelta.origen) == (r.ruta, "exportado")


# ─── lake remoto ──────────────────────────────────────────────────────────────
class RemotoFalso:
    """bocho en un directorio. Implementa el mismo protocolo que ``RemotoSSH``."""

    def __init__(self, base: Path, *, arriba: bool = True) -> None:
        self.base = base
        self.arriba = arriba
        self.subidas: list[str] = []

    def disponible(self) -> bool:
        return self.arriba

    def _exigir(self) -> None:
        if not self.arriba:
            raise lake_mod.LakeInaccesible("bocho caído (falso)")

    def sha256(self, rel: str) -> str | None:
        self._exigir()
        p = self.base / rel
        return _sha(p.read_bytes()) if p.is_file() else None

    def leer_lineage(self, rel: str) -> dict | None:
        self._exigir()
        p = self.base / (rel + ".lineage.json")
        return json.loads(p.read_text("utf-8")) if p.is_file() else None

    def subir(self, local: Path, rel: str) -> None:
        self._exigir()
        destino = self.base / rel
        if destino.exists():
            raise AssertionError(f"subir pisó {rel}: el lake nunca sobrescribe")
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(local.read_bytes())
        self.subidas.append(rel)

    def bajar(self, rel: str, local: Path) -> None:
        self._exigir()
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes((self.base / rel).read_bytes())


@pytest.fixture
def bocho(tmp_path: Path) -> RemotoFalso:
    base = tmp_path / "bocho"
    base.mkdir()
    return RemotoFalso(base)


def test_publicar_sube_archivo_y_lineage(proyecto, bocho):
    resultado = lake_mod.publicar("h3_admin", bocho, cfg=proyecto.cfg, env=SIN_ENTORNO)
    assert resultado == "publicado"
    rel = "infelix/h3_features/h3_admin.parquet"
    assert (bocho.base / rel).read_bytes() == b"admin-infelix"
    lineage = bocho.leer_lineage(rel)
    assert lineage["sha256"] == _sha(b"admin-infelix")
    assert lineage["ruta_origen"] == "infelix:data/silver/h3_features/h3_admin.parquet"


def test_publicar_no_hace_nada_si_bocho_ya_tiene_el_mismo_sha(proyecto, bocho):
    lake_mod.publicar("h3_admin", bocho, cfg=proyecto.cfg, env=SIN_ENTORNO)
    bocho.subidas.clear()
    assert lake_mod.publicar("h3_admin", bocho, cfg=proyecto.cfg, env=SIN_ENTORNO) == "ya_estaba"
    assert bocho.subidas == []


def test_publicar_se_detiene_si_bocho_tiene_otra_version(proyecto, bocho):
    rel = "infelix/h3_features/h3_admin.parquet"
    (bocho.base / rel).parent.mkdir(parents=True)
    (bocho.base / rel).write_bytes(b"otra version en bocho")
    with pytest.raises(lake_mod.ConflictoLake, match=rel):
        lake_mod.publicar("h3_admin", bocho, cfg=proyecto.cfg, env=SIN_ENTORNO)
    assert (bocho.base / rel).read_bytes() == b"otra version en bocho"


def test_publicar_no_sube_lo_que_ya_viene_del_lake(proyecto, bocho):
    _escribir_lake(proyecto, "infelix/h3_features/h3_admin.parquet", b"admin-lake")
    with pytest.raises(lake_mod.ConflictoLake, match="ya se sirve desde el lake"):
        lake_mod.publicar("h3_admin", bocho, cfg=proyecto.cfg, env=SIN_ENTORNO)


def test_sync_baja_verifica_el_sha_y_la_fuente_pasa_a_resolver_desde_lake(proyecto, bocho):
    lake_mod.publicar("h3_admin", bocho, cfg=proyecto.cfg, env=SIN_ENTORNO)
    resultado = lake_mod.sync("h3_admin", bocho, cfg=proyecto.cfg, env=SIN_ENTORNO)
    assert resultado == "verificado"
    r = fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO)
    assert (r.origen, r.sha256) == ("lake", _sha(b"admin-infelix"))


def test_sync_rechaza_una_copia_que_no_cuadra_con_su_lineage(proyecto, bocho):
    lake_mod.publicar("h3_admin", bocho, cfg=proyecto.cfg, env=SIN_ENTORNO)
    rel = "infelix/h3_features/h3_admin.parquet"
    (bocho.base / rel).write_bytes(b"corrompido en el camino")
    with pytest.raises(lake_mod.IntegridadLake, match=rel):
        lake_mod.sync("h3_admin", bocho, cfg=proyecto.cfg, env=SIN_ENTORNO)
    assert not (proyecto.cfg.lake / rel).exists()
    assert fuentes.resolver("h3_admin", cfg=proyecto.cfg, env=SIN_ENTORNO).origen == "infelix"


def test_sync_acepta_datos_previos_de_bocho_sin_lineage_pero_lo_declara(proyecto, bocho):
    """bocho ya era data lake antes de este catálogo: su silver no trae lineage."""
    rel = "infelix/h3_features/h3_admin.parquet"
    (bocho.base / rel).parent.mkdir(parents=True)
    (bocho.base / rel).write_bytes(b"silver historico")
    assert lake_mod.sync("h3_admin", bocho, cfg=proyecto.cfg, env=SIN_ENTORNO) == "sin_lineage"
    assert (proyecto.cfg.lake / rel).read_bytes() == b"silver historico"


def test_estado_compara_contra_bocho(proyecto, bocho):
    lake_mod.publicar("h3_admin", bocho, cfg=proyecto.cfg, env=SIN_ENTORNO)
    lake_mod.sync("h3_admin", bocho, cfg=proyecto.cfg, env=SIN_ENTORNO)
    filas = {f.nombre: f for f in lake_mod.estado(bocho, cfg=proyecto.cfg, env=SIN_ENTORNO)}
    assert (filas["h3_admin"].origen, filas["h3_admin"].remoto) == ("lake", "igual")
    assert (filas["solo_lake"].origen, filas["solo_lake"].remoto) == ("falta", "ausente")
    assert filas["matchdays_ancla"].origen == "falta"


def test_estado_funciona_con_bocho_caido(proyecto, tmp_path):
    caido = RemotoFalso(tmp_path / "nada", arriba=False)
    filas = {f.nombre: f for f in lake_mod.estado(caido, cfg=proyecto.cfg, env=SIN_ENTORNO)}
    assert filas["h3_admin"].origen == "infelix"
    assert filas["h3_admin"].es_transicion
    assert {f.remoto for f in filas.values()} == {"sin_conexion"}


def test_remoto_pendiente_falla_de_forma_accionable(proyecto):
    catalogo = proyecto.cfg.catalogo
    catalogo.write_text(
        catalogo.read_text(encoding="utf-8").replace("bocho:/srv/lake", "PENDIENTE"),
        encoding="utf-8",
    )
    cat = fuentes.cargar_catalogo(proyecto.cfg, env=SIN_ENTORNO)
    with pytest.raises(lake_mod.LakeNoConfigurado, match="INWATCH_LAKE_REMOTO"):
        lake_mod.remoto_desde(cat)


# ─── RemotoSSH: los comandos que de verdad se ejecutan ────────────────────────
class Grabadora:
    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.comandos: list[list[str]] = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess:
        self.comandos.append(cmd)
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, "")


def test_ssh_usa_el_binario_del_sistema_y_no_el_kitten():
    """En la terminal del usuario `ssh` es el kitten de kitty, que exige un TTY."""
    g = Grabadora()
    remoto = lake_mod.RemotoSSH("bocho:/srv/lake", ejecutar=g)
    assert remoto.disponible()
    cmd = g.comandos[0]
    assert cmd[0] == "/usr/bin/ssh"
    assert "BatchMode=yes" in cmd
    assert cmd[-2:] == ["bocho", "true"]


def test_ssh_caido_no_esta_disponible():
    remoto = lake_mod.RemotoSSH("bocho:/srv/lake", ejecutar=Grabadora(returncode=255))
    assert not remoto.disponible()


def test_subir_nunca_borra_ni_sobrescribe(tmp_path):
    g = Grabadora()
    local = tmp_path / "a b.parquet"
    local.write_bytes(b"x")
    lake_mod.RemotoSSH("bocho:/srv/lake", ejecutar=g).subir(local, "dir con espacio/a b.parquet")
    rsync = next(c for c in g.comandos if c[0] == "rsync")
    assert "--ignore-existing" in rsync
    assert not any(flag.startswith("--delete") for c in g.comandos for flag in c)
    assert "/usr/bin/ssh" in rsync[rsync.index("-e") + 1]
    assert rsync[-1] == "bocho:/srv/lake/dir con espacio/a b.parquet"


def test_sha_remoto_ausente_es_none():
    g = Grabadora(returncode=1)
    assert lake_mod.RemotoSSH("bocho:/srv/lake", ejecutar=g).sha256("no/esta.parquet") is None


def test_sha_remoto_sale_de_sha256sum():
    g = Grabadora(stdout=f"{'a' * 64}  /srv/lake/x.parquet\n")
    assert lake_mod.RemotoSSH("bocho:/srv/lake", ejecutar=g).sha256("x.parquet") == "a" * 64


def test_destino_remoto_mal_formado_falla():
    with pytest.raises(lake_mod.LakeNoConfigurado, match="host:/ruta"):
        lake_mod.RemotoSSH("solo-un-host", ejecutar=Grabadora())


@pytest.mark.parametrize("host", [
    "-oProxyCommand=touch /tmp/pwned",   # ssh lo lee como opción y ejecuta el comando
    "-F/dev/null",
    "host con espacio",
    "host;rm -rf ~",
    "",
])
def test_un_host_que_parece_opcion_o_trae_metacaracteres_se_rechaza(host):
    """`[lake].remoto` está versionado y el repo es público: un host malicioso en un PR
    ejecutaría comandos en la máquina de quien corra `fuentes estado`."""
    with pytest.raises(lake_mod.LakeNoConfigurado, match="host"):
        lake_mod.RemotoSSH(f"{host}:/srv/lake", ejecutar=Grabadora())


@pytest.mark.parametrize("host", ["bocho", "usuario@bocho", "10.147.19.10", "bocho-2.local"])
def test_los_hosts_normales_siguen_valiendo(host):
    assert lake_mod.RemotoSSH(f"{host}:/srv/lake", ejecutar=Grabadora()).host == host


# ─── el catálogo real del repo ────────────────────────────────────────────────
def test_el_catalogo_versionado_es_valido():
    """Carga `registry/fuentes.toml` del repo. No necesita datos: valida estructura."""
    cfg = fuentes.load_config(Path(__file__).parent)
    cat = fuentes.cargar_catalogo(cfg, env=SIN_ENTORNO)
    assert cat.fuentes, "el catálogo real está vacío"
    for nombre, f in cat.fuentes.items():
        assert f.lake or f.curado or f.transicion, f"{nombre} no tiene ningún candidato"
        if f.curado:
            # Declarar `curado` es prometer que el archivo viaja en el repo. Afirmar solo
            # el string deja pasar un nombre mal tipeado o un `.gitignore` que se lo coma,
            # que es justo el fallo que la fuente curada existe para evitar.
            assert (cfg.root / f.curado).is_file(), f"{nombre}: falta {f.curado} en el repo"


def _en_repo_git(raiz: Path) -> bool:
    return (raiz / ".git").exists()


def test_lo_curado_viaja_en_git_de_verdad():
    """Que el archivo esté en disco no dice que esté en el repo.

    ``test_el_catalogo_versionado_es_valido`` comprueba existencia, y eso pasa en
    la laptop de quien lo generó aunque git lo esté ignorando: el clon del grupo se
    queda sin el insumo y el loader falla lejos de la causa. Acá se pregunta por lo
    que realmente viaja, que es el índice de git.
    """
    cfg = fuentes.load_config(Path(__file__).parent)
    if not _en_repo_git(cfg.root):
        pytest.skip("sin repo git: no hay índice contra el cual verificar")
    cat = fuentes.cargar_catalogo(cfg, env=SIN_ENTORNO)
    curados = sorted({f.curado for f in cat.fuentes.values() if f.curado})
    if not curados:
        pytest.skip("el catálogo no declara fuentes curadas")
    proc = subprocess.run(
        ["git", "ls-files", "--error-unmatch", *curados],
        cwd=cfg.root,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"insumo curado sin trackear: {proc.stderr.strip()}"


def test_el_gitignore_deja_entrar_nuevos_insumos_curados():
    """La excepción `!data/curado/` solo existe si git recorre `data/`.

    Ignorar el directorio (``data/``) en vez de su contenido (``data/*``) hace que git
    ni siquiera descienda, así que la negación no llega a evaluarse. El insumo ya
    trackeado sigue viajando —el índice manda sobre el ignore— y nada falla; el que se
    pierde es el *siguiente* archivo curado, en silencio. Se prueba con rutas que no
    existen: se está interrogando la regla, no el disco.
    """
    cfg = fuentes.load_config(Path(__file__).parent)
    if not _en_repo_git(cfg.root):
        pytest.skip("sin repo git: no hay .gitignore que evaluar")

    def ignorado(ruta: str) -> bool:
        return (
            subprocess.run(
                ["git", "check-ignore", "-q", ruta], cwd=cfg.root, capture_output=True
            ).returncode
            == 0
        )

    for nuevo in ("data/curado/NUEVO.csv", "data/curado/sub/OTRO.geojson"):
        assert not ignorado(nuevo), f"{nuevo} quedaría fuera del repo sin avisar"
    # …y el resto de data/ sigue ignorado: la excepción es curado, no una puerta abierta.
    for regenerable in ("data/lake/x.parquet", "data/bronze/y.csv", "data/nuevo/z.txt"):
        assert ignorado(regenerable), f"{regenerable} es regenerable y no debe versionarse"
