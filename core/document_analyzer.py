import os
import re
import time
import threading
import pymupdf  # PyMuPDF
from PIL import Image
from config import settings
from core.ocr_engine import recognize_image

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
    match = re.search(r"^([A-Za-z0-9]+)_(\d{4})_(\d+)(?:\.pdf)?$", clean_name, re.IGNORECASE)
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

    base_result = {
        "lote_id": lote_id,
        "nombre_archivo": filename,
        "ruta_completa": file_path,
        "tamano_bytes": file_size,
        "delegacion_actual": parsed_fn["delegacion"],
        "anio_actual": parsed_fn["anio"],
        "registro_actual": parsed_fn["registro"],
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
    header_lines = []
    body_lines = []
    footer_lines = []

    for line in lines:
        rel_y = line["rel_y"]
        if rel_y < 0.32:
            header_lines.append(line)
        elif rel_y > 0.85:
            footer_lines.append(line)
        else:
            body_lines.append(line)

    bounding_boxes = {}

    # -------------------------------------------------------------
    # ZONA 1: Recuadro Superior (Encabezado)
    # -------------------------------------------------------------
    reg_encabezado = None
    fecha_reg_texto = None
    anio_detectado = None

    # a) Búsqueda directa de "Registro: X" o número de registro en el encabezado
    for l in header_lines:
        t = l["text"].strip()
        
        # Caso A: Registro: 14055
        m_reg = re.search(r"Registro:\s*(\d+)", t, re.IGNORECASE)
        if m_reg:
            reg_encabezado = m_reg.group(1)
            bounding_boxes["encabezado"] = {
                "text": t,
                "x": l["x"], "y": l["y"], "w": l["w"], "h": l["h"],
                "color": "#10b981", # Verde
                "label": f"Registro Encabezado: {reg_encabezado}"
            }
            break

        # Caso B: Número aislado en el subrecuadro superior de registro (y < 20% y x < 400)
        if re.match(r"^\d{4,7}$", t) and l["rel_y"] > 0.10 and l["rel_y"] < 0.22:
            if not reg_encabezado:
                reg_encabezado = t
                bounding_boxes["encabezado"] = {
                    "text": t,
                    "x": l["x"], "y": l["y"], "w": l["w"], "h": l["h"],
                    "color": "#10b981",
                    "label": f"Registro Encabezado: {reg_encabezado}"
                }

    # b) Extracción de Fecha de Registro y Año
    for l in header_lines:
        t = l["text"].strip()
        # Busca patrones de fecha como "01 DE SEPTIEMBRE DEL 2011" o "Fecha de Registro: 01 DE SEPTIEMBRE DEL 2011"
        m_date = re.search(r"(\d{1,2})\s+(?:DE\s+)?([A-Z]+)\s+(?:DEL?\s+)?(\d{4})", t, re.IGNORECASE)
        if m_date and ("fecha" in t.lower() or "registro" in t.lower() or "septiembre" in t.lower()):
            fecha_reg_texto = m_date.group(0)
            anio_candidate = int(m_date.group(3))
            if 1900 <= anio_candidate <= 2099:
                anio_detectado = anio_candidate
                bounding_boxes["fecha_registro"] = {
                    "text": t,
                    "x": l["x"], "y": l["y"], "w": l["w"], "h": l["h"],
                    "color": "#6366f1", # Índigo
                    "label": f"Fecha Registro: {fecha_reg_texto}"
                }
                break

    # Si aún no se detectó el año, buscar cualquier año de 4 dígitos en el encabezado
    if not anio_detectado:
        for l in header_lines:
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
    # ZONA 3: Pie de Página
    # -------------------------------------------------------------
    reg_pie = None

    for l in footer_lines:
        t = l["text"].strip()
        # Ignorar líneas de conteo de página como "Pagina 1 de 2"
        if re.search(r"p[aá]gina\s+\d+", t, re.IGNORECASE):
            continue

        # Buscar número entero independiente de 3 a 7 dígitos (ej. 14055)
        m_pie = re.search(r"\b(\d{3,7})\b", t)
        if m_pie:
            reg_pie = m_pie.group(1)
            bounding_boxes["pie"] = {
                "text": t,
                "x": l["x"], "y": l["y"], "w": l["w"], "h": l["h"],
                "color": "#3b82f6", # Azul
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

        # Determinar año propuesto
        anio_propuesto = anio_detectado if anio_detectado else anio_actual
        base_result["nombre_propuesto"] = f"{delegacion_actual}_{anio_propuesto}_{reg_final}.pdf"

        if reg_coincide and anio_coincide:
            base_result["estado"] = "CORRECTO"
            base_result["motivo_discrepancia"] = (
                f"El archivo está correctamente nombrado. Registro: {reg_final}"
                + (f" (validado doblemente en pie y encabezado)" if coincide_ambos else "")
            )
        elif not reg_coincide and not anio_coincide:
            base_result["estado"] = "AMBAS_DISCREPANCIAS"
            motivo = (
                f"Discrepancia doble: Tiene asignado registro '{reg_actual}' y año '{anio_actual}', "
                f"pero el OCR detectó registro '{reg_final}' y año '{anio_detectado}'."
            )
            if reg_antecedente and (reg_antecedente == reg_actual or str(reg_antecedente) in str(reg_actual)):
                motivo += f" NOTA: El registro actual parece provenir erróneamente de antecedentes ('{reg_antecedente}')."
            base_result["motivo_discrepancia"] = motivo
        elif not reg_coincide:
            base_result["estado"] = "DISCREPANCIA_REGISTRO"
            motivo = (
                f"El archivo tiene registro '{reg_actual}', pero corresponde al registro '{reg_final}'"
            )
            if coincide_ambos:
                motivo += " (confirmado al 100% por encabezado y pie de página)."
            else:
                motivo += "."
                
            if reg_antecedente:
                motivo += f" Causa detectada: La herramienta anterior tomó el número de antecedentes '{reg_antecedente}'."
            base_result["motivo_discrepancia"] = motivo
        else:
            base_result["estado"] = "DISCREPANCIA_ANIO"
            base_result["motivo_discrepancia"] = (
                f"El registro '{reg_final}' es correcto, pero el año en el nombre es '{anio_actual}' "
                f"mientras que la fecha de registro indica '{anio_detectado}'."
            )

    base_result["tiempo_proceso_ms"] = int((time.time() - start_time) * 1000)
    return base_result
