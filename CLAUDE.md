# InWatch — AI Agent Instructions

## Dominio / Contexto científico

- **Problema**: los datos policiales no miden crimen. Miden la intersección de tres
  filtros — que la víctima denuncie, que la institución registre, y que el sistema
  geocodifique — y los tres son fuertes y **desiguales en el espacio**. Un mapa que
  ignora eso muestra dónde se denuncia, no dónde ocurre.
- **Outcome / target**: riesgo delictivo **latente** bajo sesgo de denuncia, estimado
  por unidad espacial y hecho *manipulable*: cada experimento es un notebook reactivo
  donde mover un parámetro muestra qué le pasa al hallazgo. No es un producto de ruteo
  ni un mapa de calor de denuncias.
- **Procedencia de datos**: Lima + Callao, Perú. Manzana censal INEI; grilla canónica
  H3 res-8; tesselación morfológica vía `city2graph`. Los estimadores combinan encuesta
  de victimización con registro policial (pooled multi-año, r̂ EB victim-level). El
  material derivado proviene de un repo de origen bajo **CC BY-NC-SA 4.0 con dos
  titulares de copyright** — por eso la licencia de InWatch está **sin definir** y el
  repo permanece privado. No agregues un `LICENSE` por defecto.

### Las dos reglas duras

1. **Sin datos ≠ seguro.** Una celda sin registro se dibuja *deshilachada*, nunca vacía
   ni verde. Ausencia de denuncia es ausencia de evidencia, no evidencia de ausencia.
2. **Ningún número portante se escribe a mano.** Toda cifra sale del registro canónico
   con `git_commit` y hash del script emisor. Ver *Números canónicos* abajo.

## Arquitectura

Dos capas por experimento, y la separación **no es negociable**: `marimo` exporta a
WASM, pero geopandas y PyTorch Geometric **no corren en Pyodide**.

- `loader.py` — cómputo pesado (grafos, joins geoespaciales, modelos) → parquet con hash.
- `notebook.py` — lee artefactos y presenta. **Nunca calcula desde datos crudos.**

```bash
uv sync                      # entorno + grupo dev (NO uses --extra dev: dev es dependency-group)
uv sync --extra geo          # + geopandas, shapely, h3, city2graph
uv sync --extra ml           # + torch, torch-geometric, scikit-learn
uv sync --extra viz          # + marimo, matplotlib, pydeck

uv run pytest                # tests
uv run ruff check .          # lint
uv run canon show            # estado del registro canónico
uv run canon check           # valida anclas CANON: en los docs vigilados
uv run marimo edit experiments/<slug>/notebook.py
```

## La unidad espacial es un parámetro

No hay rejilla privilegiada. Conviven tres, y poder cambiar entre ellas *es* uno de los
experimentos:

| Unidad | Clave | Origen |
|---|---|---|
| `h3_8` | `h3_index` | grilla canónica H3 res-8 (Lima + Callao) |
| `manzana` | `mzn_id` | manzana censal INEI |
| `morfologica` | `tess_id` | tesselación morfológica (`city2graph`) |

El motivo no es estético: la escalera de atribución encontró que el único escalón
significativo es **la manzana censal**. La señal vive en la forma urbana a granularidad
sub-distrital, y un hexágono H3 res-8 no respeta manzanas. Contrato completo en
`design/contrato-unidades.md`.

## Key Files

| File | Purpose |
|------|---------|
| `src/inwatch/canon/registry.py` | Emisión y frescura del registro canónico (`emit`, `stale_entries`). Machine-written. |
| `src/inwatch/canon/check.py` | El linter: valida anclas `CANON:` contra el registro. Corre en pre-commit. |
| `src/inwatch/canon/config.py` | Descubre la raíz vía `pyproject.toml`; lee `[tool.inwatch.canon]`. |
| `src/inwatch/canon/cli.py` | `canon show \| check \| staged \| audit`. |
| `registry/canonical_numbers.json` | **Versionado** — es memoria científica, no un artefacto regenerable. |
| `experiments/<slug>/` | `loader.py` + `notebook.py` + `README.md` + tests. |
| `design/*.md` | Contratos de datos y decisiones. Vigilado por anclas `CANON:`. |
| `analysis/*.md` | Reportes por experimento (versionados; los datos no). Vigilado. |
| `pyproject.toml` | Deps por extra + `[tool.inwatch.canon]` (registry path, watched globs). |

> Aún no existen en el repo: `registry/`, `experiments/`, `analysis/`. Están en el
> diseño del README y se crean al aterrizar el primer experimento.

## Números canónicos

El mecanismo existe porque el fallo **ya ocurrió** en el repo de origen: un multiplicador
quedó stale tras un re-run del pipeline y llegó a un paper enviado.

```python
from inwatch import canon

# el emisor registra con procedencia
canon.emit("multiplier.<familia>", lat / obs, variant="victim",
           unit="latente/observado (adim.)", estimator="pooled Σλ*/Σy",
           inputs=[rate_file], script=__file__)

# la presentación consume ya redondeado por la policy — la UI no decide precisión
canon.display("multiplier.<familia>")
```

- `policy` es **hand-written** (qué variante es canónica, `decimals`, `round_mode`).
  Un script **no puede autoproclamarse canónico**: `emit()` deriva `canonical` de la policy.
- `entries` es **machine-written**. No la edites a mano.
- Los docs citan con anclas: `<!-- CANON: <key> = <valor> -->`. `canon staged` bloquea en
  pre-commit.

**Para agentes, regla operativa**: los globs vigilados son `analysis/*.md`,
`experiments/*/README.md` y `design/*.md`. **Este archivo (`CLAUDE.md`) NO está
vigilado** — por eso arriba no se cita ni una sola cifra portante. No introduzcas
números concretos acá ni en el README: quedarían fuera del check y son exactamente el
drift que el mecanismo previene. Cita por `key`, o manda el número a un doc vigilado
con su ancla.

## Convenciones

- **Stack de datos**: pandas + pyarrow + duckdb (no polars — el template genérico dice
  lo contrario; acá manda `pyproject.toml`). DuckDB para joins SQL sobre parquet.
- **Python 3.12–3.14**. El tope `<3.15` es real, lo exige `city2graph`.
- **Extras separados a propósito**: `torch` pesa y no todo experimento lo necesita.
  No muevas deps de `geo`/`ml`/`viz` al bloque base.
- **Regenerable → gitignored; reporte → versionado.** Las excepciones van con `!`
  explícito, nunca por accidente.
- **Tests que dependen de artefactos** de `data/` van marcados `@pytest.mark.needs_data`.
- **Idioma**: docstrings, comentarios y docs en español, como el resto del repo.
- **Commits**: Conventional Commits en español, **scope = experimento o track** (no
  módulo de código), y el bead ID entre paréntesis al final. El sujeto describe el
  resultado, no la acción mecánica.

  ```
  feat(observado-latente): el slider expone que la corrección no reordena el mapa (iw-3f2)
  fix(canon): el guard de decimales dejaba pasar valores en la cuenca de redondeo (iw-9k1)
  ```

- **Sin metadata de herramienta en los mensajes de commit**: nada de
  `Co-Authored-By`, `Claude-Session:` ni `🤖 Generated with…`. Heredado del repo de
  origen (decisión 2026-07-25) por dos motivos: evitar sesgo de revisor sobre trabajo
  asistido, y porque reescribir la historia después para quitarlos invalidaría los
  `git_commit` de procedencia del registro canónico. Es independiente de declarar uso
  de IA en un manuscrito — eso se resuelve en el paper, no en git.
- **Docstrings de módulo narrativos**: cuando un archivo existe por un fallo concreto,
  el docstring lo cuenta. `canon/registry.py` es el ejemplo: dice qué se rompió y por
  qué el mecanismo tiene la forma que tiene.


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->

## Session Close (PR flow — supersedes the generic beads protocol in this file)

`main` is protected: a PR is required, and merges are gated on green CI plus resolved
review conversations — with **no approval count** (a solo dev can't self-approve, and
Copilot/Sourcery reviews only ever *Comment*, so they never satisfy a required-approval
rule). **Do not push directly to `main`.**

At session end:
1. Commit work on a **branch**; `git push -u origin <branch>`.
2. Open/update a **PR**; let the configured reviewer (Copilot/Sourcery) run.
3. The merge waits for **green CI + all review conversations resolved** — never `--admin`.
4. Tracking: `bd ready` at start; file follow-up issues at close for the cross-session
   backlog. **TodoWrite is fine for ephemeral, in-session steps.**
5. `bd dolt push` applies only if a dolt remote is configured; otherwise the git-tracked
   `.beads/issues.jsonl` is the sync. `bd remember` and an out-of-repo harness `MEMORY.md`
   don't conflict — use either.

> The generic beads "Session Completion" protocol elsewhere in this file assumes
> trunk-based development (direct push to `main`, `bd dolt push`) and is **superseded**
> by this section.
