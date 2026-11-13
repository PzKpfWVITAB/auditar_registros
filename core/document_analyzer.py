import os
import re
import time
import threading
import pymupdf  # PyMuPDF
from PIL import Image
from config import settings
from core.ocr_engine import recognize_image
from core.delegaciones import detect_delegacion_from_lines, get_delegacion_by_clave, get_delegacion_display

# PyMuPDF (fitz) no es thread-safe a nivel C; este lock protege apertura y renderizado
_pdf_lock = threading.Lock()

MONTHS = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
    "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
    "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12
}

def parse_filename(filename: str):
    """
    Descompone el nombre del archivo según el estándar [DELEGACION]_[AÑO]_[REGISTRO].pdf
    Ejemplo: '01_2011_233.pdf' -> ('01', 2011, '233')
    """
    clean_name = os.path.basename(filename)
    match = re.search(r"^([A-Za-z0-9]+)_(\d{4})_(\d+)(?:\.(?:pdf|jpe?g|png))?$", clean_name, re.IGNORECASE)
    if match:
        return {
            "valido": True,
            "delegacion": match.group(1),
            "anio": int(match.group(2)),
            "registro": match.group(3)
        }
    return {
        "valido": False,
        "delegacion": None,
        "anio": None,
        "registro": None
    }

def extract_page_image(pdf_path: str, page_number: int = 0, dpi: int = None) -> Image.Image:
    """
    Obtiene la imagen óptima de la página del PDF para OCR:
    1. Si es un PDF escaneado con imagen embebida, extrae la imagen original sin pérdida de resolución.
    2. Si es vectorial o no tiene imagen embebida directa, renderiza a pixmap con DPI optimizado (por defecto OCR_DPI).
    3. Si la ruta es una imagen directa (.jpg, .png), la abre directamente.
    Soporta rutas locales y rutas de red UNC.
    """
    import io
    if dpi is None:
        dpi = settings.OCR_DPI
    # Si la ruta es directamente una imagen (para pruebas o formatos mixtos)
    if pdf_path.lower().endswith((".jpg", ".jpeg", ".png")):
        img = Image.open(pdf_path)
        img.load()
    else:
        with _pdf_lock:
            doc = pymupdf.open(pdf_path)
            try:
                if len(doc) <= page_number:
                    raise ValueError(
                        f"El PDF solo contiene {len(doc)} páginas. No se puede acceder a la {page_number}."
                    )

                page = doc[page_number]
                img = None

                # Intentar extraer la imagen escaneada original nativa
                image_list = page.get_images(full=True)
                if image_list:
                    try:
                        xref = image_list[0][0]
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        candidate = Image.open(io.BytesIO(image_bytes))
                        candidate.load()
                        if candidate.width > 400 and candidate.height > 400:
                            img = candidate
                    except Exception:
                        img = None

                # Si no hay imagen embebida o falló, renderizar a DPI configurado
                if img is None:
                    zoom = dpi / 72.0
                    mat = pymupdf.Matrix(zoom, zoom)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            finally:
                doc.close()

    # Evitar imágenes gigantescas que puedan saturar memoria en WinOCR
    max_dim = 2400
    if img.width > max_dim or img.height > max_dim:
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

    return img

def analyze_document(file_path: str, lote_id: int = None) -> dict:
    """
    Analiza un documento PDF (o imagen) mediante análisis espacial y OCR.
    Retorna el resultado completo listo para almacenar en MySQL.
    """
    start_time = time.time()
    filename = os.path.basename(file_path)
    parsed_fn = parse_filename(filename)
    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0

    del_info_actual = get_delegacion_by_clave(parsed_fn["delegacion"])
    del_archivo_nombre = f"{del_info_actual['clave']} - {del_info_actual['nombre']}" if del_info_actual else (parsed_fn["delegacion"] or "-")

    base_result = {
        "lote_id": lote_id,
        "nombre_archivo": filename,
        "ruta_completa": file_path,
        "tamano_bytes": file_size,
        "delegacion_actual": parsed_fn["delegacion"],
        "delegacion_archivo_nombre": del_archivo_nombre,
        "anio_actual": parsed_fn["anio"],
        "registro_actual": parsed_fn["registro"],
        "delegacion_detectada_clave": None,
        "municipio_detectado": None,
        "delegacion_coincide": None,
        "confianza_delegacion": 0,
        "registro_encabezado": None,
        "registro_pie": None,
        "anio_detectado": None,
        "fecha_registro_texto": None,
        "registro_antecedente": None,
        "registro_final_detectado": None,
        "coincide_encabezado_pie": False,
        "estado": "ERROR_LECTURA",
        "nombre_propuesto": None,
        "confianza_score": 0,
        "motivo_discrepancia": None,
        "bounding_boxes": {},
        "tiempo_proceso_ms": 0
    }

    try:
        # 1. Obtener imagen de página 1
        img = extract_page_image(file_path, page_number=0)
    except Exception as e:
        base_result["estado"] = "ERROR_LECTURA"
        base_result["motivo_discrepancia"] = f"No se pudo abrir el archivo PDF: {str(e)}"
        base_result["tiempo_proceso_ms"] = int((time.time() - start_time) * 1000)
        return base_result

    # 2. Ejecutar OCR
    try:
        ocr_res = recognize_image(img)
    except Exception as e:
        base_result["estado"] = "ERROR_LECTURA"
        base_result["motivo_discrepancia"] = f"Fallo en el motor OCR: {str(e)}"
        base_result["tiempo_proceso_ms"] = int((time.time() - start_time) * 1000)
        return base_result

    img_w = ocr_res["width"]
    img_h = ocr_res["height"]
    lines = ocr_res["lines"]

    # 3. Segmentación espacial en 3 zonas
    # El recuadro superior de inscripción termina aprox. en rel_y = 0.24
    header_lines = []
    body_lines = []
    footer_lines = []

    for line in lines:
        rel_y = line["rel_y"]
        if rel_y < 0.24:
            header_lines.append(line)
        elif rel_y > 0.90:
            footer_lines.append(line)
        else:
            body_lines.append(line)

    bounding_boxes = {}

    # -------------------------------------------------------------
    # ZONA 0: Detección de Delegación / Oficina Registral
    # -------------------------------------------------------------
    del_detectada = detect_delegacion_from_lines(header_lines)
    del_detectada_clave = None
    municipio_detectado = None
    confianza_delegacion = 0
    delegacion_coincide = None

    if del_detectada:
        del_detectada_clave = del_detectada["clave"]
        municipio_detectado = del_detectada["nombre"]
        confianza_delegacion = del_detectada["confianza"]

        # Comparar con la clave del archivo (normalizada con ceros a la izquierda)
        if parsed_fn["valido"] and parsed_fn["delegacion"]:
            clave_archivo_norm = str(parsed_fn["delegacion"]).zfill(2)
            delegacion_coincide = (clave_archivo_norm == del_detectada_clave)

        del_box = del_detectada.get("bounding_box")
        if del_box:
            bounding_boxes["delegacion"] = {
                "text": del_detectada.get("raw_text", del_box.get("text", "")),
                "x": del_box["x"], "y": del_box["y"], "w": del_box["w"], "h": del_box["h"],
                "color": "#9333ea",  # Morado
                "label": f"Delegación: {del_detectada_clave} - {municipio_detectado} ({confianza_delegacion}%)"
            }

    base_result["delegacion_detectada_clave"] = del_detectada_clave
    base_result["municipio_detectado"] = municipio_detectado
    base_result["delegacion_coincide"] = delegacion_coincide
    base_result["confianza_delegacion"] = confianza_delegacion

    # -------------------------------------------------------------
    # ZONA 1: Recuadro Superior (Encabezado: rel_y < 0.24)
    # -------------------------------------------------------------
    reg_encabezado = None
    reg_encabezado_labeled = False
    fecha_reg_texto = None
    anio_detectado = None

    SPANISH_MONTHS = (
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "setiembre", "octubre", "noviembre", "diciembre"
    )
    FORBIDDEN_HEADER_WORDS = (
        "fecha", "volante", "recibo", "derecho", "hora", "calificador",
        "folio", "libro", "sección", "seccion", "notaria",
        "escritura", "volumen", "tomo", "pagina", "página",
        "publico", "oficina", "chiapas", "tuxtla", "estado", "inscrito",
        *SPANISH_MONTHS,
    )
    DATE_LIKE_RE = re.compile(
        r"\b\d{1,2}\s+(?:DE\s+)?[A-ZÁÉÍÓÚ]{3,}\s+(?:DEL?\s+)?(?:19\d{2}|20\d{2})\b",
        re.IGNORECASE,
    )

    def _left_col_text(line_obj, max_rel_x: float = 0.52) -> str:
        """Extrae solo las palabras de la columna izquierda del recuadro superior."""
        words = line_obj.get("words") or []
        if words and img_w > 0:
            left_words = [w["text"] for w in words if (w["x"] / img_w) < max_rel_x]
            return " ".join(left_words).strip()
        if img_w > 0 and (line_obj["x"] / img_w) < max_rel_x:
            return line_obj["text"].strip()
        return ""

    # Ubicar referencias Y clave dentro del recuadro:
    # - y_top_box: línea "Esta Oficina hace constar que este documento quedo inscrito bajo :"
    # - y_reg_label: línea "Registro:"
    # - y_fecha_label: línea "Fecha de Registro: DD DE MES DEL YYYY"
    y_top_box = None
    y_reg_label = None
    y_fecha_label = None
    for l in header_lines:
        left_t = _left_col_text(l, max_rel_x=0.60)
        t_low = l["text"].lower()
        left_low = left_t.lower()
        rel_x = l["x"] / img_w if img_w > 0 else 0

        if "inscrito" in t_low or "hace constar" in t_low or "documento quedo" in t_low:
            if 0.08 < l["rel_y"] < 0.18:
                y_top_box = l["rel_y"]

        if rel_x < 0.55 and l["rel_y"] > 0.11:
            has_year_and_text = bool(re.search(r"\b(?:19\d{2}|20\d{2})\b", left_t) and re.search(r"[A-Za-z]{3,}", left_t))
            if "fecha" in left_low or DATE_LIKE_RE.search(left_t) or (0.13 < l["rel_y"] < 0.22 and has_year_and_text):
                if y_fecha_label is None or l["rel_y"] < y_fecha_label:
                    y_fecha_label = l["rel_y"]
            elif "registro" in left_low and "publico" not in left_low and "oficina" not in left_low:
                if y_reg_label is None:
                    y_reg_label = l["rel_y"]

    y_min_reg = max(0.11, (y_top_box + 0.003) if y_top_box is not None else 0.11)
    if y_fecha_label is not None:
        y_max_reg = max(y_min_reg + 0.01, y_fecha_label - 0.002)
    elif y_reg_label is not None:
        y_max_reg = max(y_min_reg + 0.01, y_reg_label + 0.015)
    else:
        y_max_reg = 0.185

    # a) Búsqueda directa de "Registro: X" en la columna izquierda (NUNCA en líneas de Fecha/Volante/etc.)
    for l in header_lines:
        left_t = _left_col_text(l, max_rel_x=0.52)
        if not left_t:
            continue
        left_low = left_t.lower()
        if any(bad in left_low for bad in FORBIDDEN_HEADER_WORDS) or DATE_LIKE_RE.search(left_t):
            continue

        m_reg = re.search(r"\bRegistro\s*[:.]?\s*(\d{1,7})\b", left_t, re.IGNORECASE)
        if m_reg and y_min_reg <= l["rel_y"] <= y_max_reg + 0.02:
            reg_encabezado = m_reg.group(1)
            reg_encabezado_labeled = True
            bounding_boxes["encabezado"] = {
                "text": left_t,
                "x": l["x"], "y": l["y"], "w": l["w"], "h": l["h"],
                "color": "#10b981",  # Verde
                "label": f"Registro Encabezado: {reg_encabezado}"
            }
            break

    # b) Si "Registro:" estaba en una línea y el número quedó desfasado arriba/al lado
    #    Aceptar números en columna izquierda (0.14 <= rel_x < 0.50) estrictamente por ENCIMA de Fecha de Registro
    if not reg_encabezado:
        for l in header_lines:
            if not (y_min_reg <= l["rel_y"] < y_max_reg):
                continue
            left_t = _left_col_text(l, max_rel_x=0.50)
            if not left_t:
                continue
            left_low = left_t.lower()
            if any(bad in left_low for bad in FORBIDDEN_HEADER_WORDS) or DATE_LIKE_RE.search(left_t):
                continue

            # Buscar número entero limpio de 1 a 7 dígitos en los tokens de la columna izquierda
            left_words = [
                w for w in (l.get("words") or [])
                if img_w > 0 and 0.14 <= (w["x"] / img_w) < 0.50
            ]
            clean_num = None
            target_box = l
            if re.match(r"^\d{1,7}$", left_t):
                clean_num = left_t
            else:
                for w in left_words:
                    wt = w["text"].strip(".:,;-# ")
                    if re.match(r"^\d{2,7}$", wt):
                        clean_num = wt
                        target_box = w
                        break
                if not clean_num:
                    for w in left_words:
                        wt = w["text"].strip(".:,;-# ")
                        if re.match(r"^\d{1,7}$", wt):
                            clean_num = wt
                            target_box = w
                            break

            if clean_num:
                reg_encabezado = clean_num
                bounding_boxes["encabezado"] = {
                    "text": clean_num,
                    "x": target_box["x"], "y": target_box["y"],
                    "w": target_box["w"], "h": target_box["h"],
                    "color": "#10b981",
                    "label": f"Registro Encabezado: {reg_encabezado}"
                }
                break

    # c) Fallback con zoom 3x (margen blanco + autocontraste/nitidez) entre tope del recuadro y "Fecha de Registro:"
    if not reg_encabezado:
        try:
            from PIL import ImageOps, ImageFilter
            x0, x1 = int(img_w * 0.14), int(img_w * 0.51)
            crop_y1_rel = y_max_reg
            crop_y0_rel = max(y_min_reg, crop_y1_rel - 0.055)
            y0 = int(img_h * crop_y0_rel)
            y1 = int(img_h * crop_y1_rel)

            if x1 > x0 + 20 and y1 > y0 + 10:
                crop = img.crop((x0, y0, x1, y1))
                crop_3x = crop.resize((crop.width * 3, crop.height * 3), Image.Resampling.LANCZOS)
                pad = 40
                padded_rgb = ImageOps.expand(crop_3x.convert("RGB"), border=pad, fill="white")
                padded_sharp = ImageOps.autocontrast(
                    padded_rgb.convert("L").filter(ImageFilter.SHARPEN),
                    cutoff=2,
                )
                for crop_img in (padded_rgb, padded_sharp):
                    if reg_encabezado:
                        break
                    crop_ocr = recognize_image(crop_img)
                    for cl in crop_ocr["lines"]:
                        ct = cl["text"].strip()
                        ct_low = ct.lower()
                        if any(bad in ct_low for bad in FORBIDDEN_HEADER_WORDS) or DATE_LIKE_RE.search(ct):
                            continue
                        m_c = re.search(r"\bRegistro\s*[:.]?\s*(\d{1,7})\b", ct, re.IGNORECASE)
                        if m_c:
                            val = m_c.group(1)
                            reg_encabezado_labeled = True
                        elif re.match(r"^\d{1,7}$", ct.strip(".:,;-# ")):
                            val = ct.strip(".:,;-# ")
                        else:
                            val = None
                        if val:
                            reg_encabezado = val
                            bounding_boxes["encabezado"] = {
                                "text": ct,
                                "x": max(0.0, x0 + (cl["x"] - pad) / 3.0),
                                "y": max(0.0, y0 + (cl["y"] - pad) / 3.0),
                                "w": cl["w"] / 3.0,
                                "h": cl["h"] / 3.0,
                                "color": "#10b981",
                                "label": f"Registro Encabezado: {reg_encabezado}"
                            }
                            break
        except Exception:
            pass

    # d) Extracción de Fecha de Registro y Año (exclusivo del recuadro superior rel_y < 0.24)
    for l in header_lines:
        t = l["text"].strip()
        t_low = t.lower()
        m_date = re.search(r"(\d{1,2})\s+(?:DE\s+)?([A-Z]+)\s+(?:DEL?\s+)?(19\d{2}|20\d{2})", t, re.IGNORECASE)
        if m_date and ("fecha" in t_low or "registro" in t_low or l["rel_y"] > 0.13):
            fecha_reg_texto = m_date.group(0)
            anio_detectado = int(m_date.group(3))
            bounding_boxes["fecha_registro"] = {
                "text": t,
                "x": l["x"], "y": l["y"], "w": l["w"], "h": l["h"],
                "color": "#6366f1",  # Índigo
                "label": f"Fecha Registro: {fecha_reg_texto}"
            }
            break

    # Si aún no se detectó el año, buscar cualquier año de 4 dígitos dentro del recuadro (rel_y > 0.12)
    if not anio_detectado:
        for l in header_lines:
            if l["rel_y"] > 0.12:
                m_year = re.search(r"\b(20\d{2}|19\d{2})\b", l["text"])
                if m_year:
                    anio_detectado = int(m_year.group(1))
                    break

    # -------------------------------------------------------------
    # ZONA 2: Cuerpo y Trampa de "ANTECEDENTES"
    # -------------------------------------------------------------
    reg_antecedente = None
    in_antecedentes_zone = False

    for l in body_lines:
        t = l["text"].strip()
        if "antecedente" in t.lower():
            in_antecedentes_zone = True

        # Si encontramos "Registro: 283" en la zona de antecedentes o en el cuerpo medio
        m_ant = re.search(r"Registro:\s*(\d+)", t, re.IGNORECASE)
        if m_ant and (in_antecedentes_zone or l["rel_y"] > 0.40):
            reg_antecedente = m_ant.group(1)
            bounding_boxes["antecedente"] = {
                "text": t,
                "x": l["x"], "y": l["y"], "w": l["w"], "h": l["h"],
                "color": "#ef4444", # Rojo (Advertencia: trampa)
                "label": f"Antecedente (Trampa): {reg_antecedente}"
            }
            break

    # -------------------------------------------------------------
    # ZONA 3: Pie de Página (rel_y > 0.90, centrado, sin palabras de cuerpo/fecha)
    # -------------------------------------------------------------
    reg_pie = None
    FORBIDDEN_FOOTER_WORDS = (
        "pagina", "página", "fecha", "acto", "libro", "registro",
        "sección", "seccion", "antecedente", "delegado", "jefe", "auxiliar"
    )

    for l in footer_lines:
        t = l["text"].strip()
        t_low = t.lower()
        rel_x = l["x"] / img_w if img_w > 0 else 0

        if any(bad in t_low for bad in FORBIDDEN_FOOTER_WORDS):
            continue
        if rel_x < 0.20 or rel_x > 0.78:
            continue

        # Buscar número entero independiente de 2 a 7 dígitos (ej. 14055, 1867, 572)
        m_pie = re.match(r"^(\d{2,7})$", t) or re.search(r"\b(\d{2,7})\b", t)
        if m_pie:
            reg_pie = m_pie.group(1)
            bounding_boxes["pie"] = {
                "text": t,
                "x": l["x"], "y": l["y"], "w": l["w"], "h": l["h"],
                "color": "#3b82f6",  # Azul
                "label": f"Registro Pie: {reg_pie}"
            }
            break

    # -------------------------------------------------------------
    # VALIDACIÓN CRUZADA Y DECISIÓN FINAL
    # -------------------------------------------------------------
    coincide_ambos = False
    reg_final = None
    confianza = 0

    if reg_encabezado and reg_pie:
        if reg_encabezado == reg_pie:
            coincide_ambos = True
            reg_final = reg_encabezado
            confianza = 100
        elif not reg_encabezado_labeled and len(reg_pie) >= 4 and len(reg_pie) > len(reg_encabezado):
            # Si el encabezado fue un fragmento sin etiqueta y el pie tiene un número completo
            reg_final = reg_pie
            confianza = 75
        else:
            # Si difieren, priorizamos el encabezado pero con menor confianza
            reg_final = reg_encabezado
            confianza = 70
    elif reg_encabezado:
        reg_final = reg_encabezado
        confianza = 85
    elif reg_pie:
        reg_final = reg_pie
        confianza = 75
    else:
        reg_final = None
        confianza = 0

    base_result["registro_encabezado"] = reg_encabezado
    base_result["registro_pie"] = reg_pie
    base_result["anio_detectado"] = anio_detectado
    base_result["fecha_registro_texto"] = fecha_reg_texto
    base_result["registro_antecedente"] = reg_antecedente
    base_result["registro_final_detectado"] = reg_final
    base_result["coincide_encabezado_pie"] = coincide_ambos
    base_result["confianza_score"] = confianza
    base_result["bounding_boxes"] = bounding_boxes

    # -------------------------------------------------------------
    # COMPARACIÓN CON EL NOMBRE DEL ARCHIVO ACTUAL
    # -------------------------------------------------------------
    if not parsed_fn["valido"]:
        base_result["estado"] = "NOMBRE_INVALIDO"
        base_result["motivo_discrepancia"] = (
            f"El nombre '{filename}' no cumple con la nomenclatura esperada "
            f"[Delegacion]_[Año]_[Registro].pdf"
        )
    elif reg_final is None:
        base_result["estado"] = "ERROR_LECTURA"
        base_result["motivo_discrepancia"] = (
            "No se pudo detectar ningún número de registro en el encabezado ni en el pie del documento."
        )
    else:
        reg_actual = parsed_fn["registro"]
        anio_actual = parsed_fn["anio"]
        delegacion_actual = parsed_fn["delegacion"]

        # Comparaciones
        reg_coincide = (str(reg_actual) == str(reg_final))
        anio_coincide = (anio_detectado is None) or (int(anio_actual) == int(anio_detectado))
        # Si la delegación no se detectó claramente, no asumimos discrepancia (del_coincide = True)
        del_coincide = True if delegacion_coincide is None else bool(delegacion_coincide)

        # Determinar clave de delegación propuesta y año propuesto
        delegacion_propuesta = del_detectada_clave if (del_detectada_clave and not del_coincide) else delegacion_actual
        anio_propuesto = anio_detectado if anio_detectado else anio_actual
        base_result["nombre_propuesto"] = f"{delegacion_propuesta}_{anio_propuesto}_{reg_final}.pdf"

        # Conteo de discrepancias entre los 3 ejes
        discrepancias_lista = []
        if not reg_coincide:
            discrepancias_lista.append(f"Registro (actual: '{reg_actual}', detectado: '{reg_final}')")
        if not anio_coincide:
            discrepancias_lista.append(f"Año (actual: '{anio_actual}', detectado: '{anio_detectado}')")
        if not del_coincide:
            discrepancias_lista.append(f"Delegación (actual: '{del_archivo_nombre}', detectada: '{del_detectada_clave} - {municipio_detectado}')")

        if not discrepancias_lista:
            base_result["estado"] = "CORRECTO"
            base_result["motivo_discrepancia"] = (
                f"El archivo está correctamente nombrado. Registro: {reg_final}"
                + (f" (validado doblemente en pie y encabezado)" if coincide_ambos else "")
                + (f" | Delegación: {municipio_detectado}" if del_detectada_clave else "")
            )
        elif len(discrepancias_lista) > 1:
            base_result["estado"] = "AMBAS_DISCREPANCIAS"
            motivo = f"Discrepancia múltiple detectada en: {', '.join(discrepancias_lista)}."
            if reg_antecedente and (reg_antecedente == reg_actual or str(reg_antecedente) in str(reg_actual)):
                motivo += f" NOTA: El registro actual parece provenir erróneamente de antecedentes ('{reg_antecedente}')."
            base_result["motivo_discrepancia"] = motivo
        elif not reg_coincide:
            base_result["estado"] = "DISCREPANCIA_REGISTRO"
            motivo = f"El archivo tiene registro '{reg_actual}', pero corresponde al registro '{reg_final}'"
            if coincide_ambos:
                motivo += " (confirmado al 100% por encabezado y pie de página)."
            else:
                motivo += "."
            if reg_antecedente:
                motivo += f" Causa detectada: La herramienta anterior tomó el número de antecedentes '{reg_antecedente}'."
            base_result["motivo_discrepancia"] = motivo
        elif not anio_coincide:
            base_result["estado"] = "DISCREPANCIA_ANIO"
            base_result["motivo_discrepancia"] = (
                f"El registro '{reg_final}' es correcto, pero el año en el nombre es '{anio_actual}' "
                f"mientras que la fecha de registro indica '{anio_detectado}'."
            )
        else:
            base_result["estado"] = "DISCREPANCIA_DELEGACION"
            base_result["motivo_discrepancia"] = (
                f"El archivo tiene clave de delegación '{delegacion_actual}' ({del_archivo_nombre}), "
                f"pero el encabezado indica oficina registral '{del_detectada_clave} - {municipio_detectado}'."
            )

    base_result["tiempo_proceso_ms"] = int((time.time() - start_time) * 1000)
    return base_result
