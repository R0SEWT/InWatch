"""Precómputo del hito 2 de `pulso-estadios` (inwatch-8ke): el pulso bajo otros recortes.

    uv run --extra geo python experiments/pulso-estadios/loader_unidades.py

El bead pedía añadir las unidades nuevas a ``loader.py``. No se hizo, y el motivo es el
registro canónico: ``loader.py`` es el EMISOR de ``pulso.rr_puerta``,
``pulso.dias_tratados`` y ``pulso.desviacion_replica``, y el registro guarda el sha256
del script. Tocarlo deja esas tres cifras stale —el hook de pre-commit lo bloquea— y la
única salida sería re-emitirlas, que este hito no debe hacer: sus cifras no son
portantes hasta que se adjudique el soporte (inwatch-ap1) y se decida qué unidad es
canónica. Así que el hito 2 vive al lado, IMPORTA al loader del hito 1 sin modificarlo, y
no llama nunca a ``canon.emit``.

Lo que reusa del hito 1, sin copiar: la limpieza de puntos y su caché con huella, los
eventos, el calendario, los estratos, ``_acumular`` y el estimador MH. Lo único que
reimplementa es la preparación (``_preparar``), porque en el loader vive inline dentro de
``construir``; está copiada línea a línea y la corrida verifica que el anillo recalculado
acá reproduce ``pulso.rr_puerta`` del registro, que es la prueba de que no derivó.

Mismos puntos, mismos días tratados, mismos controles, mismo estimador: sólo cambia qué
punto cuenta como «cerca del estadio». Las unidades están en ``unidades.py``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

_DIR = Path(__file__).resolve().parent


def _cargar(nombre: str, archivo: str):
    """Importa un módulo hermano sin tocar ``sys.path``."""
    spec = importlib.util.spec_from_file_location(nombre, _DIR / archivo)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


L = _cargar("pulso_loader", "loader.py")
(AORISTIC_MODS, B_BOOT, BIN_H, CROSS_CONTAM_M, EPOCH, M_PER_DEG_LAT, M_PER_DEG_LNG,
 N_DAYS, OFFSET_HI, OFFSET_LO, OUT, RING_EDGES, RING_NAMES, SEED, STADIUMS, WINDOW_H,
 _RAIZ) = (L.AORISTIC_MODS, L.B_BOOT, L.BIN_H, L.CROSS_CONTAM_M, L.EPOCH, L.M_PER_DEG_LAT,
           L.M_PER_DEG_LNG, L.N_DAYS, L.OFFSET_HI, L.OFFSET_LO, L.OUT, L.RING_EDGES,
           L.RING_NAMES, L.SEED, L.STADIUMS, L.WINDOW_H, L._RAIZ)
_acumular, calendario, cargar_eventos = L._acumular, L.calendario, L.cargar_eventos
construir_estratos, mh_rr, puntos_cacheados = (L.construir_estratos, L.mh_rr,
                                               L.puntos_cacheados)
REGISTRO = _RAIZ / "registry" / "canonical_numbers.json"


def _preparar(epoca: str):
    """Puntos en event-time y metros, eventos y calendarios con contaminación.

    Lo comparten el hito 1 (``construir``) y el hito 2 (``construir_unidades``): las dos
    unidades nuevas cambian SÓLO el recorte espacial, así que todo lo demás —limpieza,
    estratos, controles, contaminación entre estadios— tiene que ser byte a byte el mismo.
    """
    geo = puntos_cacheados()
    n_bruto = len(geo)
    geo = geo[~geo["exact_midnight"]]
    geo = geo[~geo["modalidad_hecho"].isin(AORISTIC_MODS)].copy()
    print(f"  {len(geo):,} puntos ({n_bruto:,} antes de excluir 00:00:00 y aorísticos)")

    day = (geo["date"].dt.tz_localize(None) - EPOCH.tz_localize(None)).dt.days.to_numpy()
    keep = (day >= 0) & (day < N_DAYS)
    geo, day = geo[keep], day[keep]
    tfrac = day * 24.0 + geo["hour"].to_numpy() + geo["minute"].to_numpy() / 60.0
    x = geo["lng"].to_numpy() * M_PER_DEG_LNG
    y = geo["lat"].to_numpy() * M_PER_DEG_LAT

    kev = cargar_eventos(epoca)
    coords = {st: np.array([ln * M_PER_DEG_LNG, la * M_PER_DEG_LAT])
              for st, (la, ln) in STADIUMS.items()}
    cals = {st: calendario(kev, st) for st in STADIUMS}
    for st in STADIUMS:
        contam = np.zeros(N_DAYS, dtype=bool)
        for otro in STADIUMS:
            if otro != st and np.hypot(*(coords[st] - coords[otro])) < CROSS_CONTAM_M:
                dias = cals[otro].loc[cals[otro]["crowd_rank"] >= 1, "day"].to_numpy()
                contam[dias] = True
        cals[st]["contaminado"] = contam
    lnglat = np.column_stack([geo["lng"].to_numpy(), geo["lat"].to_numpy()])
    return x, y, tfrac, kev, cals, coords, lnglat



# ─── hito 2: el corte alternativo (inwatch-8ke) ──────────────────────────────
# El tejido de E5 lo produce `experiments/tejido-vs-hexagono/loader.py`; se lee de este
# mismo repo, no del de origen.
TEJIDO_DIR = _RAIZ / "data" / "silver" / "tejido-vs-hexagono"

# Piso de denominador de la pieza (``pieza/datos.py``). Se repite acá —en vez de
# importarse— porque ``datos.py`` corre la pieza entera al importarse; un test verifica
# que los dos valores no se separen. Las dos nociones de soporte que conviven hoy
# (inwatch-ap1, sin adjudicar) se aplican JUNTAS en el hito 2: un bin es medible sólo si
# cumple las dos. Es la lectura conservadora, y no decide ap1: sólo evita que el hito 2
# elija por su cuenta la que le convenga.
PISO_CONTROL = 2
SOPORTE_MIN = 30  # valor por defecto del deslizador del notebook del hito 1

# Criterio de «sobrevive», fijado ANTES de calcular (ver notebook y README):
#   M1 = RR MH en la ventana kickoff±4h, banda interior, variante multitud, 3 estadios.
#   Sobrevive en la unidad U si (i) ic_low(M1_U) > 1, (ii) la falsificación se sostiene
#   —ic_low del mismo contraste en dosis cero ≤ 1— y (iii) hay gradiente: RR de la banda
#   interior > RR de la exterior.
#   Magnitud: se MUEVE si el IC95 bootstrap PAREADO de log(RR_U / RR_anillo) excluye 0.
#   Material si además la razón puntual cae fuera de [0.8, 1.25].
RAZON_MATERIAL = (0.8, 1.25)


def _unidades_mod():
    return _cargar("pulso_unidades", "unidades.py")


def rr_puerta_registrado() -> float | None:
    """``pulso.rr_puerta`` tal como está en el registro; None si no está."""
    if not REGISTRO.exists():
        return None
    for e in json.loads(REGISTRO.read_text())["entries"].values():
        if e.get("family") == "pulso.rr_puerta" and e.get("variant") == "anillo_0_500":
            return float(e["value"])
    return None


def mh_rr_boot(a: np.ndarray, c: np.ndarray, nc: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """RR de Mantel-Haenszel en cada réplica bootstrap; ``idx`` es (B, n).

    Vectoriza ``mh_rr`` para poder usar los MISMOS índices en todas las unidades: el
    bootstrap pareado es lo que permite decir si el RR se movió al cambiar de unidad,
    y no sólo si los dos intervalos se solapan (que es un test mucho más débil).
    """
    if idx.shape[1] == 0:
        return np.full(idx.shape[0], np.nan)
    w = 1.0 / (1.0 + nc)
    num = np.sum((a * nc * w)[idx], axis=1)
    den = np.sum((c * w)[idx], axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / den, np.nan)


def _ic(vals: np.ndarray, b: int) -> tuple[float, float]:
    """Percentil 2.5–97.5 con la misma regla de ``boot_ci``: nan si falla media corrida."""
    v = vals[np.isfinite(vals)]
    if len(v) < b // 2:
        return float("nan"), float("nan")
    return float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def medible(n_control, n_control_estratos, n_estratos_soporte,
            piso: int = PISO_CONTROL, soporte_min: int = SOPORTE_MIN):
    """Las dos nociones de soporte de inwatch-ap1, aplicadas a la vez."""
    return ((np.asarray(n_control) >= piso) & (np.asarray(n_control_estratos) > 0)
            & (np.asarray(n_estratos_soporte) >= soporte_min))


def construir_unidades(epoca: str = "actual"):
    """El pulso bajo las cuatro unidades. Devuelve un dict de DataFrames; no emite nada.

    Mismos puntos, mismos estratos, mismo estimador: sólo cambia qué punto cuenta como
    «cerca del estadio». El anillo se recalcula exactamente como en el hito 1 (con la
    aproximación equirectangular de ``M_PER_DEG_*``), para que su curva sea la del hito 1
    y no una casi igual; las unidades nuevas se miden en EPSG:32718.
    """
    from inwatch import fuentes

    U = _unidades_mod()
    rng = np.random.default_rng(SEED)
    x, y, tfrac, kev, cals, coords, lnglat = _preparar(epoca)

    a_m = U._a_metros()
    ux, uy = a_m(lnglat[:, 0], lnglat[:, 1])
    ux, uy = np.asarray(ux), np.asarray(uy)
    est_utm = {st: np.array(a_m(ln, la)) for st, (la, ln) in STADIUMS.items()}
    bandas, cortes, corr, masa = U.etiquetar(
        ux, uy, est_utm, fuentes.ruta("osm_peru_gpkg"), TEJIDO_DIR, cortes_m=RING_EDGES)

    # el anillo, idéntico al del hito 1
    for st in STADIUMS:
        r = np.hypot(x - coords[st][0], y - coords[st][1])
        bandas[("anillo", st)] = U.banda(r, np.asarray(RING_EDGES))

    tsorted = {}
    for (unidad, st), b in bandas.items():
        for k in range(len(RING_NAMES)):
            tsorted[(unidad, st, k)] = np.sort(tfrac[b == k])

    def ts_de(unidad):
        return {(st, k): tsorted[(unidad, st, k)]
                for st in STADIUMS for k in range(len(RING_NAMES))}

    filas_v, filas_p = [], []
    for variante in ("full", "none"):
        estratos = construir_estratos(kev, cals, variante)
        n = len(estratos)
        print(f"  {variante}: {n} días tratados")
        idx = rng.integers(0, n, (B_BOOT, n))
        boot_ref, rr_ref = {}, {}
        for unidad in U.UNIDADES:
            ts = ts_de(unidad)
            for k in range(len(RING_NAMES)):
                a, c, nc = _acumular(estratos, ts, k, -WINDOW_H, WINDOW_H)
                rb = mh_rr_boot(a, c, nc, idx)
                rr = mh_rr(a, c, nc)
                if unidad == "anillo":
                    boot_ref[k], rr_ref[k] = rb, rr
                lo, hi = _ic(rb, B_BOOT)
                fila = {"unidad": unidad, "banda": k, "variante": variante,
                        "rr": rr, "ic_low": lo, "ic_high": hi, "treated_days": n,
                        "n_tratado": int(a.sum()), "n_control": int(c.sum()),
                        "n_control_estratos": int(np.sum(nc > 0))}
                with np.errstate(divide="ignore", invalid="ignore"):
                    lr = np.log(rb) - np.log(boot_ref[k])
                    fila["log_razon_vs_anillo"] = float(np.log(rr) - np.log(rr_ref[k]))
                fila["log_razon_ic_low"], fila["log_razon_ic_high"] = (
                    _ic(lr, B_BOOT) if unidad != "anillo" else (0.0, 0.0))
                filas_v.append(fila)

                for off in range(OFFSET_LO, OFFSET_HI + 1):
                    a, c, nc = _acumular(estratos, ts, k, off - BIN_H / 2, off + BIN_H / 2)
                    lo, hi = _ic(mh_rr_boot(a, c, nc, idx), B_BOOT)
                    esperado = float(np.sum(c / np.maximum(nc, 1)))
                    filas_p.append({
                        "offset_h": off, "unidad": unidad, "banda": k,
                        "anillo": RING_NAMES[k], "variante": variante,
                        "n_tratado": int(a.sum()), "n_control": int(c.sum()),
                        "esperado": esperado, "exceso": float(a.sum()) - esperado,
                        "rr": mh_rr(a, c, nc), "ic_low": lo, "ic_high": hi,
                        "n_estratos_soporte": n,
                        "n_estratos_con_evento": int(np.sum(a > 0)),
                        "n_control_estratos": int(np.sum(nc > 0)),
                    })

    # Por estadio, descriptivo y sin veredicto. Va DESPUÉS del bucle agregado a propósito:
    # consume el generador aleatorio al final, así que agregarlo no movió ni un decimal
    # de las cifras de arriba. Existe porque el agregado lo domina el Nacional y porque
    # el Monumental es donde las unidades nuevas más cambian el recorte (red escasa
    # alrededor del recinto, tejido OSM incompleto en Ate).
    filas_e = []
    for variante in ("full", "none"):
        todos = construir_estratos(kev, cals, variante)
        for st in STADIUMS:
            sub = [e for e in todos if e[0] == st]
            if not sub:
                continue
            idx = rng.integers(0, len(sub), (B_BOOT, len(sub)))
            for unidad in U.UNIDADES:
                a, c, nc = _acumular(sub, ts_de(unidad), 0, -WINDOW_H, WINDOW_H)
                lo, hi = _ic(mh_rr_boot(a, c, nc, idx), B_BOOT)
                filas_e.append({"estadio": st, "unidad": unidad, "banda": 0,
                                "variante": variante, "rr": mh_rr(a, c, nc),
                                "ic_low": lo, "ic_high": hi, "treated_days": len(sub),
                                "n_tratado": int(a.sum()), "n_control": int(c.sum())})

    perfil = pd.DataFrame(filas_p)
    perfil["medible"] = medible(perfil["n_control"], perfil["n_control_estratos"],
                                perfil["n_estratos_soporte"])
    ventana = pd.DataFrame(filas_v)
    desvio = U.desvio_de_masa(corr)
    if desvio > 1e-9:
        raise AssertionError(f"la correspondencia pierde o inventa masa: {desvio:.3g}")
    return {"perfil_unidades": perfil, "ventana_unidades": ventana,
            "cortes_unidades": cortes, "correspondencia_unidades": corr,
            "masa_unidades": masa, "ventana_estadio_unidades": pd.DataFrame(filas_e)}


def main_unidades() -> None:
    """Hito 2. Escribe los artefactos de las cuatro unidades; NO emite al registro.

    Las cifras de este hito todavía no son portantes: la adjudicación de soporte
    (inwatch-ap1) y la decisión de qué unidad es canónica son de Rody, no de un loader.
    """
    OUT.mkdir(parents=True, exist_ok=True)
    print("Hito 2 · el pulso bajo cuatro recortes del espacio (fixtures vivos):")
    arts = construir_unidades("actual")
    for nombre, df in arts.items():
        df.to_parquet(OUT / f"{nombre}.parquet", index=False)
        print(f"  → {nombre}.parquet ({len(df):,} filas)")
    v = arts["ventana_unidades"]
    print(v.to_string(index=False, float_format=lambda z: f"{z:.3f}"))
    print(arts["ventana_estadio_unidades"].to_string(
        index=False, float_format=lambda z: f"{z:.3f}"))

    # El anillo de acá tiene que ser el del hito 1. Si no reproduce la cifra registrada,
    # la preparación copiada derivó y nada de lo de arriba es comparable.
    ref = rr_puerta_registrado()
    propio = float(v[(v["unidad"] == "anillo") & (v["banda"] == 0)
                     & (v["variante"] == "full")]["rr"].iloc[0])
    if ref is not None:
        print(f"\nanillo 0-500 full: {propio:.6f} · registro pulso.rr_puerta: {ref:.6f}")
        # el registro guarda seis decimales
        if abs(propio - ref) > 5e-6:
            print("  ⚠ DERIVA: el anillo del hito 2 no reproduce pulso.rr_puerta. O la "
                  "preparación copiada se separó del loader, o cambiaron los insumos "
                  "desde la emisión. Nada de lo de arriba es comparable hasta aclararlo.")


if __name__ == "__main__":
    main_unidades()
