import os
import time
import threading
import traceback
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import List, Optional

from config import settings
from core.document_analyzer import analyze_document
from core.logger import setup_logging, get_logger
from database import db_manager


def _worker_analyze_file(file_path: str, lote_id: Optional[int]) -> dict:
    """
    Función de nivel superior ejecutada en un proceso hijo aislado.
    Aísla WinRT (winocr) y PyMuPDF del proceso principal de Qt (PySide6).
    """
    log = setup_logging("worker")
    fname = os.path.basename(file_path)
    log.info("[WORKER START] %s", file_path)
    try:
        res = analyze_document(file_path, lote_id=lote_id)
        log.info("[WORKER OK] %s -> %s (%sms)", fname, res.get("estado"), res.get("tiempo_proceso_ms"))
        return res
    except Exception as e:
        log.error("[WORKER ERROR] %s: %s\n%s", fname, e, traceback.format_exc())
        raise


class AuditorManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.status = "IDLE"  # IDLE, RUNNING, STOPPED, COMPLETED
        self.should_stop = False

        self.lote_id: Optional[int] = None
        self.directorio: str = ""
        self.total_files: int = 0
        self.processed_files: int = 0
        self.correct_files: int = 0
        self.discrepancy_files: int = 0
        self.error_files: int = 0
        self.current_file: str = ""
        self.start_time: float = 0
        self.elapsed_seconds: float = 0
        self.logs: List[str] = []
        self._thread: Optional[threading.Thread] = None

    def get_progress(self):
        with self.lock:
            pct = round((self.processed_files / self.total_files * 100), 1) if self.total_files > 0 else 0.0
            elapsed = round(time.time() - self.start_time, 1) if self.status == "RUNNING" else self.elapsed_seconds
            rate = round(self.processed_files / elapsed, 1) if elapsed > 0 else 0.0

            return {
                "status": self.status,
                "lote_id": self.lote_id,
                "directorio": self.directorio,
                "total_files": self.total_files,
                "processed_files": self.processed_files,
                "correct_files": self.correct_files,
                "discrepancy_files": self.discrepancy_files,
                "error_files": self.error_files,
                "current_file": self.current_file,
                "progress_pct": pct,
                "elapsed_seconds": elapsed,
                "rate_docs_per_sec": rate,
                "recent_logs": self.logs[-15:]
            }

    def add_log(self, msg: str, level: str = "info"):
        log = get_logger()
        if level == "error":
            log.error(msg)
        elif level == "critical":
            log.critical(msg)
        else:
            log.info(msg)

        with self.lock:
            timestamp = time.strftime("%H:%M:%S")
            self.logs.append(f"[{timestamp}] {msg}")
            if len(self.logs) > 200:
                self.logs.pop(0)

    def stop(self):
        with self.lock:
            self.should_stop = True
            self.status = "STOPPED"
        self.add_log("Auditoría detenida por el usuario.")

    def start_audit(self, directory: str, recursive: bool = False, limit: Optional[int] = None):
        with self.lock:
            if self.status == "RUNNING":
                return False, "Ya hay una auditoría en curso."

            self.status = "RUNNING"
            self.should_stop = False
            self.directorio = directory
            self.total_files = 0
            self.processed_files = 0
            self.correct_files = 0
            self.discrepancy_files = 0
            self.error_files = 0
            self.current_file = ""
            self.start_time = time.time()
            self.elapsed_seconds = 0
            self.logs = []

        self._thread = threading.Thread(
            target=self._run_audit_worker,
            args=(directory, recursive, limit),
            daemon=True
        )
        self._thread.start()
        return True, "Auditoría iniciada correctamente."

    def start_retry_errors(self):
        """
        Reintenta todos los documentos que quedaron con estado ERROR_LECTURA o NOMBRE_INVALIDO,
        actualizando sus registros existentes en MySQL.
        """
        error_docs = db_manager.get_error_documents()
        if not error_docs:
            return False, "No hay documentos con error pendientes de reintentar."

        with self.lock:
            if self.status == "RUNNING":
                return False, "Ya hay una auditoría o reintento en curso."

            self.status = "RUNNING"
            self.should_stop = False
            self.directorio = "Reintento de errores"
            self.total_files = len(error_docs)
            self.processed_files = 0
            self.correct_files = 0
            self.discrepancy_files = 0
            self.error_files = 0
            self.current_file = ""
            self.start_time = time.time()
            self.elapsed_seconds = 0
            self.logs = []

        self._thread = threading.Thread(
            target=self._run_retry_worker,
            args=(error_docs,),
            daemon=True
        )
        self._thread.start()
        return True, f"Reintentando {len(error_docs)} documentos con error."

    def retry_single_document(self, doc_id: int):
        """
        Reintenta un único documento por su ID en un proceso aislado y actualiza MySQL.
        """
        doc = db_manager.get_document_by_id(doc_id)
        if not doc:
            return False, "Documento no encontrado en base de datos.", None

        file_path = doc["ruta_completa"]
        try:
            with ProcessPoolExecutor(max_workers=1) as single_exec:
                res = single_exec.submit(_worker_analyze_file, file_path, doc.get("lote_id")).result(timeout=60)
            db_manager.update_audit_result(doc_id, res)
            return True, f"Reintento completado: {res.get('estado')}", res
        except Exception as e:
            self.add_log(f"Error reintentando documento ID={doc_id} ({file_path}): {e}", level="error")
            return False, f"Falló el reintento: {e}", None

    def _run_retry_worker(self, error_docs: List[dict]):
        try:
            self.add_log(f"Iniciando reintento de {len(error_docs)} archivos con error...")
            max_workers = min(settings.MAX_WORKERS, max(1, len(error_docs)))

            idx = 0
            while idx < len(error_docs) and not self.should_stop:
                batch = error_docs[idx:idx + max_workers]
                try:
                    with ProcessPoolExecutor(max_workers=max_workers) as executor:
                        while idx < len(error_docs) and not self.should_stop:
                            batch = error_docs[idx:idx + max_workers]
                            futures = [
                                (item, executor.submit(_worker_analyze_file, item["ruta_completa"], item.get("lote_id")))
                                for item in batch
                            ]

                            for item, fut in futures:
                                if self.should_stop:
                                    break
                                f_name = item["nombre_archivo"]
                                try:
                                    res = fut.result(timeout=60)
                                    db_manager.update_audit_result(item["id"], res)
                                    with self.lock:
                                        self.processed_files += 1
                                        self.current_file = f_name
                                        estado = res.get("estado")
                                        if estado == "CORRECTO":
                                            self.correct_files += 1
                                        elif estado in ("DISCREPANCIA_REGISTRO", "DISCREPANCIA_ANIO", "AMBAS_DISCREPANCIAS"):
                                            self.discrepancy_files += 1
                                        else:
                                            self.error_files += 1
                                except BrokenProcessPool:
                                    raise
                                except Exception as e:
                                    self.add_log(f"Error en reintento de {f_name}: {e}", level="error")
                                    with self.lock:
                                        self.processed_files += 1
                                        self.error_files += 1
                                idx += 1
                except BrokenProcessPool:
                    self.add_log("Worker falló en reintento por lotes; aislando de uno en uno...", level="critical")
                    for item in batch:
                        if self.should_stop:
                            break
                        ok, _, res = self.retry_single_document(item["id"])
                        with self.lock:
                            self.processed_files += 1
                            self.current_file = item["nombre_archivo"]
                            if ok and res:
                                estado = res.get("estado")
                                if estado == "CORRECTO":
                                    self.correct_files += 1
                                elif estado in ("DISCREPANCIA_REGISTRO", "DISCREPANCIA_ANIO", "AMBAS_DISCREPANCIAS"):
                                    self.discrepancy_files += 1
                                else:
                                    self.error_files += 1
                            else:
                                self.error_files += 1
                        idx += 1
        except Exception as fatal_err:
            self.add_log(f"ERROR FATAL EN REINTENTO: {fatal_err}\n{traceback.format_exc()}", level="critical")
        finally:
            with self.lock:
                self.status = "COMPLETED" if not self.should_stop else "STOPPED"
                self.elapsed_seconds = time.time() - self.start_time
            self.add_log(
                f"Reintento finalizado. Total: {self.processed_files}/{self.total_files} | "
                f"Correctos: {self.correct_files} | Discrepancias: {self.discrepancy_files} | Errores: {self.error_files}"
            )

    def _discover_files(self, directory: str, recursive: bool, limit: Optional[int]) -> List[str]:
        pdf_files = []
        if not os.path.exists(directory):
            self.add_log(f"ERROR: El directorio '{directory}' no existe o no es accesible.", level="error")
            return []

        try:
            if recursive:
                for root, _, files in os.walk(directory):
                    for f in files:
                        if f.lower().endswith((".pdf", ".jpg", ".jpeg", ".png")):
                            pdf_files.append(os.path.join(root, f))
                            if limit and len(pdf_files) >= limit:
                                return pdf_files
            else:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if entry.is_file() and entry.name.lower().endswith((".pdf", ".jpg", ".jpeg", ".png")):
                            pdf_files.append(entry.path)
                            if limit and len(pdf_files) >= limit:
                                return pdf_files
        except Exception as e:
            self.add_log(f"Error explorando directorio: {str(e)}\n{traceback.format_exc()}", level="error")

        return pdf_files

    def _record_crash_result(self, file_path: str, reason: str):
        fname = os.path.basename(file_path)
        crash_doc = {
            "lote_id": self.lote_id,
            "nombre_archivo": fname,
            "ruta_completa": file_path,
            "tamano_bytes": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
            "estado": "ERROR_LECTURA",
            "confianza_score": 0,
            "motivo_discrepancia": reason,
            "bounding_boxes": {},
            "tiempo_proceso_ms": 0
        }
        try:
            db_manager.save_audit_result(crash_doc)
        except Exception as db_err:
            self.add_log(f"Error guardando fallo en MySQL ({fname}): {db_err}", level="error")

    def _run_audit_worker(self, directory: str, recursive: bool, limit: Optional[int]):
        try:
            self.add_log(f"Iniciando escaneo en: {directory}")

            # 1. Crear lote en MySQL
            try:
                self.lote_id = db_manager.create_lote(directory)
                self.add_log(f"Lote de auditoría #{self.lote_id} creado en base de datos.")
            except Exception as e:
                self.add_log(f"Advertencia: No se pudo registrar lote en MySQL: {e}", level="error")
                self.lote_id = None

            # 2. Descubrir archivos
            files = self._discover_files(directory, recursive, limit)
            with self.lock:
                self.total_files = len(files)

            if not files:
                self.add_log("No se encontraron archivos PDF para analizar.")
                with self.lock:
                    self.status = "COMPLETED"
                    self.elapsed_seconds = time.time() - self.start_time
                if self.lote_id:
                    db_manager.update_lote_summary(self.lote_id, 0, 0, 0, 0, "COMPLETADO")
                return

            max_workers = min(settings.MAX_WORKERS, max(1, len(files)))
            self.add_log(f"Se encontraron {len(files)} archivos. Procesando en procesos aislados ({max_workers} workers)...")

            # 3. Procesar secuencialmente por lotes en ProcessPoolExecutor para aislar fallos catastróficos
            idx = 0
            while idx < len(files) and not self.should_stop:
                file_path = files[idx]
                fname = os.path.basename(file_path)
                with self.lock:
                    self.current_file = fname

                try:
                    with ProcessPoolExecutor(max_workers=max_workers) as executor:
                        # Enviar en bloques para poder recuperarnos ante un BrokenProcessPool si un PDF crashea en C/WinRT
                        while idx < len(files) and not self.should_stop:
                            batch = files[idx:idx + max_workers]
                            futures = [(f, executor.submit(_worker_analyze_file, f, self.lote_id)) for f in batch]

                            for f_path, fut in futures:
                                if self.should_stop:
                                    break
                                f_name = os.path.basename(f_path)
                                try:
                                    res = fut.result(timeout=60)
                                    try:
                                        db_manager.save_audit_result(res)
                                    except Exception as db_err:
                                        self.add_log(f"Error MySQL ({f_name}): {db_err}", level="error")

                                    with self.lock:
                                        self.processed_files += 1
                                        self.current_file = f_name
                                        estado = res.get("estado")
                                        if estado == "CORRECTO":
                                            self.correct_files += 1
                                        elif estado in ("DISCREPANCIA_REGISTRO", "DISCREPANCIA_ANIO", "AMBAS_DISCREPANCIAS"):
                                            self.discrepancy_files += 1
                                            self.add_log(f"[DISCREPANCIA] {f_name} -> Sugerido: {res.get('nombre_propuesto')}")
                                        else:
                                            self.error_files += 1

                                except BrokenProcessPool:
                                    raise
                                except Exception as e:
                                    self.add_log(f"Error procesando {f_name}: {e}", level="error")
                                    self._record_crash_result(f_path, f"Error procesando archivo: {e}")
                                    with self.lock:
                                        self.processed_files += 1
                                        self.error_files += 1

                                idx += 1

                except BrokenProcessPool:
                    # Un proceso hijo murió por fallo nativo (C/WinRT); la GUI sigue intacta
                    self.add_log(
                        f"FALLO CATASTRÓFICO DE WORKER al procesar bloque cerca de '{fname}'. "
                        f"Reintentando de uno en uno para aislar el PDF dañado.",
                        level="critical"
                    )
                    # Procesar el archivo actual de forma individual aislada
                    for f_path in files[idx:idx + max_workers]:
                        if self.should_stop:
                            break
                        f_name = os.path.basename(f_path)
                        try:
                            with ProcessPoolExecutor(max_workers=1) as single_exec:
                                res = single_exec.submit(_worker_analyze_file, f_path, self.lote_id).result(timeout=60)
                            db_manager.save_audit_result(res)
                            with self.lock:
                                self.processed_files += 1
                                estado = res.get("estado")
                                if estado == "CORRECTO":
                                    self.correct_files += 1
                                elif estado in ("DISCREPANCIA_REGISTRO", "DISCREPANCIA_ANIO", "AMBAS_DISCREPANCIAS"):
                                    self.discrepancy_files += 1
                                else:
                                    self.error_files += 1
                        except Exception as single_err:
                            self.add_log(
                                f"PDF CAUSANTE DE CRASH AISLADO: {f_path} -> {single_err}",
                                level="critical"
                            )
                            self._record_crash_result(
                                f_path,
                                f"Fallo catastrófico al leer/OCR el archivo (aislado sin cerrar el sistema): {single_err}"
                            )
                            with self.lock:
                                self.processed_files += 1
                                self.error_files += 1
                        idx += 1

        except Exception as fatal_err:
            self.add_log(
                f"ERROR FATAL EN HILO AUDITOR:\n{fatal_err}\n{traceback.format_exc()}",
                level="critical"
            )
        finally:
            with self.lock:
                self.status = "COMPLETED" if not self.should_stop else "STOPPED"
                self.elapsed_seconds = time.time() - self.start_time

            self.add_log(
                f"Auditoría finalizada. Total: {self.processed_files}/{self.total_files} | "
                f"Correctos: {self.correct_files} | Discrepancias: {self.discrepancy_files} | Errores: {self.error_files}"
            )

            if self.lote_id:
                try:
                    lote_estado = "COMPLETADO" if self.status == "COMPLETED" else "CANCELADO"
                    db_manager.update_lote_summary(
                        self.lote_id,
                        self.processed_files,
                        self.correct_files,
                        self.discrepancy_files,
                        self.error_files,
                        lote_estado
                    )
                except Exception as db_err:
                    self.add_log(f"Error actualizando resumen de lote: {db_err}", level="error")


# Instancia global del auditor
auditor_instance = AuditorManager()
