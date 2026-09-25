# denominador — riesgo por expuesto, no por residente

> **Estado: exploratorio.** Nada de este experimento se emite todavía al registro
> canónico. Las cifras del hallazgo viven en los parquets de `data/silver/denominador/`
> y en el notebook, no en este archivo; cuando se emitan, entran acá con su ancla
> `CANON:`. Bead: `inwatch-2px`.

## La pregunta

Todas las superficies del programa son conteos o densidades por celda, y todos los
denominadores en uso son **residenciales**. Pero el riesgo de una persona es eventos por
persona expuesta: Mesa Redonda tiene una población flotante enorme y pocos residentes, y
su riesgo por residente es un sinsentido operativo.

¿Cambiar el denominador —de residentes a población ambiente— **reordena** el mapa de
riesgo latente por celda? `observado-latente` (E1) encontró que la corrección por sesgo
de denuncia escala sin reordenar. Esta es la misma pregunta para otro control, medida en
la misma escala.

## Predicción, escrita antes de calcular

Asentada en este commit, antes de que exista `loader.py`.

**La predicción es de infelix** (`slr-m0fq`, Idea 17), no de este experimento: «re-expresar
la superficie latente como riesgo-por-expuesto probablemente REORDENA el mapa (celdas
comerciales/nightlife bajan, periferias residenciales suben)».

**Honestidad sobre lo que ya se sabe.** Esta predicción no es ciega. Las notas del bead
`inwatch-2px` registran un sondeo exploratorio (2026-08-04) que ya apuntaba a un
reordenamiento fuerte. Lo que este commit fija antes de calcular no es la dirección
esperada —que ya se intuye— sino **la métrica, la población y los umbrales de decisión**,
para que el resultado no se pueda leer a conveniencia después.

### El denominador de expuestos no existe; el proxy sí

El denominador conceptualmente correcto es **persona-horas expuestas por celda** (población
flotante por franja horaria, viajes origen-destino). **No existe en los datos locales**:
no hay matriz OD, ni conteos de movilidad, ni LandScan día/noche para Perú (LandScan Global
entrega un único conteo ambiente de 24 h por año). La parte horaria está en `inwatch-04w`
(matriz de commuting del censo 2017).

Proxy elegido: **LandScan Global 2023** (población ambiente, promedio de 24 h), agregado a
la grilla canónica H3 res-8. Es el más defendible porque es el único producto local que
modela explícitamente dónde *está* la gente y no dónde *duerme*. Sus límites, que el
resultado hereda: resolución nativa ~1 km (más grueso que la celda), es un modelo y no un
conteo, promedia día y noche, y no distingue a quién expone (un peatón de un conductor).

### Qué se manipula

El denominador de `riesgo = Σ latente 2018-2024 / población` por celda:

| Nombre | Fuente | Tipo |
|---|---|---|
| `residente` | WorldPop (`h3_population`) | residencial — **baseline** |
| `ambiente` | LandScan 2023 (`h3_landscan`) | ambiente 24 h — **el tratamiento** |
| `residente_meta` | Meta/HRSL 2020 (`h3_meta_population`) | residencial desde edificaciones — **control** |
| `ambiente_2020` | LandScan 2020 | ambiente — control temporal |

### Métrica de reordenamiento (la misma escala que E1)

Contra el baseline `residente`, sobre las celdas con denominador ≥ piso en **las tres**
fuentes principales (misma población de celdas para todas las comparaciones):

1. **ρ de Spearman** entre rankings (la misma que `rango_espacial.spearman` de E1).
2. **Solapamiento del top-50** (la misma que `rango_espacial.top_overlap` de E1).
3. Robustez de la métrica: τ-b de Kendall y solapamiento del top-k con k ∈ {25, 100, 200}.

Piso primario: **500 personas** en las tres fuentes. Se reportan también 0, 200, 1000 y
2000. Sin piso, dividir entre poblaciones de dos dígitos fabrica riesgos gigantes, y esa
celda no es «riesgosa», es **no evaluable** (se dibuja deshilachada, regla dura 1).

### Criterios de decisión (fijados ahora)

- **Reordena** si, en el piso primario: ρ(ambiente) < 0,80 **y** top-50(ambiente) < 0,50,
  **y** el control está claramente más alineado: ρ(residente_meta) − ρ(ambiente) > 0,20 con
  el IC bootstrap 95 % (1000 remuestreos de celdas) excluyendo cero.
- **No reordena** (como E1) si ρ(ambiente) ≥ 0,95 y top-50(ambiente) ≥ 0,70.
- **Se cae la conclusión** si el control reordena tanto como el tratamiento (diferencia de ρ
  con IC que incluye cero): lo que movería el mapa sería el ruido entre rasters, no la
  distinción ambiente-vs-residente.
- **Ambiguo** en cualquier otro caso, y se reporta como tal.

**Kill-criterion de resolución** (de infelix): si LandScan a ~1 km no tiene variación
intra-distrital —fracción de la varianza de `log(1+pob)` dentro de distrito < 10 %, o menos
valores distintos que WorldPop—, el experimento se cierra como negativo de resolución.

**Sub-predicción direccional** (la parte entre paréntesis de Idea 17): el cambio de rango al
pasar a ambiente, `Δrango = rango_ambiente − rango_residente` (positivo = sube en riesgo),
debería correlacionar **negativamente** con la densidad de POI comerciales/nightlife de OSM
(`h3_osm_features`, independiente de las dos poblaciones). Se reporta ρ con su IC. Aviso de
diseño: `riesgo_amb / riesgo_res = pob_res / pob_amb`, así que el sentido del reordenamiento
lo fija por completo el cociente entre denominadores; esta prueba mide si ese cociente
coincide con lo comercial, no algo del delito.

## Enmienda posterior al pre-registro: el numerador pre-registrado es circular

Encontrado **después** de la primera corrida y declarado acá como tal. La superficie de
E1 (`crime_latent_surface.parquet`) se construye en infelix
(`scripts/build_latent_surface_h3.py`, `--pattern population`, el default) repartiendo
el latente de cada distrito entre sus celdas **en proporción a WorldPop**. Entonces
`latente / residente` es **exactamente constante dentro de cada distrito** (verificado:
max/min = 1 en todos los distritos evaluables; `circularidad.parquet`). El mapa «por
residente» es una coropleta distrital, y dividir entre cualquier otra población lo
reordena **por construcción**, sin que el delito intervenga.

Por eso el sondeo de las notas del bead exagera el efecto, y por eso se añadieron dos
numeradores cuyo patrón intra-distrital no sale de la población:

- `latente_hibrido` — la superficie híbrida de infelix (`slr-us4`): patrón intra-distrital
  tomado de las denuncias geocodificadas, suavizado Dirichlet (M = 10) hacia la población.
  **Es el numerador de la conclusión.**
- `observado_geo` — denuncias geocodificadas crudas, sin corrección latente.

El numerador pre-registrado (`latente`) se sigue reportando, marcado como circular. Los
umbrales de decisión no se cambiaron.

## Resultado (exploratorio)

Las cifras están en `reordenamiento.parquet`, `bootstrap.parquet` y compañía, y en el
notebook; entran acá con ancla `CANON:` cuando se emitan. En palabras:

- **Con el numerador no circular, la predicción se cumple según los criterios fijados**,
  pero con menos margen que el sondeo. El orden global se mueve de forma moderada; el
  **tope del ranking se renueva casi por completo**, mientras que el control residencial
  conserva la mayor parte del tope. La diferencia de ρ control-menos-ambiente es positiva
  con IC que excluye cero en todos los pisos, y queda cerca del umbral de 0,20.
- **E1 queda en pie en la misma escala**: sobre la superficie híbrida y las mismas celdas,
  la corrección por sesgo de denuncia sigue sin reordenar. Denominador y corrección son
  dos controles de naturaleza distinta.
- **No es desalineación de píxel**: agregado a distrito, los dos residenciales coinciden
  casi perfecto y el ambiente sigue discrepando. El kill-criterion de resolución pasa.
- **Dentro de cada distrito, el efecto es chico**: el reordenamiento ambiente-vs-residente
  apenas supera al ruido entre las dos fuentes residenciales. El reordenamiento vive sobre
  todo **entre distritos y en la cola alta**.
- **La sub-predicción direccional se cumple**: bajan San Isidro, Miraflores, Cercado y el
  anillo comercial; suben Ate, Villa El Salvador, Puente Piedra, Cieneguilla. Con la
  salvedad de diseño ya dicha (lo fija el cociente LandScan/WorldPop, y LandScan usa uso
  de suelo como insumo).
- **Mesa Redonda casi no se mueve** con el numerador no circular: su delito está tan
  concentrado que sigue en el tope incluso dividiendo entre su población ambiente.
- **El Spearman depende de cómo se tratan las celdas chicas** (piso contra prior aditivo);
  el recambio del top-k es la señal robusta a esa elección.

## Unidad espacial

`h3_8`, clave `h3_index`, sobre las celdas de la superficie latente. La auditoría de
resolución usa la grilla canónica completa. Agregaciones de robustez a H3 res-7 y a
distrito (`ubigeo`), sumando numerador y denominador antes de dividir.

## Datos

| Artefacto | Origen | Unidad | Notas |
|---|---|---|---|
| `crime_latent_surface.parquet` | catálogo `crime_latent_surface` | `h3_8`×año×cat | numerador pre-registrado (circular) |
| `crime_latent_surface_hybrid.parquet` | `infelix/data/silver/` | `h3_8`×año×cat | numerador no circular |
| `h3_observed_geocoded.parquet` | catálogo `h3_observed_geocoded` | `h3_8`×año×cat | denuncias geocodificadas |
| `h3_population.parquet` | `infelix/.../h3_features/` | `h3_8` | WorldPop, residente (baseline) |
| `h3_landscan.parquet` | `infelix/.../h3_features/` | `h3_8` | LandScan 2020/2023, ambiente 24 h |
| `h3_meta_population.parquet` | `infelix/.../h3_features/` | `h3_8` | Meta/HRSL 2020, residente (control) |
| `h3_osm_features.parquet` | `infelix/.../h3_features/` | `h3_8` | POI para la sub-predicción |
| `h3_admin.parquet` | catálogo `h3_admin` | `h3_8` | distrito |

Todo read-only. Las que no están en `registry/fuentes.toml` se resuelven por el origen
`infelix` del catálogo; darlas de alta queda pendiente (no se tocó `registry/` en este PR).

## Qué se ve

Tres mapas sobre la misma rampa `carrera_teal` de E1: percentil de riesgo por residente,
percentil por el denominador elegido, y el cambio de percentil en una divergente
tierra↔teal (sin verde ni rojo). Celdas bajo el piso en cualquier fuente: deshilachadas.
Controles: numerador, denominador de contraste y piso. Debajo, las tablas de robustez.

## Cómo correr

```bash
uv sync --extra geo --extra viz
uv run python experiments/denominador/loader.py    # → data/silver/denominador/
uv run marimo edit experiments/denominador/notebook.py
```

## Verificación

- [x] `uv run pytest tests/test_denominador.py`: 7 tests sintéticos + 3 `needs_data`
- [x] `uv run canon check` sin fallos (este README no tiene anclas propias todavía)
- [x] `uv run ruff check .` limpio
- [x] Loader determinista: dos corridas dan parquets byte a byte idénticos
- [x] El notebook corre de punta a punta (`marimo export html`) sin traceback
- [ ] Revisión en oscuro y deuteranopia de la divergente tierra↔teal: pendiente

## Decisiones tomadas

- **No se emite al registro todavía.** Es una corrida exploratoria nocturna; emitir
  requiere decidir claves (`rango_espacial.denominador.*`?) y policy.
- **Percentiles y no tasas en el mapa**: la escala es compartida por construcción y
  evita que un puñado de celdas con población chica sature la rampa.
- **Población común para todas las comparaciones**: si cada denominador eligiera sus
  celdas, la ρ mezclaría reordenamiento con cambio de universo.
- **LandScan 2023 como tratamiento y 2020 como control temporal**, no al revés: 2023 es el
  más cercano al final de la ventana 2018-2024.
- **Descartado**: pedir día/noche a LandScan (no existe para Perú) e inventar una
  población flotante a partir de POI (sería circular con la prueba direccional).

## Siguientes pasos

- Decidir si E1 debería migrar a la superficie híbrida (su hallazgo se sostiene en ella).
- Emitir las métricas con procedencia y anclarlas acá.
- `inwatch-04w`: la matriz de commuting del censo 2017 para el day/night real.
- Riesgo por expuesto por categoría: para violencia familiar el residente es el
  denominador correcto; un mapa mixto por categoría es el producto honesto.

## Chequeo posterior (literatura): un segundo proxy de población ambiente

> **Chequeo posterior (literatura)**, añadido el 2026-09-25 después del resultado. No
> reescribe la predicción, los umbrales ni la enmienda de arriba: los reusa tal cual.

**Por qué.** Whipp et al. 2021 (*IJGI*, doi:10.3390/ijgi10030131) muestran que las fuentes
de población ambiente no coinciden entre sí, y Malleson & Andresen 2016 que proxies
distintos dan hot spots distintos. Con un solo proxy (LandScan, que además usa uso de suelo
como insumo) parte del reordenamiento podría ser del modelo de LandScan y no del riesgo.

**Qué hay en local.** No hay empleo, viajes, matriz OD ni telefonía: el derivado del censo
2017 no trae commuting (`inwatch-04w`). Lo que sí hay, todo en `h3_features` de infelix,
son **atractores y actividad**, no poblaciones:

| Proxy | Fuente | Por qué sirve | Por qué no es ideal |
|---|---|---|---|
| `ambiente_viirs` (**el que decide**) | VIIRS DNB, radiancia media 2018-2023 | sensor distinto, continuo, > 0 en las 993 celdas; no es circular con la prueba direccional | mide luz, no gente; satura en el centro; versiones de LandScan han usado luces nocturnas como insumo, así que la independencia es parcial |
| `ambiente_poi` (sensibilidad) | OSM, suma de las 7 categorías de POI + 1 | es el proxy de «atractores» que usan Malleson & Andresen | 102 de 993 celdas sin POI; circular con la prueba direccional (por eso no decide) |

Los dos se reescalan para sumar lo mismo que LandScan en el universo; el ranking no depende
de esa escala.

**Criterio, fijado antes de calcular.** Mismo universo (piso 500 en las tres fuentes
principales, n = 993), mismo numerador (`latente_hibrido`), mismas métricas y umbrales que
arriba, con `ambiente_viirs` en lugar de LandScan:

- **El veredicto se sostiene** si `ambiente_viirs` también cumple los tres: ρ < 0,80,
  top-50 < 0,50 y ρ(residente_meta) − ρ(viirs) > 0,20 con IC95 bootstrap (1000, misma
  semilla) que excluye cero.
- **Se debilita** si cumple ρ y top-50 pero no la diferencia contra el control.
- **Se cae** (el reordenamiento es propiedad de LandScan) si `ambiente_viirs` no cumple ρ
  ni top-50.
- **Coincidencia entre proxies**: se reporta ρ entre las poblaciones (LandScan vs VIIRS),
  ρ entre los cocientes ambiente/residente (lo que fija el reordenamiento) y ρ y top-50
  entre los dos mapas de riesgo. Se lee como «coinciden» con ρ ≥ 0,80 entre riesgos, a
  secas; no hay umbral de la literatura para esto.

### Resultado del chequeo posterior (exploratorio, sin emitir)

`uv run python experiments/denominador/segundo_proxy.py` → `segundo_proxy*.parquet`
(determinista, byte a byte). Universo n = 993, numerador `latente_hibrido`:

| contra residente | ρ | top-50 | ρ(meta) − ρ(proxy), IC95 | veredicto |
|---|---|---|---|---|
| LandScan 2023 | 0,613 | 0,12 | 0,223 [0,185; 0,264] | se sostiene |
| **VIIRS (decide)** | **0,800** | **0,46** | **0,036 [0,011; 0,060]** | **ambiguo** |
| POI OSM (sensibilidad) | 0,276 | 0,08 | 0,561 [0,504; 0,621] | se sostiene |

Con `observado_geo` el patrón es el mismo (VIIRS: ρ 0,853, top-50 0,40, Δρ 0,028).

**Los proxies no coinciden entre sí**, como anticipaba Whipp et al. Entre LandScan y VIIRS:
ρ 0,68 entre poblaciones, **0,22 entre cocientes ambiente/residente** (lo que fija el
reordenamiento) y 0,59 entre mapas de riesgo, con top-50 compartido de 0,08. VIIRS y POI
coinciden todavía menos (ρ 0,31 entre riesgos). La sub-predicción direccional no se
replica con VIIRS: ρ(Δpercentil, POI comerciales) = +0,07, contra −0,33 con LandScan.

**Lectura.** Con el proxy que decide, el veredicto **no se sostiene tal como está
escrito**: VIIRS también renueva a medias el tope (top-50 0,46), pero el orden global se
mueve apenas más que con el segundo residencial. Lo que resiste a los tres proxies es solo
esto: *cualquier* denominador ambiente renueva el top-50 más que el control residencial.
**Cuáles** celdas suben y bajan, y si bajan las comerciales, depende del proxy, así que
no se puede afirmar desde LandScan solo. Hace falta un denominador de expuestos de verdad
(commuting censal, `inwatch-04w`, o telefonía) para arbitrar entre proxies.
