"""Hornea el basemap de la pieza en paleta nocturna: el suelo que usa la escena.

Gemelo de `asset_basemap.py` —misma ventana, mismas capas, mismo truco de orla y
relleno— y cambia solo la paleta. Se mantienen los dos porque el claro sigue sirviendo
para figuras impresas, donde el fondo es papel de verdad.

El motivo del nocturno no es estético: la patada inicial mediana de la muestra son las
20:00, así que las trece horas que la pieza recorre son de noche. El mapa claro afirmaba
lo contrario.

    uv run --extra geo --extra viz python experiments/pulso-estadios/pieza/suelo.py
"""
import json

import matplotlib

matplotlib.use("Agg")
import geografia
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rutas
from matplotlib.collections import LineCollection
from shapely.geometry import Point

ANCHO_PX, DPI = 6000, 300
# Asfalto casi negro, calles en gris cálido, agua azul profundo. La jerarquía se mantiene
# con el mismo truco de orla y relleno, solo que la orla ahora OSCURECE en vez de aclarar.
FONDO, AGUA, VERDE = "#0b0d10", "#0f1c27", "#101b14"
ORLA_MENOR, RELLENO_MENOR = "#16191e", "#4e5054"
ORLA_MAYOR, RELLENO_MAYOR = "#1d2127", "#8f8a7d"
LIMITE, RIEL = "#262b31", "#33383f"

est, lim, caja = geografia.ventana()
capas = geografia.cartografia(caja, lim)
ancho_m, alto_m = lim[1] - lim[0], lim[3] - lim[2]
alto_px = int(round(ANCHO_PX * alto_m / ancho_m))
print(f"ventana {ancho_m/1000:.1f} x {alto_m/1000:.1f} km → {ANCHO_PX}x{alto_px} px "
      f"({ancho_m/ANCHO_PX:.1f} m/px)")

fig = plt.figure(figsize=(ANCHO_PX / DPI, alto_px / DPI), dpi=DPI)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_facecolor(FONDO)
fig.patch.set_facecolor(FONDO)


def segmentos(gdf):
    out = []
    for geom in gdf.geometry:
        if geom is None:
            continue
        for p in (geom.geoms if geom.geom_type.startswith("Multi") else [geom]):
            out.append(np.column_stack(p.xy))
    return out


capas["agua"].plot(ax=ax, facecolor=AGUA, edgecolor="none", zorder=1)
capas["verdes"].plot(ax=ax, facecolor=VERDE, edgecolor="none", zorder=2)

menores, mayores = segmentos(capas["vias_menores"]), segmentos(capas["vias_mayores"])
ax.add_collection(LineCollection(menores, colors=ORLA_MENOR, linewidths=1.25, zorder=3,
                                 capstyle="round"))
ax.add_collection(LineCollection(menores, colors=RELLENO_MENOR, linewidths=0.65, zorder=4,
                                 capstyle="round"))
ax.add_collection(LineCollection(mayores, colors=ORLA_MAYOR, linewidths=3.0, zorder=5,
                                 capstyle="round"))
ax.add_collection(LineCollection(mayores, colors=RELLENO_MAYOR, linewidths=1.9, zorder=6,
                                 capstyle="round"))
ax.add_collection(LineCollection(segmentos(capas["rieles"]), colors=RIEL,
                                 linewidths=0.9, linestyles=(0, (6, 4)), zorder=7))
ax.add_collection(LineCollection(segmentos(capas["distritos"]), colors=LIMITE,
                                 linewidths=1.1, linestyles=(0, (7, 5)), zorder=8))

ax.set_xlim(lim[0], lim[1])
ax.set_ylim(lim[2], lim[3])
ax.set_aspect("equal")
ax.set_axis_off()
rutas.asegurar()
fig.savefig(rutas.SUELO, dpi=DPI, facecolor=FONDO, pad_inches=0)
plt.close(fig)

# La extensión en lon/lat, que es lo que el BitmapLayer de deck necesita para pegar la
# imagen al suelo. Se guarda al lado del png: si una se regenera sin la otra, la escena
# dibuja la ciudad corrida.
esquinas = gpd.GeoSeries([Point(lim[0], lim[2]), Point(lim[1], lim[3])],
                         crs=geografia.CRS_METRICO).to_crs(4326)
bounds = [float(esquinas[0].x), float(esquinas[0].y),
          float(esquinas[1].x), float(esquinas[1].y)]
rutas.SUELO_BOUNDS.write_text(json.dumps(bounds))
print(f"→ {rutas.SUELO.name} {rutas.SUELO.stat().st_size / 1e6:.1f} MB · "
      f"bounds {[round(b, 5) for b in bounds]}")
