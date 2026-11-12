import os
import io
import json
import csv
from typing import Optional
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

from config import settings
from database import db_manager, connection
from core.auditor import auditor_instance
from core.document_analyzer import extract_page_image

app = FastAPI(title="Sistema de Auditoría de Registros por OCR", version="1.0.0")

# Montar archivos estáticos y plantillas
current_dir = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(current_dir, "static")
templates_dir = os.path.join(current_dir, "templates")

app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)

# Modelos Pydantic para peticiones
class ScanRequest(BaseModel):
    directory: str
    recursive: bool = False
    limit: Optional[int] = None

class DbInitRequest(BaseModel):
    clean: bool = False

@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    """
    Renderiza la interfaz gráfica principal del dashboard.
    """
    return templates.TemplateResponse("index.html", {
        "request": request,
        "default_scan_path": settings.DEFAULT_SCAN_PATH,
        "db_name": settings.DB_NAME,
        "db_host": settings.DB_HOST,
        "db_port": settings.DB_PORT
    })

@app.get("/api/status")
async def get_system_status():
    """
    Verifica estado de conexión a MySQL y del auditor.
    """
    db_ok, db_msg = connection.test_connection()
    progress = auditor_instance.get_progress()
    return {
        "mysql_connected": db_ok,
        "mysql_message": db_msg,
        "auditor": progress
    }

@app.post("/api/db/init")
async def init_db_endpoint(req: DbInitRequest):
    """
    Inicializa la base de datos limpia y crea las tablas si no existen.
    """
    ok, msg = db_manager.init_database(clean=req.clean)
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"success": True, "message": msg}

@app.post("/api/db/reset")
async def reset_db_endpoint():
    """
    Vacía las tablas de auditoría para un nuevo análisis.
    """
    ok, msg = db_manager.reset_database()
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {"success": True, "message": msg}

@app.post("/api/scan/start")
async def start_scan_endpoint(req: ScanRequest):
    """
    Inicia la auditoría en segundo plano.
    """
    if not os.path.exists(req.directory):
        raise HTTPException(status_code=400, detail=f"La ruta '{req.directory}' no existe o no es accesible.")
    
    ok, msg = auditor_instance.start_audit(
        directory=req.directory,
        recursive=req.recursive,
        limit=req.limit
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@app.post("/api/scan/stop")
async def stop_scan_endpoint():
    """
    Detiene la auditoría en curso.
    """
    auditor_instance.stop()
    return {"success": True, "message": "Orden de detención enviada."}

@app.get("/api/scan/progress")
async def get_scan_progress():
    """
    Obtiene el estado de avance en tiempo real.
    """
    return auditor_instance.get_progress()

@app.get("/api/summary")
async def get_summary():
    """
    Obtiene métricas resumidas desde MySQL.
    """
    try:
        summary = db_manager.get_audit_summary()
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo resumen: {e}")

@app.get("/api/results")
async def get_results(
    estado: Optional[str] = None,
    search: Optional[str] = None,
    lote_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=5, le=200)
):
    """
    Retorna resultados de auditoría paginados y filtrados.
    """
    try:
        filters = {}
        if estado and estado != "TODOS":
            filters["estado"] = estado
        if search:
            filters["search"] = search.strip()
        if lote_id:
            filters["lote_id"] = lote_id

        data = db_manager.get_audit_results(filters=filters, page=page, page_size=page_size)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error consultando registros: {e}")

@app.get("/api/document/{doc_id}")
async def get_document_detail(doc_id: int):
    """
    Obtiene el detalle completo de un documento auditado.
    """
    doc = db_manager.get_document_by_id(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")
    return doc

@app.get("/api/document/{doc_id}/preview")
async def get_document_preview(doc_id: int):
    """
    Genera y sirve una imagen JPEG de la página 1 del PDF con las cajas delimitadoras
    coloreadas (Verde: Encabezado, Azul: Pie, Rojo: Antecedentes).
    """
    doc = db_manager.get_document_by_id(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Documento no encontrado.")

    file_path = doc["ruta_completa"]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"El archivo físico no existe en: {file_path}")

    try:
        img = extract_page_image(file_path, page_number=0, dpi=150)
        img = img.convert("RGB")
        draw = ImageDraw.Draw(img)

        # Parsear bounding boxes
        boxes_raw = doc.get("bounding_boxes_json")
        boxes = json.loads(boxes_raw) if boxes_raw else {}

        # Colores
        # Encabezado: Verde (#10b981)
        # Pie: Azul (#3b82f6)
        # Antecedente: Rojo (#ef4444)
        for key, box in boxes.items():
            x, y, w, h = box["x"], box["y"], box["w"], box["h"]
            color = box.get("color", "#10b981")
            label = box.get("label", key)

            # Dibujar rectángulo grueso
            for offset in range(3):
                draw.rectangle([x - offset, y - offset, x + w + offset, y + h + offset], outline=color)

            # Dibujar etiqueta de fondo
            draw.rectangle([x, max(0, y - 20), x + max(120, len(label) * 8), y], fill=color)
            draw.text((x + 4, max(0, y - 18)), label, fill="#ffffff")

        output = io.BytesIO()
        img.save(output, format="JPEG", quality=85)
        output.seek(0)
        return StreamingResponse(output, media_type="image/jpeg")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando vista previa: {e}")

@app.post("/api/rename/single/{doc_id}")
async def rename_single_endpoint(doc_id: int):
    """
    Ejecuta el renombrado seguro de un archivo físico discrepante.
    """
    ok, msg = db_manager.execute_safe_rename(doc_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@app.get("/api/export/excel")
async def export_excel(estado: Optional[str] = None):
    """
    Genera un archivo Excel (.xlsx) con el reporte completo de la auditoría.
    """
    try:
        filters = {}
        if estado and estado != "TODOS":
            filters["estado"] = estado

        # Obtener todos los registros coincidentes
        data = db_manager.get_audit_results(filters=filters, page=1, page_size=100000)
        items = data["items"]

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Auditoría OCR"

        # Encabezados
        headers = [
            "ID", "Nombre Actual", "Delegación", "Año Actual", "Reg. Actual",
            "Reg. Encabezado", "Reg. Pie", "Coinciden Pie/Encabezado",
            "Reg. Antecedente (Trampa)", "Reg. Final Detectado", "Año Detectado",
            "Estado Auditoría", "Nombre Propuesto", "Confianza %", "Motivo / Diagnóstico",
            "Fecha Auditoría", "Ruta Completa"
        ]
        ws.append(headers)

        header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # Filas de datos
        for doc in items:
            row = [
                doc["id"],
                doc["nombre_archivo"],
                doc["delegacion_actual"],
                doc["anio_actual"],
                doc["registro_actual"],
                doc["registro_encabezado"],
                doc["registro_pie"],
                "SÍ" if doc["coincide_encabezado_pie"] else "NO",
                doc["registro_antecedente"],
                doc["registro_final_detectado"],
                doc["anio_detectado"],
                doc["estado"],
                doc["nombre_propuesto"],
                doc["confianza_score"],
                doc["motivo_discrepancia"],
                str(doc["fecha_auditoria"]),
                doc["ruta_completa"]
            ]
            ws.append(row)

        # Ajuste de ancho de columnas
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 60)

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=reporte_auditoria_ocr.xlsx"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exportando Excel: {e}")

@app.get("/api/export/csv")
async def export_csv(estado: Optional[str] = None):
    """
    Genera un archivo CSV con el reporte completo de la auditoría.
    """
    try:
        filters = {}
        if estado and estado != "TODOS":
            filters["estado"] = estado

        data = db_manager.get_audit_results(filters=filters, page=1, page_size=100000)
        items = data["items"]

        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

        writer.writerow([
            "ID", "Nombre Actual", "Delegación", "Año Actual", "Reg. Actual",
            "Reg. Encabezado", "Reg. Pie", "Coinciden Pie/Encabezado",
            "Reg. Antecedente", "Reg. Final Detectado", "Año Detectado",
            "Estado", "Nombre Propuesto", "Confianza", "Motivo", "Ruta Completa"
        ])

        for doc in items:
            writer.writerow([
                doc["id"],
                doc["nombre_archivo"],
                doc["delegacion_actual"],
                doc["anio_actual"],
                doc["registro_actual"],
                doc["registro_encabezado"],
                doc["registro_pie"],
                1 if doc["coincide_encabezado_pie"] else 0,
                doc["registro_antecedente"],
                doc["registro_final_detectado"],
                doc["anio_detectado"],
                doc["estado"],
                doc["nombre_propuesto"],
                doc["confianza_score"],
                doc["motivo_discrepancia"],
                doc["ruta_completa"]
            ])

        output.seek(0)
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=reporte_auditoria_ocr.csv"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error exportando CSV: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.app:app", host=settings.WEB_HOST, port=settings.WEB_PORT, log_level="info")
