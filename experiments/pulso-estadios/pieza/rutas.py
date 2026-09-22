"""Dónde escribe la pieza. Un solo lugar, para que los seis pasos no discrepen.

Todo lo que la pieza genera —el suelo horneado, el JSON de estados, el HTML de la escena,
los frames y el mp4— es **regenerable**, así que va bajo ``data/``, que el repo ignora
entero. La regla del repo es «regenerable → gitignored; reporte → versionado», y acá el
reporte versionado es el póster y el README, no 18 MB de basemap.

La raíz se descubre subiendo hasta el ``pyproject.toml``, igual que hace ``canon``: así
los scripts corren desde cualquier directorio sin un ``sys.path`` inventado ni una ruta
de máquina.
"""

from __future__ import annotations

from pathlib import Path

from inwatch.canon.config import find_root

RAIZ = find_root(Path(__file__).resolve().parent)
SALIDA = RAIZ / "data" / "pieza" / "pulso-estadios"

SUELO = SALIDA / "suelo_noche.png"
SUELO_BOUNDS = SALIDA / "suelo_bounds.json"
DATOS = SALIDA / "datos.json"
GUION = SALIDA / "guion.json"
ESCENA = SALIDA / "escena.html"
FRAMES = SALIDA / "frames"
VIDEO = SALIDA / "pulso-estadios.mp4"

# El perfil por estadio con ventana móvil de 3 h, que produce el loader del experimento.
PERFIL = RAIZ / "data" / "silver" / "pulso-estadios" / "perfil_estadio_movil.parquet"


def asegurar() -> Path:
    """Crea el directorio de salida y lo devuelve."""
    SALIDA.mkdir(parents=True, exist_ok=True)
    return SALIDA
