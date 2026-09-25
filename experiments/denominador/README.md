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
