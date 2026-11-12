import json
from pathlib import Path
from database.connection import get_raw_connection, test_connection
from config import settings

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
        return True, "Base de datos y tablas inicializadas correctamente."
    except Exception as e:
        return False, f"Error inicializando la base de datos: {e}"
    finally:
        conn.close()

def reset_database():
    """
    Vacía las tablas de auditoría para comenzar un lote desde cero sin borrar la estructura.
    """
    conn = get_raw_connection(include_database=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
            cursor.execute("TRUNCATE TABLE `historial_renombrado`;")
            cursor.execute("TRUNCATE TABLE `documentos_auditados`;")
            cursor.execute("TRUNCATE TABLE `lotes_auditoria`;")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
        return True, "Tablas de auditoría limpiadas exitosamente."
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
    Guarda o actualiza el resultado de la auditoría de un documento.
    """
    conn = get_raw_connection(include_database=True)
    try:
        with conn.cursor() as cursor:
            sql = """
                INSERT INTO `documentos_auditados` (
                    `lote_id`, `nombre_archivo`, `ruta_completa`, `tamano_bytes`,
                    `delegacion_actual`, `anio_actual`, `registro_actual`,
                    `registro_encabezado`, `registro_pie`, `anio_detectado`,
                    `fecha_registro_texto`, `registro_antecedente`,
                    `registro_final_detectado`, `coincide_encabezado_pie`,
                    `estado`, `nombre_propuesto`, `confianza_score`,
                    `motivo_discrepancia`, `bounding_boxes_json`, `tiempo_proceso_ms`
                ) VALUES (
                    %(lote_id)s, %(nombre_archivo)s, %(ruta_completa)s, %(tamano_bytes)s,
                    %(delegacion_actual)s, %(anio_actual)s, %(registro_actual)s,
                    %(registro_encabezado)s, %(registro_pie)s, %(anio_detectado)s,
                    %(fecha_registro_texto)s, %(registro_antecedente)s,
                    %(registro_final_detectado)s, %(coincide_encabezado_pie)s,
                    %(estado)s, %(nombre_propuesto)s, %(confianza_score)s,
                    %(motivo_discrepancia)s, %(bounding_boxes_json)s, %(tiempo_proceso_ms)s
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
                "motivo_discrepancia": doc.get("motivo_discrepancia"),
                "bounding_boxes_json": json.dumps(doc.get("bounding_boxes", {}), ensure_ascii=False),
                "tiempo_proceso_ms": doc.get("tiempo_proceso_ms", 0)
            })
            return cursor.lastrowid
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
                    SUM(CASE WHEN coincide_encabezado_pie = 1 THEN 1 ELSE 0 END) AS certeza_doble_marca
                FROM `documentos_auditados` {where_clause};
            """
            cursor.execute(sql, params)
            res = cursor.fetchone() or {}
            
            total = res.get("total", 0) or 0
            correctos = res.get("correctos", 0) or 0
            discrepancias = res.get("discrepancias", 0) or 0
            errores = res.get("errores", 0) or 0
            tasa_error = round((discrepancias / total * 100), 2) if total > 0 else 0.0

            return {
                "total": total,
                "correctos": correctos,
                "discrepancias": discrepancias,
                "errores": errores,
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
                else:
                    conditions.append("estado = %s")
                    params.append(filters["estado"])

            if filters.get("search"):
                term = f"%{filters['search']}%"
                conditions.append("(nombre_archivo LIKE %s OR registro_actual LIKE %s OR registro_final_detectado LIKE %s)")
                params.extend([term, term, term])

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
                       estado_renombrado, fecha_auditoria
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
