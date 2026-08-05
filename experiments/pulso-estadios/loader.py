"""Precómputo de `pulso-estadios`: denuncias crudas → perfil de event-time por hora.

Esta capa existe por la razón de siempre en este repo — ``marimo`` exporta a WASM sobre
Pyodide y ``h3`` no corre ahí — pero además por una razón propia de este experimento, y
conviene dejarla escrita porque cambia lo que significa "replicar".

EL SCRIPT DE ORIGEN YA NO CORRE. ``infelix/scripts/eval_stadium_hourly.py`` produjo
``stadium_hourly.json`` el 9-jul-2026 y hoy tiene el import roto: pide
``CROSS_CONTAM_M``, ``RING_EDGES``, ``RING_NAMES`` y ``day_table`` a
``eval_stadium_event_study``, que define ``RINGS``/``RING_LABELS`` y ninguno de esos
cuatro nombres. Su productor fue refactorizado sin actualizarlo. Verificado por AST, sin
ejecutar nada — infelix es read-only (ver ``CLAUDE.md``, "Frontera dura"), y el hallazgo
está registrado en el bead ``inwatch-b3w``.

La consecuencia práctica: este archivo NO puede ser una transliteración línea a línea.
Hay semántica que reconstruir, y cada pieza reconstruida va marcada abajo como
``SUPUESTO DEL PORT`` con la evidencia que la sostiene. La consecuencia buena: mientras
el productor no corra, esta réplica es el único chequeo ejecutable sobre unas cifras que
ya llegaron a un reporte.

Dos artefactos:
  - ``perfil.parquet``  — lo nuevo. offset_h ∈ [−12,+12] × estadio × anillo × variante.
  - ``ancla.parquet``   — el contraste kickoff±4h, nuestros valores JUNTO a los de
                          infelix y su delta. Es el criterio de cierre del hito, no un
                          subproducto: si esta tabla no cuadra, el port derivó.

Determinista: semilla fija y ``inputs_sha256`` sobre las fuentes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from inwatch import canon

SLUG = "pulso-estadios"
UNIDAD = "anillo"

# ─── fuentes, todas read-only ────────────────────────────────────────────────
# La de denuncias viene de un encargo freelance (El Comercio / Wachi): es un tercer hilo
# de titularidad además del CC BY-NC-SA de infelix. Ver README del experimento.
WACHI = Path("~/Code/freelance-externos/ElComercio/Wachi/data/raw/LIMA.parquet").expanduser()
INFELIX = Path("/home/rosewt-dell/Code/tesis/infelix")
MATCHDAYS = INFELIX / "analysis/stadium_matchdays.csv"
EXTRA_EVENTS = INFELIX / "analysis/stadium_extra_events.csv"
MATRIX_FILE = INFELIX / "data/silver/h3_feature_matrix.parquet"
ANCLA_JSON = INFELIX / "data/silver/analysis/stadium_hourly.json"

_RAIZ = Path(__file__).resolve().parents[2]
OUT = _RAIZ / "data" / "silver" / SLUG
BRONZE = _RAIZ / "data" / "bronze" / SLUG

# El commit de infelix cuyo árbol corresponde al ancla. `stadium_hourly.json` se escribió
# a las 16:05 del 9-jul-2026; este commit es de las 16:00 del mismo día. El siguiente
# commit sobre los fixtures (766ad9d, 20:11) añadió 94 filas a matchdays — copas,
# selección y 26 conciertos — que el ancla NO vio. Con los CSV de hoy la réplica NO puede
# cuadrar, y eso no es deriva del port: es que cambió el insumo. Ver `exportar_epoca_ancla`.
COMMIT_ANCLA = "7d77bd6"

# ─── constantes heredadas, con su procedencia exacta ─────────────────────────
# Se copian en vez de importarse porque infelix es read-only y no se toca su sys.path.
SEED = 42
CAT = "robo_hurto_callejero"
EPOCH = pd.Timestamp("2019-01-01", tz="America/Lima")
N_DAYS = 1826
YEAR_LO, YEAR_HI = 2019, 2023
H3_RES = 8
LAT_MIN, LAT_MAX = -12.45, -11.55
LNG_MIN, LNG_MAX = -77.30, -76.60
MAX_PER_COORD = 30  # anti-centroide: pile-up en coord exacta = geocodificación a comisaría

M_PER_DEG_LAT = 110_540.0
M_PER_DEG_LNG = 111_320.0 * np.cos(np.deg2rad(-12.05))

STADIUMS = {
    "nacional": (-12.06707, -77.03386),
    "monumental": (-12.05565, -76.93533),
    "matute": (-12.06850, -77.02293),
}

# SUPUESTO DEL PORT (1/3) — los anillos.
# `eval_stadium_hourly.py` importaba RING_EDGES/RING_NAMES de un módulo que ya no los
# define. Se reconstruyen desde las CLAVES del propio JSON de ancla (r0_500, r500_1000,
# r1000_2000, r2000_4000), que coinciden con `RINGS` de eval_stadium_event_study.py.
# NO son los RING_EDGES de eval_stadium_power.py ([0,250,500,1000,2000]): ese es otro
# script con otra rejilla, y confundirlos rompe la comparación con el ancla.
RING_EDGES = [0.0, 500.0, 1000.0, 2000.0, 4000.0]
RING_NAMES = ["r0_500", "r500_1000", "r1000_2000", "r2000_4000"]

# SUPUESTO DEL PORT (2/3) — el umbral de contaminación cruzada.
# No hay fuente: `CROSS_CONTAM_M` desapareció del módulo. El comentario de `NEIGHBOR` en
# eval_stadium_event_study.py dice que nacional y matute están a ~1.200 m, y el código
# marca contaminado todo par por debajo del umbral. Tiene que ser > 1.200 para que ese
# par se contamine mutuamente, que es lo que el comentario declara como intención.
# 2.000 m es el valor mínimo redondo que lo cumple y coincide con el borde de anillo.
CROSS_CONTAM_M = 2000.0

# Modalidades con hora de DESCUBRIMIENTO, no del hecho (ventana aorística, Ratcliffe
# 2002). Se excluyen: su hora no informa sobre el momento del delito.
AORISTIC_MODS = {
    "HURTO DE VEHICULO",
    "HURTO DE ACCESORIOS Y AUTOPARTES DE VEHICULOS",
    "HURTO AGRAVADO EN CASA HABITADA",
}

SOURCE_COLS = [
    "solo_denuncia", "estado_coord", "id_dist_hecho",
    "lat_hecho", "long_hecho", "año_hecho",
    "tipo_hecho", "subtipo_hecho", "modalidad_hecho",
    "fecha_hora_hecho",
]

# SUPUESTO DEL PORT (3/3) — qué cuenta como fútbol.
# El original hace `liga["event"] = "liga1"` sobre TODAS las filas de matchdays y luego
# filtra por `event ∈ {liga1, libertadores, sudamericana, seleccion}`. Efecto secundario:
# las 26 filas de `event_type == "concierto"` que viven en matchdays.csv entran al
# contraste etiquetadas como liga1, mientras que los 11 conciertos de extra_events.csv
# quedan fuera. Probablemente no era la intención — pero reproducirlo es la única forma
# de cuadrar con el ancla, así que se replica y se declara. Ver README, "Qué se heredó".
FUTBOL_EVENTS = {"liga1", "libertadores", "sudamericana", "seleccion"}

WINDOW_H = 4.0          # media-ventana del contraste del ancla: kickoff ± 4 h
OFFSET_LO, OFFSET_HI = -12, 12   # dominio del perfil, en horas relativas al kickoff
BIN_H = 1.0             # ancho del bin horario del perfil
B_BOOT = 2000           # réplicas bootstrap, igual que el original


# ─── limpieza de puntos ──────────────────────────────────────────────────────
def map_category(tipo: pd.Series, subtipo: pd.Series, modalidad: pd.Series) -> pd.Series:
    """Crosswalk (tipo, subtipo, modalidad) → categoría canónica o NaN.

    Copia literal del crosswalk de infelix. Sólo se usa `robo_hurto_callejero`, pero se
    mantiene completo: recortarlo cambiaría silenciosamente el orden de las reglas, y la
    de secuestro sobre-escribe a las anteriores a propósito.
    """
    t = tipo.fillna("").str.upper()
    s = subtipo.fillna("").str.upper()
    m = modalidad.fillna("").str.upper()

    cat = pd.Series(np.nan, index=tipo.index, dtype=object)
    patrimonio = t == "PATRIMONIO (DELITO)"
    cat[patrimonio & s.isin(["ROBO", "HURTO"])] = "robo_hurto_callejero"
    cat[patrimonio & (s == "ESTAFA Y OTRAS DEFRAUDACIONES")] = "estafa"
    cat[patrimonio & (s == "EXTORSION")] = "extorsion"

    ley_mujer = t == "LEY DE VIOLENCIA CONTRA LA MUJER Y GRUPOS VULNERABLES"
    viol_sexual = (t == "LIBERTAD (DELITO)") & (s == "VIOLACION DE LA LIBERTAD SEXUAL")
    cat[ley_mujer | viol_sexual] = "violencia_familiar_sexual"
    cat[m.str.contains("SECUESTRO", na=False)] = "secuestro"
    return cat


def cargar_puntos(source: Path = WACHI) -> pd.DataFrame:
    """Denuncias 2019–2023 geocodificadas, con hora del hecho en America/Lima.

    Limpieza idéntica al oráculo de infelix: sólo denuncias, CON COORDENADA, bbox de
    Lima, anti-centroide, y restringido a las celdas del feature matrix. Devuelve
    además las banderas de heaping (`exact_midnight`) que el contraste necesita.
    """
    import h3

    df = pd.read_parquet(source, columns=SOURCE_COLS)
    df = df[df["solo_denuncia"] == 1].copy()
    df["year"] = pd.to_numeric(df["año_hecho"], errors="coerce")
    df = df[(df["year"] >= YEAR_LO) & (df["year"] <= YEAR_HI)]
    df["crime_cat"] = map_category(df["tipo_hecho"], df["subtipo_hecho"],
                                   df["modalidad_hecho"])
    # OJO AL ORDEN: se retienen LAS CINCO categorías hasta después del anti-centroide.
    # El umbral de pile-up cuenta denuncias de cualquier tipo sobre la misma coordenada,
    # porque lo que detecta es una comisaría geocodificando todo a su puerta — y una
    # comisaría no discrimina por categoría. Filtrar a robo callejero antes haría que
    # esas pilas no llegaran a 30 y dejaría entrar centroides que el original descarta.
    df = df[df["crime_cat"].notna()]

    geo = df[df["estado_coord"].astype(str).str.upper() == "CON COORDENADA"].copy()
    geo["lat"] = pd.to_numeric(geo["lat_hecho"], errors="coerce")
    geo["lng"] = pd.to_numeric(geo["long_hecho"], errors="coerce")
    geo = geo[geo["lat"].between(LAT_MIN, LAT_MAX) & geo["lng"].between(LNG_MIN, LNG_MAX)]

    # Anti-centroide: una coordenada exacta repetida decenas de veces no es un lugar,
    # es la comisaría donde se registró. Dejarlas fabricaría un cluster espurio.
    pile = geo.groupby(["lat", "lng"]).size()
    bad = set(pile[pile > MAX_PER_COORD].index)
    if bad:
        keep = np.array([k not in bad for k in zip(geo["lat"], geo["lng"], strict=True)])
        geo = geo[keep]

    geo["h3_index"] = [h3.latlng_to_cell(la, ln, H3_RES)
                       for la, ln in zip(geo["lat"].to_numpy(), geo["lng"].to_numpy(),
                                         strict=True)]
    celdas = set(pd.read_parquet(MATRIX_FILE, columns=["h3_index"])["h3_index"].unique())
    geo = geo[geo["h3_index"].isin(celdas)].copy()

    ts = pd.to_datetime(geo["fecha_hora_hecho"], unit="ms", utc=True)
    ts = ts.dt.tz_convert("America/Lima")
    geo["hour"], geo["minute"] = ts.dt.hour, ts.dt.minute
    geo["date"] = ts.dt.normalize()
    geo["exact_midnight"] = (
        (ts.dt.hour == 0) & (ts.dt.minute == 0) & (ts.dt.second == 0)
    )
    # Recién ahora se recorta a la categoría del contraste. Ver el comentario del orden.
    geo = geo[geo["crime_cat"] == CAT]
    return geo.reset_index(drop=True)


def parse_kickoff(s: object) -> float:
    """'19:30' → 19.5; ausente o mal formado → nan."""
    if not isinstance(s, str) or ":" not in s:
        return float("nan")
    hh, mm = s.split(":")[:2]
    try:
        return float(hh) + float(mm) / 60.0
    except ValueError:
        return float("nan")


def exportar_epoca_ancla() -> tuple[Path, Path]:
    """Exporta a `data/bronze/` los fixtures tal como estaban al computarse el ancla.

    Los lee con ``git show`` sobre el repo de origen, que es una operación de LECTURA
    pura: no toca índice, worktree ni refs. La frontera de ``CLAUDE.md`` prohíbe escribir
    en infelix, y autoriza explícitamente exportar a ``data/`` de este repo lo que se
    necesite. Esto es eso.

    Sin este paso la réplica no es reproducible: los CSV vivos ya no son los que el ancla
    vio, y cualquiera que corra el loader mañana obtendría el mismo desajuste sin saber
    por qué.
    """
    import subprocess

    BRONZE.mkdir(parents=True, exist_ok=True)
    salidas = []
    for rel, nombre in (("analysis/stadium_matchdays.csv", "matchdays_ancla.csv"),
                        ("analysis/stadium_extra_events.csv", "extra_events_ancla.csv")):
        destino = BRONZE / nombre
        if not destino.exists():
            blob = subprocess.run(
                ["git", "show", f"{COMMIT_ANCLA}:{rel}"],
                cwd=INFELIX, capture_output=True, text=True, check=True,
            ).stdout
            destino.write_text(blob)
        salidas.append(destino)
    return salidas[0], salidas[1]


def cargar_eventos(epoca: str = "actual") -> pd.DataFrame:
    """Partidos y eventos con kickoff, día absoluto y etiqueta de evento.

    ``epoca="ancla"`` usa los fixtures congelados del commit del ancla; ``"actual"`` usa
    los vivos, que traen 94 filas más.

    Reproduce el ensamblado del original, incluido el efecto de etiquetar toda la tabla
    de matchdays como `liga1` (ver SUPUESTO DEL PORT 3/3).
    """
    md, ex = (exportar_epoca_ancla() if epoca == "ancla" else (MATCHDAYS, EXTRA_EVENTS))
    liga = pd.read_csv(md)
    liga["event"] = "liga1"
    extra = pd.read_csv(ex)
    kev = pd.concat([liga, extra], ignore_index=True)
    kev["day"] = (pd.to_datetime(kev["date"]).dt.tz_localize("America/Lima")
                  - EPOCH).dt.days
    kev["kh"] = kev["kickoff"].map(parse_kickoff)
    return kev[(kev["day"] >= 0) & (kev["day"] < N_DAYS)].copy()


def calendario(kev: pd.DataFrame, estadio: str) -> pd.DataFrame:
    """Calendario diario del estadio: día, año-mes, día-de-semana, si hubo evento.

    Reconstruye `day_table`, que desapareció del módulo de origen. Su contrato se deduce
    del uso: el original consulta `ym`, `dow`, `has_event` y `crowd_rank`, y usa
    `crowd_rank >= 1` para marcar los días de multitud que contaminan a un vecino.
    """
    fechas = pd.date_range("2019-01-01", periods=N_DAYS, freq="D")
    cal = pd.DataFrame({
        "day": np.arange(N_DAYS),
        "dow": fechas.dayofweek,
        "ym": fechas.year * 12 + fechas.month,
    })
    propios = kev[kev["stadium"] == estadio]
    cal["has_event"] = cal["day"].isin(propios["day"]).to_numpy()
    rank = {"none": 0, "partial": 1, "full": 2}
    con_multitud = propios[propios["crowd"].map(rank).fillna(0) >= 1]["day"]
    cal["crowd_rank"] = np.where(cal["day"].isin(con_multitud), 1, 0)
    return cal


# ─── estimador ───────────────────────────────────────────────────────────────
def mh_rr(a: np.ndarray, c: np.ndarray, nc: np.ndarray) -> float:
    """Rate-ratio de Mantel-Haenszel con un día tratado por estrato (nt = 1)."""
    num = float(np.sum(a * nc / (1.0 + nc)))
    den = float(np.sum(c * 1.0 / (1.0 + nc)))
    return num / den if den > 0 else float("nan")


def boot_ci(a, c, nc, b, rng) -> tuple[float, float]:
    """IC 95% por bootstrap sobre días tratados (la unidad de aleatorización)."""
    n = len(a)
    if n == 0:
        return float("nan"), float("nan")
    vals = np.empty(b)
    for i in range(b):
        idx = rng.integers(0, n, n)
        vals[i] = mh_rr(a[idx], c[idx], nc[idx])
    vals = vals[np.isfinite(vals)]
    if len(vals) < b // 2:
        return float("nan"), float("nan")
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def _cuenta(t_ord: np.ndarray, lo: float, hi: float) -> int:
    return int(np.searchsorted(t_ord, hi) - np.searchsorted(t_ord, lo))


def construir_estratos(kev: pd.DataFrame, cals: dict, variante: str) -> list:
    """Estratos (estadio, día tratado, kickoff, pool de controles).

    Control = día del MISMO estadio, sin evento, mismo año-mes y mismo día-de-semana, no
    contaminado por un vecino. Que la celda sea su propio control es lo que cancela el
    sesgo de denuncia estático: el contraste es intra-celda.
    """
    futbol = kev["event"].isin(FUTBOL_EVENTS)
    tt = (kev[futbol & (kev["crowd"] == variante) & kev["kh"].notna()]
          .sort_values("kh").drop_duplicates(["stadium", "day"]))
    estratos = []
    for st, g in tt.groupby("stadium"):
        cal = cals[st]
        ok = ~cal["contaminado"].to_numpy()
        pool_base = (~cal["has_event"].to_numpy()) & ok
        clave = cal.set_index("day")[["ym", "dow"]]
        dias = cal["day"].to_numpy()
        for _, fila in g.iterrows():
            d = int(fila["day"])
            if not ok[d]:
                continue
            ym_d, dow_d = clave.loc[d, "ym"], clave.loc[d, "dow"]
            pool = dias[(cal["ym"].to_numpy() == ym_d)
                        & (cal["dow"].to_numpy() == dow_d) & pool_base]
            pool = pool[pool != d]
            if len(pool) == 0:
                continue
            estratos.append((st, d, float(fila["kh"]), pool))
    return estratos


def _acumular(estratos, tsorted, k, lo_off, hi_off):
    """Cuentas tratado/control en la ventana [kickoff+lo_off, kickoff+hi_off)."""
    n = len(estratos)
    a, c, nc = np.zeros(n), np.zeros(n), np.zeros(n)
    for i, (st, d, kh, pool) in enumerate(estratos):
        ts = tsorted[(st, k)]
        base = d * 24.0 + kh
        a[i] = _cuenta(ts, base + lo_off, base + hi_off)
        tot = 0
        for dd in pool:
            b = int(dd) * 24.0 + kh
            tot += _cuenta(ts, b + lo_off, b + hi_off)
        c[i] = tot
        nc[i] = len(pool)
    return a, c, nc


def _complemento(estratos, tsorted, k):
    """Cuentas en las 16 h restantes del día calendario. La falsificación del ancla."""
    n = len(estratos)
    a, c, nc = np.zeros(n), np.zeros(n), np.zeros(n)
    for i, (st, d, kh, pool) in enumerate(estratos):
        ts = tsorted[(st, k)]

        def fuera(dd: int, _ts=ts, _kh=kh) -> int:
            base = dd * 24.0 + _kh
            dia_lo, dia_hi = dd * 24.0, dd * 24.0 + 24.0
            todo = _cuenta(_ts, dia_lo, dia_hi)
            dentro = _cuenta(_ts, max(base - WINDOW_H, dia_lo),
                             min(base + WINDOW_H, dia_hi))
            return todo - dentro

        a[i] = fuera(d)
        c[i] = sum(fuera(int(dd)) for dd in pool)
        nc[i] = len(pool)
    return a, c, nc


# ─── orquestación ────────────────────────────────────────────────────────────
def _sha256(paths) -> str:
    h = hashlib.sha256()
    for p in sorted(str(x) for x in paths):
        h.update(Path(p).read_bytes() if Path(p).stat().st_size < 5_000_000
                 else str(Path(p).stat().st_size).encode())
        h.update(p.encode())
    return h.hexdigest()


def _huella_puntos() -> str:
    """Huella de todo lo que determina los puntos limpios: fuentes + lógica de limpieza.

    Incluye el hash del propio ``loader.py`` porque la limpieza vive acá: cambiar el
    orden del anti-centroide o el crosswalk de categorías cambia el resultado sin que
    ningún insumo se haya movido, y eso ya pasó una vez en este experimento.
    """
    h = hashlib.sha256()
    for p in (WACHI, MATRIX_FILE, Path(__file__)):
        st = p.stat()
        # Para el parquet de 179 MB leer el contenido en cada corrida no compensa;
        # tamaño + mtime detectan cualquier re-exportación real de la fuente.
        h.update(f"{p}:{st.st_size}:{st.st_mtime_ns}".encode())
    for cte in (YEAR_LO, YEAR_HI, H3_RES, MAX_PER_COORD, CAT,
                LAT_MIN, LAT_MAX, LNG_MIN, LNG_MAX):
        h.update(str(cte).encode())
    return h.hexdigest()


def puntos_cacheados() -> pd.DataFrame:
    """Puntos limpios, cacheados en bronze e invalidados por huella de insumos.

    La limpieza recorre un parquet de 179 MB y mapea cada punto a H3; hacerla dos veces
    (época del ancla y época actual) sería tiempo tirado, porque las denuncias son las
    mismas en ambas — lo que cambia es el calendario de eventos.

    Pero un caché sin invalidar es peor que no tener caché. Si `LIMA.parquet`, el feature
    matrix o la lógica de limpieza cambian y el caché no, `canon.emit` registraría hashes
    de las fuentes ACTUALES sobre cifras calculadas con las viejas: procedencia fresca
    atada a resultados stale. Ése es exactamente el fallo que el registro canónico existe
    para impedir, y meterlo por la puerta de atrás en un caché sería irónico. Por eso la
    huella se guarda junto al parquet y se verifica antes de reutilizarlo.
    """
    cache = BRONZE / "puntos_limpios.parquet"
    marca = BRONZE / "puntos_limpios.huella"
    huella = _huella_puntos()

    if cache.exists() and marca.exists() and marca.read_text().strip() == huella:
        return pd.read_parquet(cache)
    if cache.exists():
        print("  caché de puntos invalidado: cambiaron las fuentes o la limpieza")

    geo = cargar_puntos()
    BRONZE.mkdir(parents=True, exist_ok=True)
    cols = ["lat", "lng", "hour", "minute", "date", "exact_midnight", "modalidad_hecho"]
    geo[cols].to_parquet(cache, index=False)
    marca.write_text(huella + "\n")
    return geo[cols]


def construir(epoca: str = "actual") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (perfil, ancla). No escribe los artefactos: eso lo hace `main`."""
    rng = np.random.default_rng(SEED)

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

    # Tiempos ordenados por estadio×anillo: `searchsorted` convierte cada conteo de
    # ventana en dos búsquedas binarias en vez de un barrido.
    tsorted = {}
    for st in STADIUMS:
        r = np.hypot(x - coords[st][0], y - coords[st][1])
        for k in range(len(RING_NAMES)):
            m = (r >= RING_EDGES[k]) & (r < RING_EDGES[k + 1])
            tsorted[(st, k)] = np.sort(tfrac[m])

    filas_ancla, filas_perfil = [], []
    for variante in ("full", "none"):
        estratos = construir_estratos(kev, cals, variante)
        print(f"  {variante}: {len(estratos)} días tratados con kickoff y controles")

        for k, anillo in enumerate(RING_NAMES):
            # ancla: ventana ±4 h y su complemento
            for etiqueta, (a, c, nc) in (
                ("window", _acumular(estratos, tsorted, k, -WINDOW_H, WINDOW_H)),
                ("complement", _complemento(estratos, tsorted, k)),
            ):
                lo, hi = boot_ci(a, c, nc, B_BOOT, rng)
                filas_ancla.append({
                    "spec": f"{variante}_{etiqueta}", "ring": anillo,
                    "rr": mh_rr(a, c, nc), "ci_lo": lo, "ci_hi": hi,
                    "treated_days": len(estratos),
                    "treated_events": int(a.sum()), "ctrl_events": int(c.sum()),
                })

            # perfil: un bin por hora de offset
            for off in range(OFFSET_LO, OFFSET_HI + 1):
                a, c, nc = _acumular(estratos, tsorted, k,
                                     off - BIN_H / 2, off + BIN_H / 2)
                lo, hi = boot_ci(a, c, nc, B_BOOT, rng)
                esperado = float(np.sum(c / np.maximum(nc, 1)))
                filas_perfil.append({
                    "offset_h": off, "anillo": anillo, "variante": variante,
                    "unidad": UNIDAD,
                    "n_tratado": int(a.sum()), "n_control": int(c.sum()),
                    "esperado": esperado, "exceso": float(a.sum()) - esperado,
                    "rr": mh_rr(a, c, nc), "ic_low": lo, "ic_high": hi,
                    # SOPORTE = estratos tratados OBSERVADOS en el bin. Todos aportan,
                    # tengan o no evento: un día observado con cero delitos es un dato,
                    # no un hueco. Contar `a > 0` como soporte —que es lo que hacía esta
                    # línea antes— dibujaba deshilachados justamente los ceros: la
                    # variante dosis-cero y los anillos exteriores, o sea donde el cero
                    # ES el hallazgo. Eso invierte la regla dura del repo: presentaba
                    # evidencia de ausencia como ausencia de evidencia.
                    "n_estratos_soporte": len(estratos),
                    # Diagnóstico, NO soporte. Cuántos días tratados tuvieron al menos un
                    # evento en el bin. Sirve para leer la dispersión del numerador; si
                    # alguien lo usa para deshilachar, reintroduce el error de arriba.
                    "n_estratos_con_evento": int(np.sum(a > 0)),
                    # Masa de control detrás del contraste. Un bin sin controles no puede
                    # afirmar nada, y ése sí es un hueco legítimo que dibujar deshilachado.
                    "n_control_estratos": int(np.sum(nc > 0)),
                })

    perfil = pd.DataFrame(filas_perfil)
    ancla = pd.DataFrame(filas_ancla)

    # Contraste contra el ancla de infelix. Es el criterio de cierre del hito.
    ref = pd.DataFrame(json.loads(ANCLA_JSON.read_text())["results"])
    ancla = ancla.merge(ref[["spec", "ring", "rr", "treated_days", "treated_events",
                             "ctrl_events"]],
                        on=["spec", "ring"], how="left", suffixes=("", "_infelix"))
    ancla["delta_rr_rel"] = (ancla["rr"] - ancla["rr_infelix"]).abs() / ancla["rr_infelix"]
    return perfil, ancla


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. Validación: con los fixtures congelados del ancla. Es el criterio de cierre.
    print("Época del ancla (fixtures congelados en el commit del ancla):")
    _, ancla = construir(epoca="ancla")
    ancla.to_parquet(OUT / "ancla.parquet", index=False)

    # 2. Producción: con los fixtures vivos, que traen 94 partidos más. Estas son las
    #    cifras que el experimento reporta; la validación de arriba sólo certifica que
    #    la maquinaria que las produce es la misma que produjo el ancla.
    print("\nÉpoca actual (fixtures vivos):")
    perfil, actual = construir(epoca="actual")
    perfil.to_parquet(OUT / "perfil.parquet", index=False)
    actual.to_parquet(OUT / "vigente.parquet", index=False)

    fuentes = [WACHI, MATCHDAYS, EXTRA_EVENTS, MATRIX_FILE]
    pico = actual[(actual["spec"] == "full_window")
                  & (actual["ring"] == "r0_500")].iloc[0]
    canon.emit(
        "pulso.rr_puerta", float(pico["rr"]), variant="anillo_0_500",
        unit="rate-ratio tratado/control (adim.)",
        estimator="MH estratificado por día tratado, ventana kickoff±4h, bootstrap B=2000",
        inputs=[str(p) for p in fuentes], script=__file__,
    )
    canon.emit(
        "pulso.dias_tratados", int(pico["treated_days"]), variant="anillo_0_500",
        unit="días", estimator="días con kickoff conocido, no contaminados y con controles",
        inputs=[str(p) for p in fuentes], script=__file__,
    )
    # La desviación de la réplica es número portante por derecho propio: es la prueba
    # de que el port no derivó, y es lo único que hoy ata esas cifras a algo ejecutable.
    peor = float(ancla["delta_rr_rel"].max())
    # Los inputs son TODO lo que puede mover esta cifra, no sólo el JSON contra el que se
    # compara. La desviación se recalcula desde las denuncias, el filtro espacial y los
    # fixtures congelados: si cualquiera de esos cambia, el número cambia. Listar sólo el
    # ancla dejaría un número de validación científica sin registro de qué lo produjo —
    # el fallo que este registro existe para impedir, cometido por el propio guard.
    md_ancla, ex_ancla = exportar_epoca_ancla()
    canon.emit(
        "pulso.desviacion_replica", peor, variant="anillo_ancla",
        unit="desviación relativa máxima del RR (adim.)",
        estimator=("max |rr − rr_infelix| / rr_infelix sobre las 16 celdas, "
                   f"fixtures @{COMMIT_ANCLA}"),
        inputs=[str(p) for p in (ANCLA_JSON, WACHI, MATRIX_FILE, md_ancla, ex_ancla)],
        script=__file__,
    )
    print(f"\nMayor desviación relativa contra el ancla de infelix: {peor:.4%}")
    print(ancla[["spec", "ring", "rr", "rr_infelix", "delta_rr_rel"]].to_string(index=False))
    print(f"\nOK → {OUT}")


if __name__ == "__main__":
    main()
