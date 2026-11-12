import asyncio
import threading
import winocr
from PIL import Image
from config import settings

# WinRT Media.Ocr requiere serialización y un event loop persistente en el proceso
# para evitar fallos nativos (RaiseFailFastException) al destruir/recrear loops con asyncio.run().
_ocr_lock = threading.Lock()
_ocr_loop = None


def _get_ocr_loop():
    global _ocr_loop
    if _ocr_loop is None or _ocr_loop.is_closed():
        _ocr_loop = asyncio.new_event_loop()
    return _ocr_loop


def recognize_image(image: Image.Image, lang: str = None) -> dict:
    """
    Ejecuta OCR sobre una imagen PIL utilizando el motor nativo de Windows (WinOCR).
    Retorna un diccionario estructurado con líneas, palabras y coordenadas normalizadas.
    """
    if lang is None:
        lang = settings.OCR_LANG

    # Asegurar modo RGBA/RGB
    if image.mode != "RGB":
        image = image.convert("RGB")

    width, height = image.size

    # Ejecutar reconocimiento protegido con loop persistente (sin asyncio.run repetitivo)
    with _ocr_lock:
        loop = _get_ocr_loop()
        raw_result = winocr.picklify(
            loop.run_until_complete(winocr.to_coroutine(winocr.recognize_pil(image, lang=lang)))
        )

    lines_output = []

    for raw_line in raw_result.get("lines", []):
        line_text = raw_line.get("text", "").strip()
        words = []

        for w in raw_line.get("words", []):
            rect = w.get("bounding_rect", {})
            words.append({
                "text": w.get("text", ""),
                "x": float(rect.get("x", 0)),
                "y": float(rect.get("y", 0)),
                "w": float(rect.get("width", 0)),
                "h": float(rect.get("height", 0))
            })

        if words:
            min_x = min(w["x"] for w in words)
            min_y = min(w["y"] for w in words)
            max_x = max(w["x"] + w["w"] for w in words)
            max_y = max(w["y"] + w["h"] for w in words)

            lines_output.append({
                "text": line_text,
                "x": min_x,
                "y": min_y,
                "w": max_x - min_x,
                "h": max_y - min_y,
                "rel_y": min_y / height if height > 0 else 0,
                "words": words
            })

    return {
        "width": width,
        "height": height,
        "lines": lines_output
    }
