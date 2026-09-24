# InWatch

Banco de experimentos visuales sobre **riesgo delictivo latente bajo sesgo de
denuncia**. Cada experimento es un notebook reactivo con su propia capa visual,
alimentado por artefactos precomputados con procedencia verificable.

No es un producto de ruteo ni un mapa de calor de denuncias. Es el sitio donde los
resultados de la investigación se vuelven manipulables: mover un parámetro y ver qué
le pasa al hallazgo.

## La premisa

Los datos policiales no miden crimen. Miden la intersección de tres filtros — que la
víctima denuncie, que la institución registre, y que el sistema geocodifique — y los
tres son fuertes y desiguales en el espacio. Un mapa que ignora eso muestra dónde se
denuncia, no dónde ocurre.

De ahí las dos reglas que atraviesan todo el repo:

- **Sin datos ≠ seguro.** Una celda sin registro se dibuja *deshilachada*, nunca vacía
  ni verde.
- **Ningún número se escribe a mano.** Toda cifra portante sale del registro canónico,
  con `git_commit` y hash del script que la produjo.

## La unidad espacial es un parámetro

No hay una rejilla privilegiada. Conviven tres, y poder cambiar entre ellas *es* uno
de los experimentos:

| Unidad | Clave | Origen |
|---|---|---|
| `h3_8` | `h3_index` | grilla canónica H3 res-8 (4.172 celdas, Lima + Callao) |
| `manzana` | `mzn_id` | manzana censal INEI |
| `morfologica` | `tess_id` | tesselación morfológica (`city2graph`) |

El motivo no es estético: la escalera de atribución encontró que **el único escalón
significativo de once fuentes es la manzana censal**. La señal vive en la forma urbana
a granularidad sub-distrital, y un hexágono de 530 m no respeta manzanas.

Contrato completo en [`design/contrato-unidades.md`](design/contrato-unidades.md).

## Estructura

```
src/inwatch/canon/     registro de números canónicos (paquete instalable)
experiments/<slug>/    un experimento: loader.py + notebook.py + README.md + tests
registry/              canonical_numbers.json — versionado, es memoria científica
design/                contratos de datos y decisiones de diseño
analysis/              reportes por experimento (versionados; los datos no)
data/                  artefactos regenerables (gitignored)
```

## Empezar

```bash
uv sync                      # entorno + dev
uv sync --extra geo          # + geopandas, h3, city2graph
uv sync --extra viz          # + marimo, matplotlib, pydeck

uv run pytest                # tests
uv run ruff check .          # lint
uv run canon show            # estado del registro canónico
uv run marimo edit experiments/<slug>/notebook.py
```

## Números canónicos

Regla dura: **nunca copiar a mano una cifra portante** de un reporte a otro sitio. El
mecanismo existe porque el fallo ya ocurrió una vez en el repo de origen — un
multiplicador quedó stale tras un re-run del pipeline y llegó a un paper enviado.

```python
from inwatch import canon

# el emisor registra el número con su procedencia
canon.emit("multiplier.robo_hurto_callejero", lat / obs,
           variant="victim", unit="latente/observado (adim.)",
           estimator="pooled Σλ*/Σy 2018-2024", inputs=[rate_file], script=__file__)

# la capa de presentación lo consume ya redondeado por la policy
canon.display("multiplier.robo_hurto_callejero")   # "4.6"
```

Los docs lo citan con anclas, y el pre-commit las verifica:

```markdown
<!-- CANON: multiplier.robo_hurto_callejero = 4.6 -->
```

`uv run canon check` valida todo; `canon staged` corre en pre-commit y bloquea.

## Qué corre dónde

`marimo` exporta a WASM, pero **geopandas y PyTorch Geometric no corren en Pyodide**.
De ahí la separación, que no es negociable:

- `loader.py` — cómputo pesado (grafos, joins geoespaciales, modelos) → parquet con hash.
- `notebook.py` — lee artefactos y presenta. Nunca calcula desde datos crudos.

## Licencia

**Sin definir todavía, y por eso sin `LICENSE`: todos los derechos reservados.**

El repo es público desde el 2026-09-14 para poder compartirlo, entre otros con el
docente del curso donde se usa. Que sea público no concede permisos de reutilización.
La licencia sigue siendo una decisión pendiente y deliberada: el material derivado
proviene de un repo bajo CC BY-NC-SA 4.0 con dos titulares de copyright, así que no
puede elegirse en solitario ni por defecto. Mientras tanto aplican los términos de
GitHub para ver y hacer fork; cualquier otro uso requiere permiso de los titulares.
