import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from config import settings
from core.document_analyzer import analyze_document
from database import db_manager

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

    def add_log(self, msg: str):
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

    def _discover_files(self, directory: str, recursive: bool, limit: Optional[int]) -> List[str]:
        pdf_files = []
        if not os.path.exists(directory):
            self.add_log(f"ERROR: El directorio '{directory}' no existe o no es accesible.")
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
            self.add_log(f"Error explorando directorio: {str(e)}")
            
        return pdf_files

    def _run_audit_worker(self, directory: str, recursive: bool, limit: Optional[int]):
        self.add_log(f"Iniciando escaneo en: {directory}")
        
        # 1. Crear lote en MySQL
        try:
            self.lote_id = db_manager.create_lote(directory)
            self.add_log(f"Lote de auditoría #{self.lote_id} creado en base de datos.")
        except Exception as e:
            self.add_log(f"Advertencia: No se pudo registrar lote en MySQL: {e}")
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

        self.add_log(f"Se encontraron {len(files)} archivos para auditar. Procesando con {settings.MAX_WORKERS} hilos...")

        # 3. Procesamiento en paralelo
        max_workers = min(settings.MAX_WORKERS, max(1, len(files)))
        
        def process_single_file(file_path):
            if self.should_stop:
                return None
            res = analyze_document(file_path, lote_id=self.lote_id)
            # Guardar en MySQL inmediatamente
            try:
                db_manager.save_audit_result(res)
            except Exception as e:
                self.add_log(f"Error guardando en MySQL ({os.path.basename(file_path)}): {e}")
            return res

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {executor.submit(process_single_file, f): f for f in files}

            for future in as_completed(future_to_file):
                if self.should_stop:
                    break

                file_path = future_to_file[future]
                fname = os.path.basename(file_path)

                try:
                    res = future.result()
                    if res is None:
                        continue

                    with self.lock:
                        self.processed_files += 1
                        self.current_file = fname
                        
                        estado = res.get("estado")
                        if estado == "CORRECTO":
                            self.correct_files += 1
                        elif estado in ("DISCREPANCIA_REGISTRO", "DISCREPANCIA_ANIO", "AMBAS_DISCREPANCIAS"):
                            self.discrepancy_files += 1
                            self.add_log(f"[DISCREPANCIA] {fname} -> Sugerido: {res.get('nombre_propuesto')}")
                        else:
                            self.error_files += 1

                except Exception as e:
                    with self.lock:
                        self.processed_files += 1
                        self.error_files += 1
                    self.add_log(f"Error procesando {fname}: {str(e)}")

        with self.lock:
            self.status = "COMPLETED" if not self.should_stop else "STOPPED"
            self.elapsed_seconds = time.time() - self.start_time

        self.add_log(
            f"Auditoría finalizada. Total: {self.processed_files}/{self.total_files} | "
            f"Correctos: {self.correct_files} | Discrepancias: {self.discrepancy_files} | Errores: {self.error_files}"
        )

        if self.lote_id:
            lote_estado = "COMPLETADO" if self.status == "COMPLETED" else "CANCELADO"
            db_manager.update_lote_summary(
                self.lote_id,
                self.processed_files,
                self.correct_files,
                self.discrepancy_files,
                self.error_files,
                lote_estado
            )

# Instancia global del auditor
auditor_instance = AuditorManager()
