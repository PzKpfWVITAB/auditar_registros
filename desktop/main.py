import os
import sys
import faulthandler
import traceback
import threading
from datetime import datetime
from pathlib import Path

# Agregar raíz del proyecto al PYTHONPATH
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Carpeta de logs para diagnóstico si ocurre algún fallo
LOGS_DIR = ROOT_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

_crash_file = open(LOGS_DIR / "crash.log", "a", encoding="utf-8")
faulthandler.enable(file=_crash_file, all_threads=True)

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QFont

from database import connection, db_manager
from desktop.main_window import MainWindow


def _log_exception(exc_type, exc_value, exc_tb):
    err_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    log_path = LOGS_DIR / "app_error.log"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n=== {datetime.now().isoformat()} ===\n{err_text}\n")
    return err_text


def _global_excepthook(exc_type, exc_value, exc_tb):
    err_text = _log_exception(exc_type, exc_value, exc_tb)
    if QApplication.instance() is not None:
        QMessageBox.critical(
            None,
            "Error Inesperado",
            f"Ocurrió un error inesperado (guardado en logs/app_error.log):\n\n{exc_value}"
        )
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _thread_excepthook(args):
    _log_exception(args.exc_type, args.exc_value, args.exc_traceback)


sys.excepthook = _global_excepthook
threading.excepthook = _thread_excepthook


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))

    # Intentar inicializar tablas de forma segura si MySQL está activo
    ok, _ = connection.test_connection()
    if ok:
        db_manager.init_database(clean=False)

    window = MainWindow()
    window.show()
    exit_code = app.exec()
    _crash_file.flush()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
