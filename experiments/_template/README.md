# <slug> — <título en una línea>

> Plantilla. Copiar a `experiments/<slug>/` y reemplazar todo lo que esté entre `<>`.
> Este archivo está **vigilado** por `canon check`: cada cifra portante necesita su
> ancla `<!-- CANON: key = valor -->`.

## La pregunta

<Una o dos frases. Qué se quiere poder ver que hoy no se ve. Si no se puede escribir
sin usar la palabra "dashboard", probablemente no es un experimento.>

## Qué se manipula

<El parámetro que el usuario mueve, y qué debería pasar. Un experimento sin nada que
mover es una figura, y las figuras van en `analysis/`, no acá.>

## Unidad espacial

<`h3_8` | `manzana` | `morfologica` | varias comparables>

Ver `design/contrato-unidades.md`. Si el experimento cruza unidades, nombrar acá la
tabla de correspondencia que usa.

## Datos

| Artefacto | Origen | Unidad | Notas |
|---|---|---|---|
| `<archivo>.parquet` | `<ruta en el repo de origen>` | `<unidad>` | `<qué representa>` |

Los artefactos se leen **read-only** del repo de origen y se exportan a `data/` con su
procedencia registrada. Nunca se escribe en el repo de origen.

## Qué se ve

<Descripción de la capa visual: tipo de vista, qué codifica el color, qué codifica la
opacidad o la textura, qué pasa cuando no hay dato.>

**Recordatorio no negociable**: ausencia de registro se dibuja deshilachada, nunca vacía
ni verde. La rampa debe ser de luminosidad monótona y estar verificada en deuteranopia.

## Cómo correr

```bash
uv run python experiments/<slug>/loader.py    # precómputo → data/silver/<slug>/
uv run marimo edit experiments/<slug>/notebook.py
```

## Verificación

- [ ] `uv run pytest experiments/<slug>` en verde
- [ ] `uv run canon check` sin fallos
- [ ] El loader es determinista: dos corridas dan el mismo `inputs_sha256`
- [ ] Screenshot del notebook en claro y oscuro, consola limpia
- [ ] Contraste verificado en deuteranopia

## Decisiones tomadas

<Registrar acá lo que se decidió y por qué, sobre todo lo que se descartó. Un lector
futuro necesita saber qué ya se probó.>
