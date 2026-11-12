import asyncio
import io
import threading
from PIL import Image
import winrt.windows.globalization as wg
import winrt.windows.graphics.imaging as wgi
import winrt.windows.media.ocr as wmo
import winrt.windows.storage.streams as wss
from config import settings

# WinRT Media.Ocr requiere serialización, un event loop persistente y caché de OcrEngine
# en el proceso para evitar corrupción de heap (0xc0000374) y RaiseFailFastException.
_ocr_lock = threading.Lock()
_ocr_loop = None
_ocr_engines = {}


def _get_ocr_loop():
    global _ocr_loop
    if _ocr_loop is None or _ocr_loop.is_closed():
        _ocr_loop = asyncio.new_event_loop()
    return _ocr_loop


def _get_ocr_engine(lang: str) -> wmo.OcrEngine:
    engine = _ocr_engines.get(lang)
    if engine is None:
        engine = wmo.OcrEngine.try_create_from_language(wg.Language(lang))
        if engine is None:
            engine = wmo.OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError(f"No se pudo inicializar Windows OcrEngine para idioma '{lang}'.")
        _ocr_engines[lang] = engine
    return engine


async def _recognize_png_bytes(png_bytes: bytes, engine: wmo.OcrEngine):
    stream = wss.InMemoryRandomAccessStream()
    writer = wss.DataWriter(stream.get_output_stream_at(0))
    sb = None
    try:
        writer.write_bytes(png_bytes)
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()
        stream.seek(0)

        # Usar BitmapDecoder nativo de Windows (WIC) en lugar de create_copy_from_buffer de winocr
        # para evitar corrupción de heap (0xc0000374) con buffers RGBA grandes/impares en winrt.
        decoder = await wgi.BitmapDecoder.create_async(stream)
        sb = await decoder.get_software_bitmap_async()
        ocr_result = await engine.recognize_async(sb)

        lines_data = []
        for raw_line in ocr_result.lines:
            words_data = []
            for w in raw_line.words:
                rect = w.bounding_rect
                words_data.append({
                    "text": w.text,
                    "x": float(rect.x),
                    "y": float(rect.y),
                    "w": float(rect.width),
                    "h": float(rect.height),
                })
            lines_data.append((raw_line.text.strip(), words_data))
        return lines_data
    finally:
        if sb is not None:
            try:
                sb.close()
            except Exception:
                pass
        try:
            writer.close()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass


def recognize_image(image: Image.Image, lang: str = None) -> dict:
    """
    Ejecuta OCR sobre una imagen PIL utilizando el motor nativo de Windows (WinRT Media.Ocr)
    mediante BitmapDecoder (WIC) para evitar fallos de memoria en buffers RGBA crudos.
    Retorna un diccionario estructurado con líneas, palabras y coordenadas normalizadas.
    """
    if lang is None:
        lang = settings.OCR_LANG

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    # Respetar límite máximo del motor WinRT OCR
    max_dim = getattr(wmo.OcrEngine, "max_image_dimension", 10000) or 10000
    width, height = image.size
    if max(width, height) > max_dim:
        scale = max_dim / max(width, height)
        image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
        width, height = image.size

    buf = io.BytesIO()
    image.save(buf, format="PNG", compress_level=1)
    png_bytes = buf.getvalue()

    with _ocr_lock:
        loop = _get_ocr_loop()
        engine = _get_ocr_engine(lang)
        raw_lines = loop.run_until_complete(_recognize_png_bytes(png_bytes, engine))

    lines_output = []
    for line_text, words in raw_lines:
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
