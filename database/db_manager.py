import gzip
import json
from pathlib import Path
from database.connection import get_raw_connection, test_connection
from config import settings

DEFAULT_REGISTROS_FILE = Path(__file__).resolve().parent / "registros_existentes.txt.gz"
DISCREPANCY_STATES = ("DISCREPANCIA_REGISTRO", "DISCREPANCIA_ANIO", "AMBAS_DISCREPANCIAS")


def _ensure_colision_column(cursor):
    """Asegura la existencia de la columna e índice colision_bd en bases existentes."""
    cursor.execute("""
        SELECT COUNT(*) AS cnt
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s
          AND TABLE_NAME = 'documentos_auditados'
          AND COLUMN_NAME = 'colision_bd';
    """, (settings.DB_NAME,))
    row = cursor.fetchone() or {}
    if not row.get("cnt"):
        cursor.execute(
            "ALTER TABLE `documentos_auditados` "
            "ADD COLUMN `colision_bd` TINYINT(1) DEFAULT 0 AFTER `tiempo_proceso_ms`, "
            "ADD INDEX `idx_colision_bd` (`colision_bd`);"
        )


def init_database(clean=False):
    """
    Crea la base de datos limpia y todas las tablas necesarias si no existen.
    Si clean=True, elimina la base de datos previa y la recrea desde cero.
    """
    conn = get_raw_connection(include_database=False)
    try:
        with conn.cursor() as cursor:
            if clean:
                cursor.execute(f"DROP DATABASE IF EXISTS `{settings.DB_NAME}`;")
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.DB_NAME}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            )
            cursor.execute(f"USE `{settings.DB_NAME}`;")
            
            # Leer schema.sql
            schema_path = Path(__file__).resolve().parent / "schema.sql"
            with open(schema_path, "r", encoding="utf-8") as f:
                sql_content = f.read()

            # Limpiar comentarios y ejecutar sentencias individuales
            commands = sql_content.split(";")
            for cmd in commands:
                # Quitar líneas de comentarios SQL (-- ...)
                lines = [line for line in cmd.splitlines() if not line.strip().startswith("--")]
                clean_cmd = "\n".join(lines).strip()
                if clean_cmd:
                    cursor.execute(clean_cmd)

            if not clean:
                _ensure_colision_column(cursor)
        return True, "Base de datos y tablas inicializadas correctamente."
    except Exception as e:
        return False, f"Error inicializando la base de datos: {e}"
    finally:
        conn.close()


def init_registros_existentes_table():
    """
    Crea específicamente la estructura de la tabla catálogo `registros_existentes`
    (y la columna `colision_bd` en `documentos_auditados` si la tabla ya existe).
    """
    conn = get_raw_connection(include_database=False)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.DB_NAME}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            )
            cursor.execute(f"USE `{settings.DB_NAME}`;")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS `registros_existentes` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `nombre_pdf` VARCHAR(255) NOT NULL,
                    `fecha_carga` DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE KEY `uk_nombre_pdf` (`nombre_pdf`)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
            """)
            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'documentos_auditados';
            """, (settings.DB_NAME,))
            if (cursor.fetchone() or {}).get("cnt"):
                _ensure_colision_column(cursor)
        return True, "Estructura de tabla 'registros_existentes' lista correctamente."
    except Exception as e:
        return False, f"Error creando estructura de 'registros_existentes': {e}"
    finally:
        conn.close()


def get_registros_existentes_count():
    """Retorna la cantidad de PDFs cargados en el catálogo `registros_existentes`."""
    try:
        conn = get_raw_connection(include_database=True)
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS total FROM `registros_existentes`;")
                row = cursor.fetchone() or {}
                return int(row.get("total") or 0)
        finally:
            conn.close()
    except Exception:
        return 0


def recheck_collisions():
    """
    Recalcula `colision_bd` en toda la tabla `documentos_auditados`
    comparando `nombre_propuesto` contra `registros_existentes`.
    Retorna el total de documentos marcados con colisión.
    """
    conn = get_raw_connection(include_database=True)
    try:
        with conn.cursor() as cursor:
            _ensure_colision_column(cursor)
            cursor.execute("""
                UPDATE `documentos_auditados` d
                LEFT JOIN `registros_existentes` r
                       ON r.`nombre_pdf` = d.`nombre_propuesto`
                SET d.`colision_bd` = CASE
                    WHEN d.`estado` IN ('DISCREPANCIA_REGISTRO', 'DISCREPANCIA_ANIO', 'AMBAS_DISCREPANCIAS')
                         AND d.`nombre_propuesto` IS NOT NULL
                         AND LOWER(d.`nombre_propuesto`) <> LOWER(d.`nombre_archivo`)
                         AND r.`id` IS NOT NULL
                    THEN 1
                    ELSE 0
                END;
            """)
            cursor.execute("SELECT COUNT(*) AS total FROM `documentos_auditados` WHERE `colision_bd` = 1;")
            return int((cursor.fetchone() or {}).get("total") or 0)
    finally:
        conn.close()


def import_registros_existentes(source_path=None, progress_callback=None, replace=True):
    """
    Alimenta la tabla `registros_existentes` desde un archivo `.txt.gz`, `.txt` o `.csv`
    (incluyendo el formato `Total registros.txt` con columna `NombrePDF\tPaginas`).
    """
    src = Path(source_path) if source_path else DEFAULT_REGISTROS_FILE
    if not src.exists():
        return False, {"message": f"No se encontró el archivo fuente: {src}"}

    ok_tbl, msg_tbl = init_registros_existentes_table()
    if not ok_tbl:
        return False, {"message": msg_tbl}

    opener = gzip.open if src.suffix.lower() == ".gz" else open
    unique_names = []
    seen = set()

    with opener(src, "rt", encoding="utf-8", errors="replace") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            col0 = raw.split("\t")[0].split(",")[0].strip().strip('"').strip("'")
            if not col0 or col0.lower() == "nombrepdf":
                continue
            key = col0.lower()
            if key not in seen:
                seen.add(key)
                unique_names.append((col0,))

    total = len(unique_names)
    if total == 0:
        return False, {"message": "El archivo no contiene nombres de PDF válidos."}

    conn = get_raw_connection(include_database=True)
    try:
        conn.autocommit(False)
        with conn.cursor() as cursor:
            if replace:
                cursor.execute("TRUNCATE TABLE `registros_existentes`;")

            batch_size = 20000
            for i in range(0, total, batch_size):
                batch = unique_names[i:i + batch_size]
                cursor.executemany(
                    "INSERT IGNORE INTO `registros_existentes` (`nombre_pdf`) VALUES (%s);",
                    batch,
                )
                conn.commit()
                if progress_callback:
                    progress_callback(min(i + len(batch), total), total)
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, {"message": f"Error alimentando 'registros_existentes': {e}"}
    finally:
        try:
            conn.autocommit(True)
        except Exception:
            pass
        conn.close()

    collisions = recheck_collisions()
    loaded = get_registros_existentes_count()
    return True, {
        "total_file": total,
        "loaded": loaded,
        "collisions": collisions,
        "message": (
            f"Catálogo alimentado correctamente: {loaded:,} nombres de PDF en 'registros_existentes'.\n"
            f"Choques detectados en auditorías actuales: {collisions:,}."
        ),
    }


def _check_collision_for_doc(cursor, doc) -> int:
    """Verifica si el nombre propuesto de una discrepancia ya existe en `registros_existentes`."""
    estado = doc.get("estado") or ""
    propuesto = (doc.get("nombre_propuesto") or "").strip()
    actual = (doc.get("nombre_archivo") or "").strip()
    if estado not in DISCREPANCY_STATES or not propuesto or propuesto.lower() == actual.lower():
        return 0
    try:
        cursor.execute(
            "SELECT 1 FROM `registros_existentes` WHERE `nombre_pdf` = %s LIMIT 1;",
            (propuesto,),
        )
        return 1 if cursor.fetchone() else 0
    except Exception:
        return 0


def reset_database():
    """
    Vacía las tablas de auditoría para comenzar un lote desde cero sin borrar la estructura
    ni el catálogo `registros_existentes`.
    """
    conn = get_raw_connection(include_database=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cursor.execute("TRUNCATE TABLE `historial_renombrado`;")
            cursor.execute("TRUNCATE TABLE `documentos_auditados`;")
            cursor.execute("TRUNCATE TABLE `lotes_auditoria`;")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
        return True, "Tablas de auditoría limpiadas exitosamente (catálogo de registros conservado)."
    except Exception as e:
        return False, f"Error limpiando tablas: {e}"
    finally:
        conn.close()

def create_lote(directorio_escaneado):
    conn = get_raw_connection(include_database=True)
    try:
        with conn.cursor() as cursor:
            sql = "INSERT INTO `lotes_auditoria` (`directorio_escaneado`) VALUES (%s);"
            cursor.execute(sql, (directorio_escaneado,))
            return cursor.lastrowid
    finally:
        conn.close()

def update_lote_summary(lote_id, total, correctos, discrepancias, errores, estado="COMPLETADO"):
    conn = get_raw_connection(include_database=True)
    try:
        with conn.cursor() as cursor:
            sql = """
                UPDATE `lotes_auditoria` 
                SET `total_archivos` = %s,
                    `total_correctos` = %s,
                    `total_discrepancias` = %s,
                    `total_errores` = %s,
                    `fecha_fin` = NOW(),
                    `estado` = %s
                WHERE `id` = %s;
            """
            cursor.execute(sql, (total, correctos, discrepancias, errores, estado, lote_id))
    finally:
        conn.close()

def save_audit_result(doc):
    """
    Guarda o actualiza el resultado de la auditoría de un documento,
    verificando si su nombre propuesto choca con el catálogo `registros_existentes`.
    """
    conn = get_raw_connection(include_database=True)
    try:
        with conn.cursor() as cursor:
            colision = _check_collision_for_doc(cursor, doc)
            motivo = doc.get("motivo_discrepancia") or ""
            if colision and "CHOCA EN BD" not in motivo:
                motivo = (motivo + " " if motivo else "") + f"[CHOCA EN BD: '{doc.get('nombre_propuesto')}' ya existe en registros_existentes]"

            sql = """
                INSERT INTO `documentos_auditados` (
                    `lote_id`, `nombre_archivo`, `ruta_completa`, `tamano_bytes`,
                    `delegacion_actual`, `anio_actual`, `registro_actual`,
                    `registro_encabezado`, `registro_pie`, `anio_detectado`,
                    `fecha_registro_texto`, `registro_antecedente`,
                    `registro_final_detectado`, `coincide_encabezado_pie`,
                    `estado`, `nombre_propuesto`, `confianza_score`,
                    `motivo_discrepancia`, `bounding_boxes_json`, `tiempo_proceso_ms`,
                    `colision_bd`
                ) VALUES (
                    %(lote_id)s, %(nombre_archivo)s, %(ruta_completa)s, %(tamano_bytes)s,
                    %(delegacion_actual)s, %(anio_actual)s, %(registro_actual)s,
                    %(registro_encabezado)s, %(registro_pie)s, %(anio_detectado)s,
                    %(fecha_registro_texto)s, %(registro_antecedente)s,
                    %(registro_final_detectado)s, %(coincide_encabezado_pie)s,
                    %(estado)s, %(nombre_propuesto)s, %(confianza_score)s,
                    %(motivo_discrepancia)s, %(bounding_boxes_json)s, %(tiempo_proceso_ms)s,
                    %(colision_bd)s
                );
            """
            cursor.execute(sql, {
                "lote_id": doc.get("lote_id"),
                "nombre_archivo": doc.get("nombre_archivo"),
                "ruta_completa": doc.get("ruta_completa"),
                "tamano_bytes": doc.get("tamano_bytes", 0),
                "delegacion_actual": doc.get("delegacion_actual"),
                "anio_actual": doc.get("anio_actual"),
                "registro_actual": doc.get("registro_actual"),
                "registro_encabezado": doc.get("registro_encabezado"),
                "registro_pie": doc.get("registro_pie"),
                "anio_detectado": doc.get("anio_detectado"),
                "fecha_registro_texto": doc.get("fecha_registro_texto"),
                "registro_antecedente": doc.get("registro_antecedente"),
                "registro_final_detectado": doc.get("registro_final_detectado"),
                "coincide_encabezado_pie": 1 if doc.get("coincide_encabezado_pie") else 0,
                "estado": doc.get("estado"),
                "nombre_propuesto": doc.get("nombre_propuesto"),
                "confianza_score": doc.get("confianza_score", 0),
                "motivo_discrepancia": motivo or None,
                "bounding_boxes_json": json.dumps(doc.get("bounding_boxes", {}), ensure_ascii=False),
                "tiempo_proceso_ms": doc.get("tiempo_proceso_ms", 0),
                "colision_bd": colision,
            })
            return cursor.lastrowid
    finally:
        conn.close()

def update_audit_result(doc_id, doc):
    """
    Actualiza un registro existente en documentos_auditados (usado al reintentar errores).
    """
    conn = get_raw_connection(include_database=True)
    try:
        with conn.cursor() as cursor:
            colision = _check_collision_for_doc(cursor, doc)
            motivo = doc.get("motivo_discrepancia") or ""
            if colision and "CHOCA EN BD" not in motivo:
                motivo = (motivo + " " if motivo else "") + f"[CHOCA EN BD: '{doc.get('nombre_propuesto')}' ya existe en registros_existentes]"

            sql = """
                UPDATE `documentos_auditados`
                SET `delegacion_actual` = %(delegacion_actual)s,
                    `anio_actual` = %(anio_actual)s,
                    `registro_actual` = %(registro_actual)s,
                    `registro_encabezado` = %(registro_encabezado)s,
                    `registro_pie` = %(registro_pie)s,
                    `anio_detectado` = %(anio_detectado)s,
                    `fecha_registro_texto` = %(fecha_registro_texto)s,
                    `registro_antecedente` = %(registro_antecedente)s,
                    `registro_final_detectado` = %(registro_final_detectado)s,
                    `coincide_encabezado_pie` = %(coincide_encabezado_pie)s,
                    `estado` = %(estado)s,
                    `nombre_propuesto` = %(nombre_propuesto)s,
                    `confianza_score` = %(confianza_score)s,
                    `motivo_discrepancia` = %(motivo_discrepancia)s,
                    `bounding_boxes_json` = %(bounding_boxes_json)s,
                    `tiempo_proceso_ms` = %(tiempo_proceso_ms)s,
                    `colision_bd` = %(colision_bd)s,
                    `fecha_auditoria` = NOW()
                WHERE `id` = %(id)s;
            """
            cursor.execute(sql, {
                "id": doc_id,
                "delegacion_actual": doc.get("delegacion_actual"),
                "anio_actual": doc.get("anio_actual"),
                "registro_actual": doc.get("registro_actual"),
                "registro_encabezado": doc.get("registro_encabezado"),
                "registro_pie": doc.get("registro_pie"),
                "anio_detectado": doc.get("anio_detectado"),
                "fecha_registro_texto": doc.get("fecha_registro_texto"),
                "registro_antecedente": doc.get("registro_antecedente"),
                "registro_final_detectado": doc.get("registro_final_detectado"),
                "coincide_encabezado_pie": 1 if doc.get("coincide_encabezado_pie") else 0,
                "estado": doc.get("estado"),
                "nombre_propuesto": doc.get("nombre_propuesto"),
                "confianza_score": doc.get("confianza_score", 0),
                "motivo_discrepancia": motivo or None,
                "bounding_boxes_json": json.dumps(doc.get("bounding_boxes", {}), ensure_ascii=False),
                "tiempo_proceso_ms": doc.get("tiempo_proceso_ms", 0),
                "colision_bd": colision,
            })
            return cursor.rowcount > 0
    finally:
        conn.close()

def get_error_documents():
    """
    Retorna todos los documentos marcados con estado de error para poder reintentarlos.
    """
    conn = get_raw_connection(include_database=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id, nombre_archivo, ruta_completa, lote_id
                FROM `documentos_auditados`
                WHERE estado IN ('ERROR_LECTURA', 'NOMBRE_INVALIDO')
                ORDER BY id ASC;
            """)
            return cursor.fetchall()
    finally:
        conn.close()

def get_audit_summary(lote_id=None):
    """
    Retorna las métricas cuantitativas clave de la auditoría.
    """
    conn = get_raw_connection(include_database=True)
    try:
        with conn.cursor() as cursor:
            where_clause = "WHERE `lote_id` = %s" if lote_id else ""
            params = (lote_id,) if lote_id else ()
            
            sql = f"""
                SELECT 
                    COUNT(*) AS total,
                    SUM(CASE WHEN estado = 'CORRECTO' THEN 1 ELSE 0 END) AS correctos,
                    SUM(CASE WHEN estado IN ('DISCREPANCIA_REGISTRO', 'DISCREPANCIA_ANIO', 'AMBAS_DISCREPANCIAS') THEN 1 ELSE 0 END) AS discrepancias,
                    SUM(CASE WHEN estado IN ('ERROR_LECTURA', 'NOMBRE_INVALIDO') THEN 1 ELSE 0 END) AS errores,
                    SUM(CASE WHEN coincide_encabezado_pie = 1 THEN 1 ELSE 0 END) AS certeza_doble_marca,
                    SUM(CASE WHEN colision_bd = 1 THEN 1 ELSE 0 END) AS colisiones
                FROM `documentos_auditados` {where_clause};
            """
            cursor.execute(sql, params)
            res = cursor.fetchone() or {}
            
            total = res.get("total", 0) or 0
            correctos = res.get("correctos", 0) or 0
            discrepancias = res.get("discrepancias", 0) or 0
            errores = res.get("errores", 0) or 0
            colisiones = res.get("colisiones", 0) or 0
            tasa_error = round((discrepancias / total * 100), 2) if total > 0 else 0.0

            return {
                "total": total,
                "correctos": correctos,
                "discrepancias": discrepancias,
                "errores": errores,
                "colisiones": colisiones,
                "certeza_doble_marca": res.get("certeza_doble_marca", 0) or 0,
                "tasa_discrepancia_pct": tasa_error
            }
    finally:
        conn.close()

def get_audit_results(filters=None, page=1, page_size=50):
    """
    Retorna lista paginada y filtrada de documentos auditados.
    """
    conn = get_raw_connection(include_database=True)
    try:
        with conn.cursor() as cursor:
            filters = filters or {}
            conditions = []
            params = []

            if filters.get("estado"):
                if filters["estado"] == "DISCREPANCIAS":
                    conditions.append("estado IN ('DISCREPANCIA_REGISTRO', 'DISCREPANCIA_ANIO', 'AMBAS_DISCREPANCIAS')")
                elif filters["estado"] == "COLISION_BD":
                    conditions.append("colision_bd = 1")
                else:
                    conditions.append("estado = %s")
                    params.append(filters["estado"])

            if filters.get("search"):
                term = f"%{filters['search']}%"
                conditions.append(
                    "(nombre_archivo LIKE %s OR nombre_propuesto LIKE %s OR registro_actual LIKE %s OR registro_final_detectado LIKE %s)"
                )
                params.extend([term, term, term, term])

            if filters.get("lote_id"):
                conditions.append("lote_id = %s")
                params.append(filters["lote_id"])

            where_str = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            # Conteo total
            count_sql = f"SELECT COUNT(*) AS total FROM `documentos_auditados` {where_str};"
            cursor.execute(count_sql, tuple(params))
            total_items = cursor.fetchone()["total"]

            # Datos paginados
            offset = (page - 1) * page_size
            data_sql = f"""
                SELECT id, lote_id, nombre_archivo, ruta_completa,
                       delegacion_actual, anio_actual, registro_actual,
                       registro_encabezado, registro_pie, anio_detectado,
                       registro_antecedente, registro_final_detectado,
                       coincide_encabezado_pie, estado, nombre_propuesto,
                       confianza_score, motivo_discrepancia, tiempo_proceso_ms,
                       colision_bd, estado_renombrado, fecha_auditoria
                FROM `documentos_auditados`
                {where_str}
                ORDER BY id DESC
                LIMIT %s OFFSET %s;
            """
            cursor.execute(data_sql, tuple(params) + (page_size, offset))
            items = cursor.fetchall()

            return {
                "items": items,
                "total": total_items,
                "page": page,
                "page_size": page_size,
                "total_pages": (total_items + page_size - 1) // page_size if total_items > 0 else 1
            }
    finally:
        conn.close()

def get_document_by_id(doc_id):
    conn = get_raw_connection(include_database=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM `documentos_auditados` WHERE id = %s;", (doc_id,))
            return cursor.fetchone()
    finally:
        conn.close()

def execute_safe_rename(doc_id):
    """
    Aplica el renombrado seguro de un archivo físico con registro de historial.
    """
    import os
    conn = get_raw_connection(include_database=True)
    try:
        doc = get_document_by_id(doc_id)
        if not doc or not doc.get("nombre_propuesto"):
            return False, "Documento o nombre propuesto no válido."
        
        old_path = doc["ruta_completa"]
        folder = os.path.dirname(old_path)
        new_path = os.path.join(folder, doc["nombre_propuesto"])

        if not os.path.exists(old_path):
            return False, f"El archivo original ya no existe en la ruta: {old_path}"
        
        if os.path.exists(new_path):
            return False, f"Ya existe un archivo con el nombre propuesto: {new_path}"

        # Realizar renombrado
        os.rename(old_path, new_path)

        with conn.cursor() as cursor:
            # Registrar historial
            cursor.execute("""
                INSERT INTO `historial_renombrado` 
                (`documento_id`, `nombre_original`, `nombre_nuevo`, `ruta_directorio`)
                VALUES (%s, %s, %s, %s);
            """, (doc_id, doc["nombre_archivo"], doc["nombre_propuesto"], folder))
            
            # Actualizar documento
            cursor.execute("""
                UPDATE `documentos_auditados` 
                SET `nombre_archivo` = %s,
                    `ruta_completa` = %s,
                    `registro_actual` = `registro_final_detectado`,
                    `estado` = 'CORRECTO',
                    `estado_renombrado` = 'RENOMBRADO'
                WHERE `id` = %s;
            """, (doc["nombre_propuesto"], new_path, doc_id))

        return True, f"Renombrado exitoso a {doc['nombre_propuesto']}"
    except Exception as e:
        return False, f"Error al renombrar: {e}"
    finally:
        conn.close()

def export_results_to_excel(filepath, estado=None):
    """
    Exporta los resultados de auditoría a un archivo Excel (.xlsx).
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment

    filters = {}
    if estado and estado != "TODOS":
        filters["estado"] = estado

    data = get_audit_results(filters=filters, page=1, page_size=100000)
    items = data["items"]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Auditoría OCR"

    headers = [
        "ID", "Nombre Actual", "Delegación", "Año Actual", "Reg. Actual",
        "Reg. Encabezado", "Reg. Pie", "Coinciden Pie/Encabezado",
        "Reg. Antecedente (Trampa)", "Reg. Final Detectado", "Año Detectado",
        "Estado Auditoría", "Nombre Propuesto", "Choca en BD",
        "Confianza %", "Motivo / Diagnóstico",
        "Fecha Auditoría", "Ruta Completa"
    ]
    ws.append(headers)

    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    collision_fill = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
    collision_font = Font(name="Calibri", size=11, bold=True, color="991B1B")

    for col_num in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_idx, doc in enumerate(items, start=2):
        choca = bool(doc.get("colision_bd"))
        ws.append([
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
            "SÍ (CHOCA)" if choca else "NO",
            doc["confianza_score"],
            doc["motivo_discrepancia"],
            str(doc["fecha_auditoria"]),
            doc["ruta_completa"]
        ])
        if choca:
            col_cell = ws.cell(row=row_idx, column=14)
            col_cell.fill = collision_fill
            col_cell.font = collision_font

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = openpyxl.utils.get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 60)

    wb.save(filepath)
    return len(items)

def export_results_to_csv(filepath, estado=None):
    """
    Exporta los resultados de auditoría a un archivo CSV (UTF-8 con BOM para Excel).
    """
    import csv

    filters = {}
    if estado and estado != "TODOS":
        filters["estado"] = estado

    data = get_audit_results(filters=filters, page=1, page_size=100000)
    items = data["items"]

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow([
            "ID", "Nombre Actual", "Delegación", "Año Actual", "Reg. Actual",
            "Reg. Encabezado", "Reg. Pie", "Coinciden Pie/Encabezado",
            "Reg. Antecedente", "Reg. Final Detectado", "Año Detectado",
            "Estado", "Nombre Propuesto", "Choca en BD", "Confianza", "Motivo", "Ruta Completa"
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
                "SÍ" if doc.get("colision_bd") else "NO",
                doc["confianza_score"],
                doc["motivo_discrepancia"],
                doc["ruta_completa"]
            ])
    return len(items)
