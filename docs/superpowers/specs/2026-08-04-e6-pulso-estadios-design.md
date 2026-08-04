# E6 · El pulso de estadios bajo la unidad espacial

- **Fecha**: 2026-08-04
- **Bead**: `inwatch-<pendiente>` (E6), depende de `inwatch-scv` (E5, grafo morfológico)
- **Origen**: `infelix/slr-3bzt` — *"Figura/viz: pulsos de crimen denunciado y latente-implicado
  alrededor de partidos y eventos (idea 10)"*, épico `slr-jf1h` (Idea 10)

## El problema

Un partido de fútbol mete decenas de miles de personas en un punto de la ciudad durante
unas pocas horas. Si el crimen denunciado sube alrededor del estadio ese día, hay dos
explicaciones que compiten: **hay más delito** o **hay más gente que denuncia**. La Idea
10 de infelix ataca eso con un event-study intra-celda: la misma celda es su propio
control, así que el sesgo de denuncia estático se cancela.

Pero el event-study de infelix mide sobre **anillos euclidianos** — `RING_EDGES = [0, 250,
500, 1000, 2000]` metros alrededor del punto del estadio. Y el propio repo ya escribió que
eso no es como se mueve una multitud. `eval_stadium_corridors.py` abre literalmente con:

> *la multitud no llega en círculos, llega por el Metropolitano y la Línea 1.*

Ese script responde construyendo buffers de 300 m alrededor de estaciones de tránsito —
que sigue siendo geometría euclidiana, solo que centrada en otro punto. **Nadie midió el
pulso recortando el espacio por la red que la gente realmente camina.**

## Qué pregunta responde este experimento

> ¿El pulso de crimen alrededor de un partido sobrevive a recortar el espacio de otra forma?

No es una pregunta retórica y no tiene respuesta preferida:

- Si el pulso **es invariante** a la unidad, el hallazgo de infelix se robustece: no era un
  artefacto del anillo.
- Si el pulso **se mueve**, el anillo euclidiano estaba haciendo trabajo silencioso, y eso
  es un hallazgo sobre el método, no sobre el fútbol.

Informa en ambas direcciones. Esa es la propiedad que justifica correrlo.

Es además el primer consumidor real de E5: sin un cliente, el grafo morfológico es
infraestructura sin uso demostrado.

## Datos

Todos verificados existentes al 2026-08-04. Se leen **read-only**; nada se copia al repo.

| Insumo | Ruta | Qué es |
|---|---|---|
| Denuncias SIDPOL | `~/Code/freelance-externos/ElComercio/Wachi/data/raw/LIMA.parquet` | 3.136.427 filas × 62 cols, con `lat_hecho`, `long_hecho`, `fecha_hora_hecho`. 179 MB |
| Partidos | `infelix/analysis/stadium_matchdays.csv` | 363 filas, 2019-2023, con `kickoff`, `stadium`, `crowd`, `attendance`, `event_type` |
| Estaciones de tránsito | `infelix/analysis/transit_stations.csv` | 38 Metropolitano + 26 Línea 1 |
| Coords + anillos | `infelix/scripts/eval_stadium_power.py:57-63` | `nacional`, `monumental`, `matute`; `RING_EDGES` en metros |
| Ancla de réplica | `infelix/data/silver/analysis/stadium_hourly.json` | Resultado ya computado del contraste kickoff±4h |
| Ancla de réplica | `infelix/data/silver/analysis/stadium_event_study.json` | Event-study diario, con placebo y sensibilidades |

Los dos últimos **no son insumos**: son el patrón contra el que se valida que el port no
derivó. Ver *Verificación*.

### Procedencia

La fuente de denuncias proviene de un encargo freelance (El Comercio / proyecto Wachi), o
sea un tercer hilo de titularidad además del CC BY-NC-SA de infelix. InWatch es privado y
`data/` está gitignored, así que no hay conflicto operativo — pero el `README.md` del
experimento **debe declararlo**, siguiendo la regla del repo de que la procedencia es lo
diferencial.

## Arquitectura

Respeta el split no negociable del repo (marimo exporta a WASM; geopandas y PyG no corren
en Pyodide):

```
experiments/pulso-estadios/
  loader.py      # único que toca datos crudos → parquet con hash
  notebook.py    # marimo: lee el parquet, dibuja. Nunca calcula desde crudo
  README.md      # doc del experimento (vigilado por el validador de anclas)
  tests/
```

**`loader.py`** toma `LIMA.parquet` + gazetteers y produce el perfil de event-time:

```
offset_h ∈ [−12, +12]  ×  estadio  ×  unidad  ×  banda  ×  variante
  → n_tratado, n_control, exceso, ic_low, ic_high, n_dias_soporte
```

Hereda de infelix las decisiones ya tomadas y auditadas, que **no se re-litigan**:

- Horas fraccionales en `America/Lima`, índice absoluto `día×24+h` para cruzar medianoche
  sin artefactos.
- Estrato = día tratado; controles = días sin evento del mismo estadio × año-mes ×
  día-de-semana, contados en la misma ventana de reloj.
- Se excluyen los `00:00:00` exactos (default de hora desconocida) y las modalidades
  aorísticas (vehículo/autopartes/casa), donde la hora es de descubrimiento.
- MH rate-ratio estratificado, bootstrap sobre días tratados.

**`notebook.py`** solo presenta. Ningún cálculo pesado.

## Las tres unidades

| Unidad | Cómo se corta | Origen |
|---|---|---|
| `anillo` | Distancia euclidiana al punto del estadio, cortes `RING_EDGES` | Réplica fiel de infelix — **baseline** |
| `banda_red` | Distancia sobre el grafo de calles, mismos cortes en metros de red | E5 / city2graph |
| `morfologica` | Celda de `morphological_graph`, agregada por anillos de adyacencia | E5 / city2graph |

`design/contrato-unidades.md` exige tabla de correspondencia con factor de área entre
unidades, y un test de que no pierde ni inventa masa. Aplica aquí.

## Controles del notebook

1. **Offset horario** — eje X, −12h..+12h. No es un control, es el dominio.
2. **Unidad espacial** — `anillo` / `banda_red` / `morfologica`. *El control nuevo; el
   corazón del experimento.*
3. **Observado → latente-implicado** — el exceso dividido por r̂ distrital de robo.
   Declarado explícitamente como **escalado**, no como estimación fina: r̂ es distrital y
   estático, y el supuesto de sesgo estático intra-celda es lo que lo hace admisible.
4. **Variante de evento** — multitud full / dosis-cero / conciertos. La dosis-cero debe dar
   pulso plano o negativo; es la falsificación incorporada.

Regla visual del repo, aplicable directo: una banda con soporte de pocos días se dibuja
**deshilachada**, no plana. `n_dias_soporte` viaja en el parquet para eso.

## Hitos

**Hito 1 — réplica euclidiana.** No depende de E5. Implementa `loader.py` + `notebook.py`
solo con la unidad `anillo`.

*Criterio de cierre*: reproducir `stadium_hourly.json` dentro de tolerancia declarada. Es
la prueba de que el port no derivó — el mismo tipo de guarda que existe porque en infelix
un número stale sobrevivió a un re-run y llegó a un paper enviado.

**Hito 2 — el corte alternativo.** Añade `banda_red` y `morfologica`, consumiendo E5.
Produce la tabla de correspondencia y el test de masa.

*Criterio de cierre*: el notebook permite cambiar de unidad y ver moverse (o no) el pulso,
con la comparación de las tres curvas en una sola escala.

## Verificación

- **Test de ancla**: la réplica euclidiana contra el JSON de infelix, con tolerancia
  explícita.
- **Test de masa**: la correspondencia entre unidades no pierde ni inventa eventos.
- **Test de falsificación**: la variante dosis-cero no enciende pulso.
- **Inspección visual por MCP**: servir el notebook y capturar con playwright. La capa
  visual se revisa mirándola, no solo por asserts.
- **Números portantes**: emitidos al registro con procedencia, citados por ancla en el
  `README.md` del experimento. Ninguna cifra se escribe a mano.
- Tests que dependan de artefactos de `data/` van marcados `needs_data`.

## Dónde corre

**Local (dell).** Este track no toca torch: de ~100 scripts de infelix solo `train_stgnn*.py`
importan torch, y ninguno participa aquí. La fuente pesa 179 MB y los artefactos de
referencia ~1 MB.

**gorgo** (`r0sewt@172.25.153.133`, RTX 4060 Ti 16 GB) entra **solo si** E5 necesita
PyTorch Geometric para el grafo morfológico. Ya está listo para eso: `~/venv-dl` tiene
torch 2.12.0+cu130 con CUDA disponible, y `LIMA.parquet` ya está en
`/shared/Code/ElComercio/ElComercio/Wachi/data/raw/`. El directorio de trabajo es
`/shared/Code` (34 GB libres, grupo `dev`), no `~/Code`.

Restricción real de gorgo si se usa: **9 GB de RAM de sistema** y VRAM parcialmente
ocupada por otro proceso. El cuello es la RAM del host, no la GPU.

## Reglas operativas

**Al cerrar cada experimento, revisar el beads de infelix.** Regla dura, pedida
explícitamente. Ya pagó antes de empezar: así aparecieron `slr-3bzt` (el diseño de la
figura, que evitó rediseñarla desde cero) y `slr-zzo3` (la compuerta de releases).

InWatch es la **capa de experimentación e inspección**, no un venue. La compuerta
`slr-zzo3` gobierna releases externos; este repo es privado y no publica, así que no la
cruza. Si algún resultado de aquí fuera a salir a un artefacto externo, esa decisión es
separada y pasa por la compuerta.

## Fuera de alcance

- Ablaciones de modelo — el pedido fue experimentos visuales, no ablaciones.
- Réplica multi-ciudad (Arequipa, Cusco, Trujillo, Piura). Los gazetteers existen; queda
  para un E6.1 si el hito 2 cierra bien.
- Los corredores de tránsito como unidad propia. `banda_red` los subsume parcialmente;
  separarlos es otro experimento.
- Cualquier cambio a `main` o a los experimentos E1-E5 del otro agente.
