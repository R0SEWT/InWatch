"""Captura: una sola página, y por frame se fija cámara, hora y foco.

Falla con código de salida distinto de cero si algún frame sale plano o si el render nunca
se asentó. No es paranoia: el encadenado a ffmpeg es un `&&`, así que una captura que avisa
y sale en 0 deja pasar un video con frames en blanco.

Necesita el extra `pieza` (playwright + pillow) y el chromium de playwright:

    uv run --extra pieza python -m playwright install chromium
    uv run --extra pieza python experiments/pulso-estadios/pieza/captura.py
"""
import json
import time

import rutas
from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright

DEST = rutas.FRAMES
DEST.mkdir(parents=True, exist_ok=True)
for f in DEST.glob("*.png"):
    f.unlink()
ARGS = ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--disable-gpu-sandbox",
        "--allow-file-access-from-files"]
guion = json.loads(rutas.GUION.read_text())


def plano(ruta):
    st = ImageStat.Stat(Image.open(ruta).convert("RGB").resize((160, 85)))
    return sum(st.stddev) / 3 < 12


with sync_playwright() as p:
    b = p.chromium.launch(channel="chromium", headless=True, args=ARGS)
    pg = b.new_page(viewport={"width": 900, "height": 480}, device_scale_factor=2)
    # Sin teselas externas ya no hay nada en vuelo que esperar: el suelo es un asset local.
    vuelo = {"n": 0}
    colgados: list[int] = []

    pg.goto(rutas.ESCENA.as_uri(), wait_until="load", timeout=120_000)
    pg.wait_for_function("window.listo === true", timeout=60_000)
    fallo = pg.evaluate("window.errorEscena || null")
    if fallo:
        raise SystemExit(f"la escena no se pudo dibujar: {fallo}")
    pg.wait_for_timeout(7000)

    def quieto(limite=14.0) -> bool:
        """True si el render se asentó; False si se agotó el límite esperándolo."""
        fin, estable = time.time() + limite, 0
        while time.time() < fin:
            if vuelo["n"] == 0 and pg.evaluate("window.pintados()") > 0:
                estable += 1
                if estable >= 2:
                    return True
            else:
                estable = 0
            pg.wait_for_timeout(110)
        return False

    for i, paso in enumerate(guion):
        pg.evaluate(
            "a => { window.setVista(a.vista); window.setPesos(a.pesos); "
            "window.setEstado(a.estado); window.setFoco(a.foco); }", paso)
        if not quieto():
            colgados.append(i)
        pg.wait_for_timeout(150)
        destino = DEST / f"f{i:03d}.png"
        pg.screenshot(path=str(destino))
        if plano(destino):
            pg.wait_for_timeout(1600)
            pg.screenshot(path=str(destino))
        if i % 25 == 0:
            print("frame", i, flush=True)
    b.close()

malos = [f.name for f in sorted(DEST.glob("*.png")) if plano(f)]
print("capturados:", len(list(DEST.glob("*.png"))), "· planos:", len(malos), malos[:4],
      "· render colgado en:", len(colgados), colgados[:4])

# Salir con error, no solo avisar. Antes esto era un `print` y la captura terminaba en 0:
# si el render se colgaba, ffmpeg encodeaba un video con frames en blanco y el pipeline
# seguía como si nada. Un frame plano o un render que nunca se asentó son exactamente la
# condición que el paso de captura existe para detectar.
if malos or colgados:
    raise SystemExit(
        f"la captura no es usable: {len(malos)} frame(s) plano(s) {malos[:6]} y "
        f"{len(colgados)} con el render sin asentarse {colgados[:6]}.\n"
        "Revisá la escena con `probe.py` antes de volver a capturar."
    )
