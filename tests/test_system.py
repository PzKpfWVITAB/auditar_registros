import os
import sys
import shutil
import pymupdf
from pathlib import Path

# Add root directory to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from core.document_analyzer import analyze_document
from database import db_manager, connection
from fastapi.testclient import TestClient
from web.app import app

def run_all_tests():
    print("=" * 65)
    print("EJECUTANDO SUITE DE PRUEBAS DEL SISTEMA DE AUDITORÍA OCR")
    print("=" * 65)

    # -------------------------------------------------------------
    # 1. Prueba de Conexión a Base de Datos y Creación Limpia
    # -------------------------------------------------------------
    print("\n[TEST 1] Conexión e Inicialización de Base de Datos MySQL...")
    db_ok, msg = connection.test_connection()
    assert db_ok, f"Falló conexión a MySQL: {msg}"
    print(f" -> Conexión exitosa: {msg}")

    init_ok, init_msg = db_manager.init_database(clean=True)
    assert init_ok, f"Falló inicialización de base de datos limpia: {init_msg}"
    print(f" -> Base de datos inicializada limpia: {init_msg}")

    # -------------------------------------------------------------
    # 2. Prueba de Análisis OCR y Validación Cruzada con Muestra Real
    # -------------------------------------------------------------
    print("\n[TEST 2] Análisis OCR y Anti-Trampa con la Muestra '01_2011_233.pdf'...")
    sample_img = r"C:\Users\yasse\.gemini\antigravity\brain\219f8f35-7cc8-44ae-9bac-0732c65e8ef5\.user_uploaded\media_1794508175031_785fc932.jpg"
    test_pdf = os.path.join(root_dir, "tests", "01_2011_233.pdf")

    # Crear PDF de prueba a partir de la muestra del usuario
    doc = pymupdf.open()
    img_doc = pymupdf.open(sample_img)
    pdf_bytes = img_doc.convert_to_pdf()
    img_pdf = pymupdf.open("pdf", pdf_bytes)
    page = doc.new_page(width=img_pdf[0].rect.width, height=img_pdf[0].rect.height)
    page.show_pdf_page(page.rect, img_pdf, 0)
    doc.save(test_pdf)
    doc.close()

    res = analyze_document(test_pdf)
    
    print(f" -> Archivo analizado     : {res['nombre_archivo']}")
    print(f" -> Registro actual       : {res['registro_actual']}")
    print(f" -> Registro encabezado   : {res['registro_encabezado']}")
    print(f" -> Registro pie          : {res['registro_pie']}")
    print(f" -> Registro antecedente  : {res['registro_antecedente']}")
    print(f" -> Coincide encab./pie   : {res['coincide_encabezado_pie']}")
    print(f" -> Año detectado         : {res['anio_detectado']}")
    print(f" -> Estado detectado      : {res['estado']}")
    print(f" -> Nombre propuesto      : {res['nombre_propuesto']}")
    print(f" -> Confianza score       : {res['confianza_score']}%")
    print(f" -> Diagnóstico           : {res['motivo_discrepancia']}")

    # Aserciones estrictas del caso del usuario
    assert res["registro_encabezado"] == "14055", f"Esperado 14055 en encabezado, obtenido {res['registro_encabezado']}"
    assert res["registro_pie"] == "14055", f"Esperado 14055 en pie, obtenido {res['registro_pie']}"
    assert res["registro_antecedente"] == "283", f"Esperado 283 en antecedentes, obtenido {res['registro_antecedente']}"
    assert res["coincide_encabezado_pie"] is True, "Debe coincidir encabezado y pie"
    assert res["anio_detectado"] == 2011, f"Esperado año 2011, obtenido {res['anio_detectado']}"
    assert res["estado"] == "DISCREPANCIA_REGISTRO", f"Estado esperado DISCREPANCIA_REGISTRO, obtenido {res['estado']}"
    assert res["nombre_propuesto"] == "01_2011_14055.pdf", f"Esperado 01_2011_14055.pdf, obtenido {res['nombre_propuesto']}"
    assert res["confianza_score"] == 100, f"Esperado 100% de confianza, obtenido {res['confianza_score']}"

    print("[OK] Test 2 superado con 100% de precisión.")

    # -------------------------------------------------------------
    # 3. Prueba de Inserción y Consulta en Base de Datos MySQL
    # -------------------------------------------------------------
    print("\n[TEST 3] Inserción de resultados en MySQL y cálculo de KPIs...")
    inserted_id = db_manager.save_audit_result(res)
    assert inserted_id > 0, "El ID insertado debe ser mayor a 0"
    print(f" -> Documento insertado en MySQL con ID: {inserted_id}")

    summary = db_manager.get_audit_summary()
    print(f" -> Resumen de KPIs en DB: {summary}")
    assert summary["total"] == 1, "Total debe ser 1"
    assert summary["discrepancias"] == 1, "Discrepancias debe ser 1"
    assert summary["certeza_doble_marca"] == 1, "Doble marca debe ser 1"

    data_page = db_manager.get_audit_results(filters={"estado": "DISCREPANCIAS"}, page=1, page_size=10)
    assert len(data_page["items"]) == 1, "Debe retornar 1 registro en filtro de discrepancias"
    print("[OK] Test 3 superado.")

    # -------------------------------------------------------------
    # 4. Prueba de la API Web y Generación de Vista Previa con Bounding Boxes
    # -------------------------------------------------------------
    print("\n[TEST 4] Pruebas de API FastAPI y Vista Previa Visual...")
    client = TestClient(app)

    # Status
    resp_status = client.get("/api/status")
    assert resp_status.status_code == 200
    assert resp_status.json()["mysql_connected"] is True
    print(" -> GET /api/status: OK")

    # Summary
    resp_summary = client.get("/api/summary")
    assert resp_summary.status_code == 200
    assert resp_summary.json()["total"] == 1
    print(" -> GET /api/summary: OK")

    # Results
    resp_results = client.get("/api/results")
    assert resp_results.status_code == 200
    assert len(resp_results.json()["items"]) == 1
    print(" -> GET /api/results: OK")

    # Preview con Bounding Boxes (imagen JPEG)
    resp_preview = client.get(f"/api/document/{inserted_id}/preview")
    assert resp_preview.status_code == 200
    assert resp_preview.headers["content-type"] == "image/jpeg"
    assert len(resp_preview.content) > 10000, "La imagen generada debe tener contenido binario"
    print(f" -> GET /api/document/{inserted_id}/preview: OK ({len(resp_preview.content)} bytes de imagen)")

    # Limpiar archivo temporal
    if os.path.exists(test_pdf):
        os.remove(test_pdf)

    print("\n" + "=" * 65)
    print("TODAS LAS PRUEBAS AUTOMATIZADAS PASARON EXITOSAMENTE (100% OK)")
    print("=" * 65)

if __name__ == "__main__":
    run_all_tests()
