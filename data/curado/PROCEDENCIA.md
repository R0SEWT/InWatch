# Insumos curados

Archivos chicos, públicos y **no regenerables con un comando**, versionados a propósito
para que un clon del repo corra sin depender de máquinas ajenas. Misma política que el
gazetteer de estaciones del repo de origen.

La regla del repo es que ningún número portante se escribe a mano. Un dato versionado sin
forma de re-derivarlo es la versión-dato del mismo problema, así que cada archivo de aquí
declara de dónde sale y cómo reproducirlo.

## `DISTRITOS_LIMITES_area_a.zip`

Los 5 distritos del área A del TP, recortados del shapefile distrital nacional.

| | |
|---|---|
| Qué es | shapefile de 5 polígonos, EPSG:4326, campos `UBIGEO`, `PROVINCIA`, `DISTRITO` |
| UBIGEO | 150101 Cercado de Lima · 150115 La Victoria · 150122 Miraflores · 150131 San Isidro · 150141 Surquillo |
| sha256 | `4e013ad626a1ce16aad7…` (el completo lo registra `canon` como input) |
| Titularidad | INEI, límites distritales (dato público) |
| Padre | fuente `distritos_limites` = `infelix:data/datasets/DISTRITOS_LIMITES.zip`, sha256 `6e305a08…` |

**Por qué el zip y no un GeoJSON**: es la única codificación que reproduce el grafo
exacto. Se midió re-codificando el mismo polígono — GeoJSON a 1 cm da 7.559/15.812
aristas, a 11 cm da 7.558/15.809, simplificado a 1 m da 7.564/15.823, contra los
**7559 nodos** <!-- CANON: corredores.conteo.nodos = 7559 --> y **15813 aristas**
<!-- CANON: corredores.conteo.aristas = 15813 --> canónicos. Un segundo polígono "casi igual" es
exactamente la deriva silenciosa que el registro existe para impedir.

**Cómo re-derivarlo** desde el padre, que vive en infelix y es de solo lectura:

```python
import zipfile
from pathlib import Path
import geopandas as gpd
from inwatch import fuentes

UBIGEOS = ["150101", "150115", "150122", "150131", "150141"]
padre = fuentes.ruta("distritos_limites")
capa = gpd.read_file(f"/vsizip/{padre}/DISTRITOS.shp", engine="pyogrio")
sub = capa[capa["UBIGEO"].astype(str).isin(UBIGEOS)]

destino = Path("data/curado/shp_a"); destino.mkdir(parents=True, exist_ok=True)
sub.to_file(destino / "DISTRITOS.shp", engine="pyogrio", encoding="utf-8")
with zipfile.ZipFile("data/curado/DISTRITOS_LIMITES_area_a.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for f in sorted(destino.iterdir()):
        z.write(f, f.name)
```

El zip resultante no es byte a byte idéntico —lleva marcas de tiempo—, pero su geometría
sí, y es lo que fija el grafo. Si hay que regenerarlo, **verifica antes de commitear** que
el loader sigue dando 7559 nodos <!-- CANON: corredores.conteo.nodos = 7559 --> y
15813 aristas <!-- CANON: corredores.conteo.aristas = 15813 -->.
