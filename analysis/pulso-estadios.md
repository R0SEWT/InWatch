# pulso-estadios — La réplica cuadró contra un ancla que ya nadie usaba

> Vigilado por `canon check`. Las cifras de **este** repo llevan su ancla; las de infelix
> se citan como observaciones externas, con la ruta y la fecha del archivo del que salen.

E6.H1 cerró reproduciendo `stadium_hourly.json` de infelix con desviación relativa
máxima

<!-- CANON: pulso.desviacion_replica = 0.0000 -->

sobre las 16 celdas del contraste: réplica exacta. El criterio de cierre se cumplió.

Al escribir la escalación que pedía `inwatch-b3w` se revisó qué sostiene ese ancla, y
resultó que sostiene menos de lo que el experimento creía. Este reporte corrige el
registro. **La conclusión práctica es que hay menos que escalar, no más.**

## Lo que sí está roto en infelix

`scripts/eval_stadium_hourly.py` no es ejecutable. Abre con

```python
from eval_stadium_event_study import (
    CROSS_CONTAM_M, EPOCH, N_DAYS, RING_EDGES, RING_NAMES,
    day_table, load_events,
)
```

y de esos siete nombres, **cuatro no existen** en el módulo que los debería proveer:
`CROSS_CONTAM_M`, `RING_EDGES`, `RING_NAMES` y `day_table`. El productor define hoy
`RINGS` y `RING_LABELS` en lugar de los dos del medio, y los otros dos desaparecieron.
El import falla antes de la primera línea de cómputo.

Verificado por AST sobre el árbol de trabajo, sin ejecutar nada: el repo de origen es
read-only para este proyecto.

Cuándo se rompió, por `git log` del propio repo de origen:

| commit | fecha y hora | qué pasó |
|---|---|---|
| `de1ab8b` | 2026-07-09 16:06 | último commit que toca el consumidor. El productor todavía define los cuatro nombres |
| `cc6d8c0` | 2026-07-09 20:21 | el productor se refactoriza. Los cuatro nombres desaparecen. El consumidor no se actualiza |
| `16c4f10` | 2026-07-10 22:05 | más trabajo sobre el productor; el consumidor sigue roto |

Un refactor legítimo dejó atrás a un consumidor, con **cuatro horas y cuarto** de
distancia. Es higiene de scripts, no una emergencia.

## Lo que NO está roto, y es la corrección importante

`inwatch-b3w` afirmaba que las cifras de ese JSON *"llegaron al addendum de
`analysis/stadium_event_study.md`"* y que *"hoy nadie puede re-derivarlas"*. **Las dos
mitades son falsas**, y conviene decirlo antes de escalarle nada a quien tiene un envío
en curso.

La §3 del reporte publicado, *"Concentración horaria: el mecanismo tiene reloj"*, cita
`RR = 3.29` en 0-500 m con IC `[2.17, 5.19]`, más `1.18` y `1.01` en los anillos
siguientes. Esas cifras **no salen** de `stadium_hourly.json`, que da `3.7578`,
`[2.3043, 6.1006]`, `1.3201` y `1.0528`.

Salen del bloque `hour_window_full` de `data/silver/analysis/stadium_event_study.json`
(mtime 2026-07-09 20:20), que contiene exactamente `3.291`, `[2.165, 5.188]`, `1.182` y
`1.009`. Lo escribe `eval_stadium_event_study.py` en su `main`, vía la función
`hour_window_run` — el **mismo módulo** que se refactorizó. Sus imports resuelven
(`DEFAULT_SOURCE` de `build_observed_h3_points`, `load_points` de
`eval_crime_chronotypes`, ambos presentes) y define a nivel de módulo todo lo que usa.
Es estáticamente sano.

Las dos cifras difieren porque son **specs distintas**: el JSON huérfano usa una ventana
simétrica `kickoff ± 4h`, y el publicado usa `[kickoff − 4h, kickoff + 5h]`, asimétrica.
No es deriva ni error: es una decisión de diseño que cambió el mismo día.

**Entonces**: `stadium_hourly.json` (16:05) fue superado por `stadium_event_study.json`
(20:20) cuatro horas y cuarto más tarde, y el script que lo producía quedó roto una
hora después de eso. Ninguna cifra publicada depende del artefacto huérfano. Ninguna
figura de la tesis quedó sin productor.

## La consecuencia real, y cae de este lado

E6.H1 ancló su réplica en un **intermedio superado**. Eso no invalida la réplica: sigue
probando que el port reproduce la maquinaria bit a bit, y esa desviación de 0.0000 sobre
16 celdas es evidencia fuerte de que la semántica reconstruida —los bordes de anillo, el
umbral de contaminación cruzada, el calendario diario— es la correcta. Como validación
de port, vale igual.

Lo que no vale es la lectura que el README del experimento le puso encima. Decía que la
réplica era *"el único chequeo ejecutable que existe sobre unas cifras que ya llegaron a
un reporte"*. No lo es: las cifras que llegaron al reporte tienen un productor que corre.
Esa frase queda corregida en el mismo commit que este reporte.

Queda además una cifra de este repo apuntando a la spec superada. El rate-ratio en la
puerta que se emite como canónico es

<!-- CANON: pulso.rr_puerta = 3.67 -->

medido sobre `kickoff ± 4h` con los fixtures vivos, sobre

<!-- CANON: pulso.dias_tratados = 201 -->

días tratados. Su comparable publicado en infelix es `3.29` bajo la ventana asimétrica.
Los dos números son correctos y miden cosas distintas; el riesgo es que alguien los lea
como el mismo número y concluya que hay una discrepancia del 11 %. La spec está en el
`estimator` de la entrada del registro, que es donde tiene que estar, pero no en el
nombre de la clave.

## Qué se recomienda escalar, y con qué tono

Un solo punto, y menor: **`scripts/eval_stadium_hourly.py` está muerto desde el
2026-07-09**. Importa cuatro nombres que su módulo hermano ya no define. Su salida
`stadium_hourly.json` quedó superada el mismo día por `hour_window_full`, así que borrar
el script no pierde nada que el pipeline vivo no produzca ya — pero mientras siga en
`scripts/` parece una etapa vigente del pipeline, y alguien que quiera re-derivar la
concentración horaria va a correrlo primero y a chocarse con un `ImportError`.

**No hay nada urgente que reportar sobre las cifras publicadas.** Se verificó y están
respaldadas por un productor que corre.

## Procedencia de este reporte

Todo lo de infelix se leyó en read-only: `git log`, `git show` y lectura de archivos.
No se ejecutó ningún script suyo —correr `eval_stadium_event_study.py` habría reescrito
`stadium_event_study.json`, que es un artefacto de su tesis— y no se escribió un solo
byte en ese repo.

| Afirmación | Cómo se verificó |
|---|---|
| cuatro nombres faltantes | AST de ambos módulos, comparando importados contra definidos a nivel de módulo |
| cuándo se rompió | AST del productor en `de1ab8b`, `cc6d8c0`, `16c4f10` y `HEAD` vía `git show` |
| las cifras publicadas no son las del ancla | lectura de `analysis/stadium_event_study.md` §3 contra los dos JSON |
| el productor de las publicadas corre | AST: imports resueltos y nombres definidos. **No se ejecutó** |

Las cifras de infelix citadas acá (`3.291`, `3.7578`, `1.182`, …) son observaciones
externas con su ruta y su fecha, no números canónicos de este repo, y por eso no llevan
ancla: emitirlas al registro las haría parecer derivadas por InWatch cuando lo único que
se hizo fue leer un archivo ajeno.
