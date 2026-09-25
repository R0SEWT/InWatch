# reloj-de-riesgo — ¿tiene cada celda su reloj, y esos relojes forman tipos? (E8)

> Bead `inwatch-kr0`. Origen: infelix slr-b41b (Idea 15, *chronotypes*). Depende de
> E6.H1 (`pulso-estadios`), de donde hereda la limpieza, los 00:00 y las aorísticas.
>
> **Este README no cita cifras todavía.** El loader no emite al registro canónico (ver
> *Decisiones tomadas*); los resultados viven en `data/silver/reloj-de-riesgo/trampas.json`
> con su `inputs_sha256`, y en la descripción del PR. Cuando se decida emitir, las cifras
> entran acá con su ancla `CANON:`.

## La pregunta

¿Reparte cada celda su crimen entre madrugada, mañana, tarde y noche de una forma que la
distinga de la ciudad, y esas formas se agrupan en unos pocos tipos (nocturna, diurna,
madrugada)? Antes de agrupar: ¿sobreviven los datos a las tres trampas que infelix exige
auditar — heaping, incertidumbre aorística y sparsity?

## Qué se manipula

- **El turno**: el mapa muestra, turno por turno, la razón entre la proporción de la
  celda y la de la ciudad.
- **El corte**: 4 turnos (los de `turno_hecho` de SIDPOL) o 6 bloques de 4 h. Una firma
  que solo existe en un corte es del corte, no del lugar.
- **k**: el número de tipos. El notebook muestra la partición de cada k junto a su
  estabilidad y a la de una ciudad nula, para que se vea qué k (si alguno) es real.

## Unidad espacial

`h3_8`, como **climatología**: celda × turno con todos los años 2019–2023 apilados. No es
un panel. Celda × hora es inviable (el bead lo declara y la auditoría de sparsity lo
mide). `manzana` y `morfologica` quedan pendientes: el cruce reloj × unidad es la mejora
que el bead nombra sobre infelix, y no entró en esta corrida.

## Datos

| Artefacto | Origen | Unidad | Notas |
|---|---|---|---|
| `trampas.json` | `denuncias_lima`, `h3_feature_matrix`, `h3_admin` | — | auditoría, criterios, veredicto, estructura |
| `heaping_hora_minuto.parquet` | `denuncias_lima` | hora × minuto | el histograma de heaping que E6.H1 pedía exportar |
| `aoristica_modalidades.parquet` | `denuncias_lima` | modalidad | 00:00, madrugada y rezago hecho→registro |
| `sparsity_celdas.parquet` | idem | `h3_8` | n por celda y si pasa el piso |
| `mapa_turno.parquet` | idem | `h3_8` × turno | conteo, proporción cruda y encogida, razón vs ciudad |
| `eje.parquet` | idem | `h3_8` | puntaje de la celda en el eje principal de la firma |
| `clusters.parquet`, `clusters_perfil.parquet` | idem | `h3_8` | partición y perfil para cada k de 2 a 8 |
| `estabilidad.parquet`, `sensibilidad.parquet` | idem | k | semillas, bootstrap, nulo; ARI al deshacer cada decisión |

Fuentes pedidas por nombre con `inwatch.fuentes`, en solo lectura.

## Las tres trampas y cómo se auditan

Los criterios de muerte son constantes `KILL_*` en `loader.py`, fijadas antes de correr
el clustering. El clustering solo corre si las tres sobreviven.

1. **Heaping.** Histograma hora × minuto; espiga del 00:00 exacto contra el minuto 0 de
   01–05 h; espigas en los bordes de turno. Test de re-sorteo: cada hora redondeada se
   sortea dentro de su ventana de redondeo (`:00` ±30 min, `:30` ±15, otro múltiplo de 5
   ±2,5) y se mide qué fracción cambia de turno y cuánto se mueve la firma de cada celda
   contra cuánto difieren las celdas de la ciudad. Muere si cambia de turno más del 10 %
   o si el ruido es al menos la mitad de la señal. Los 00:00:00 exactos se excluyen
   (default de hora desconocida, heredado de E6.H1); se mide además si ese default se
   concentra en ciertas celdas.
2. **Aorística.** SIDPOL trae una sola hora del hecho y la hora de registro; no trae
   ventana (inicio, fin), así que el reparto de Ratcliffe (2002) **no es aplicable**. Las
   modalidades de E6.H1 (vehículo, autopartes, casa habitada) se excluyen y se mide
   cuánto pesan, por celda y en total. Muere si se pierde más de la mitad. Se reportan,
   sin excluirlas, las modalidades que se comportan como aorísticas (mucho 00:00 o mucho
   rezago).
3. **Sparsity.** Celda × hora y celda × turno × mes, medidos. Piso de n ≥ 100 por celda
   (SE ≤ 0,05 en cualquier proporción de turno). Sobredispersión entre celdas contra la
   multinomial, fiabilidad split-half (Spearman-Brown) al azar, por años pares/impares y
   con/sin toque de queda. Muere con menos de 100 celdas sobre el piso, cobertura menor
   al 50 % de los eventos, fiabilidad menor a 0,5 o sobredispersión menor a 1,5.

## Clustering, estabilidad y estructura

- Firma = clr de la proporción encogida hacia la ciudad (Dirichlet, α por momentos)
  menos el clr de la ciudad.
- k-means++ (scipy, sin el extra `ml`), k de 2 a 8, 20 semillas × 10 arranques.
- Estabilidad: ARI entre semillas y ARI bootstrap (re-muestreo multinomial de los eventos
  de cada celda). **Nulo**: la ciudad sin relojes (cada celda multinomial del perfil de
  la ciudad con su propio n), pasada por el mismo procedimiento.
- Un k se acepta si su silhouette supera el p95 del nulo, su ARI bootstrap p05 supera el
  p95 del nulo y su ARI bootstrap medio es ≥ 0,75 (Hennig 2007). Si ninguno pasa, no hay
  tipos y se dice.
- Sensibilidad: ARI contra la partición principal al deshacer cada decisión (con 00:00,
  con aorísticas, con el heaping re-sorteado, sin 2020–21).
- Estructura: PCA de la firma, Moran's I del primer eje sobre vecinos H3, correlación de
  la firma con la mezcla de categorías, y la misma prueba con solo robo callejero.
- Las etiquetas de los clusters salen del dato (turno de mayor exceso), no de la
  hipótesis nocturna / diurna / madrugada.

## Qué se ve

Tabla de las tres trampas con su criterio y resultado; histograma de heaping; tabla de
modalidades. Si sobreviven: mapa por turno (rampa magma de log2 razón vs ciudad,
recortada a ×½…×2), mapa del eje continuo (rampa cividis), tabla de estabilidad contra el
nulo, mapa de tipos para el k elegido en el slider (Okabe-Ito sin verde) con su perfil y
la sensibilidad.

**Recordatorio no negociable**: las celdas bajo el piso se dibujan punteadas, nunca vacías
ni verdes.

## Cómo correr

```bash
uv sync --extra geo --extra viz
uv run python experiments/reloj-de-riesgo/loader.py    # precómputo → data/silver/reloj-de-riesgo/
uv run marimo edit experiments/reloj-de-riesgo/notebook.py
```

## Verificación

- [x] `uv run pytest tests/test_reloj_de_riesgo.py` en verde (sin datos: lógica sintética)
- [x] `uv run canon check` sin fallos
- [x] El loader es determinista: dos corridas dan el mismo `trampas.json` byte a byte
- [ ] Screenshot del notebook en claro y oscuro, consola limpia
- [ ] Contraste verificado en deuteranopia

## Decisiones tomadas

- **No se emite al registro canónico en esta corrida.** Fue una corrida nocturna
  desatendida y la emisión es una decisión de Rody. Por eso este README no cita cifras.
- **`fecha_hora_registro_hecho` se lee como hora de pared de Lima**, no como UTC. Leída
  como UTC, el rezago registro − hecho tiene un piso duro en −5 h y una fracción grande de
  registros "antes" del hecho; leída como hora local, el piso pasa a 0. `fecha_hora_hecho`
  sí es UTC (su hora en Lima cuadra con `turno_hecho`). Solo afecta al diagnóstico de
  rezago, no al reloj.
- **Las aorísticas se excluyen, no se reparten.** Sin ventana no hay Ratcliffe; repartir
  sobre una ventana inventada sería fabricar el dato. La sensibilidad "con aorísticas"
  muestra cuánto cambiaría la partición si se incluyeran con su hora puntual.
- **El 00:00 exacto se excluye** (E6.H1). Como su frecuencia varía entre celdas más que
  la binomial, la exclusión le quita algo de madrugada a unas celdas más que a otras; la
  sensibilidad "con 00:00" lo acota.
- **El toque de queda (2020–21) está dentro de la climatología.** Cambia el perfil de la
  ciudad y la partición es la más sensible a sacarlo. No se excluye por defecto (el bead
  pide climatología 2019–2023, heredada), pero es la primera duda abierta.
- **Sin k-means de sklearn**: el CI instala solo `geo`, y la lógica tiene que testearse
  ahí. k-means++, ARI y silhouette están implementados sobre scipy y testeados con datos
  sintéticos.
- **Hereda el sesgo horario de denuncia.** ENAPRES no tiene hora; la superficie
  de-sesgada es hora-invariante. Si lo que ocurre de madrugada se denuncia menos, este
  reloj lo hereda sin poder medirlo. Que no se pueda contestar es un hallazgo, y así se
  reporta.

## Chequeo posterior (literatura): heaping por modalidad y tipos en subconjuntos

> **Chequeo posterior (literatura)**, añadido el 2026-09-25 después del resultado. No
> reescribe las trampas, sus criterios de muerte ni el criterio de elección de k de
> arriba: los reusa tal cual. Código en `chequeo_literatura.py`.

### 1 · Re-sorteo no uniforme (Taylor, Di Marzio, Fensore & Passamonti 2026, *JRSS C*)

Taylor et al. muestran que la probabilidad de redondear depende del tipo de delito. El
re-sorteo de arriba usa la misma ventana para todos. Acá:

- **Tasas por modalidad.** Para cada modalidad con n ≥ 2000 (el resto se agrupa por
  categoría), se estiman por EM las probabilidades π_r de redondear a r ∈ {60, 30, 15, 5,
  1} min a partir de los «minutos pasada la hora», suponiendo que el minuto verdadero es
  uniforme. Variante: π por modalidad × turno, para ver si la madrugada redondea más.
- **Re-sorteo.** Cada evento sortea su resolución r de la posterior P(r | minuto) de su
  modalidad y su hora se re-sortea dentro de la ventana de esa resolución. Dos lecturas
  de la ventana: **al más cercano** (± r/2, la de arriba) y **truncado** ([hora, hora + r),
  «a las 8» por «8 y algo»), que desplaza masa hacia el turno siguiente.
- **Criterio (el mismo de arriba).** El heaping sigue sin matar si, en `turnos4`, la razón
  ruido/señal < 0,50 y la fracción que cambia de turno ≤ 10 %, en **todas** las variantes
  (modalidad y modalidad × turno, cercano y truncado), tomando el p95 de 20 réplicas.
  Se reporta además cuánto cambia la fracción de madrugada de la ciudad y el ρ del eje
  madrugada-tarde antes y después.

### 2 · ¿Aparecen tipos en hot spots o en zonas comerciales? (Corcoran et al. 2019; Ratcliffe 2002)

Esos trabajos sí encuentran tipologías temporales, pero dentro de hot spots o de zonas
comerciales, no en toda la ciudad. Se repite el clustering de arriba (misma firma clr
encogida, mismo nulo «ciudad sin relojes» construido con el perfil **del subconjunto**,
mismo bootstrap, mismo `elegir_k`) sobre dos subconjuntos de las celdas con n ≥ 100:

- **hot spots**: el quintil superior por número de eventos del reloj;
- **comerciales**: el cuartil superior de POI comerciales de OSM (retail + comida +
  nightlife, la misma definición que E7).

**Aparecen tipos** si `elegir_k` devuelve un k en algún subconjunto y esquema. Se reporta
también, sin que decida, qué pasaría con el umbral de estabilidad relajado a 0,5 (duda 5).
