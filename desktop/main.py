import sys
import traceback
import threading
from pathlib import Path

# Agregar raíz del proyecto al PYTHONPATH
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.logger import setup_logging
logger = setup_logging("desktop")

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QFont

from database import connection, db_manager
from desktop.main_window import MainWindow


def _global_excepthook(exc_type, exc_value, exc_tb):
    err_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical("EXCEPCIÓN NO CONTROLADA EN HILO PRINCIPAL:\n%s", err_text)
    if QApplication.instance() is not None:
        QMessageBox.critical(
            None,
            "Error Inesperado",
            f"Ocurrió un error inesperado (guardado en logs/auditoria.log):\n\n{exc_value}"
        )
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _thread_excepthook(args):
    err_text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    logger.critical("EXCEPCIÓN NO CONTROLADA EN HILO SECUNDARIO (%s):\n%s", args.thread, err_text)


sys.excepthook = _global_excepthook
threading.excepthook = _thread_excepthook


def main():
    logger.info("=== Iniciando aplicación de escritorio Auditoría OCR ===")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 9))

    # Intentar inicializar tablas de forma segura si MySQL está activo
    ok, msg = connection.test_connection()
    logger.info("Conexión MySQL inicial: ok=%s msg=%s", ok, msg)
    if ok:
        db_manager.init_database(clean=False)

    window = MainWindow()
    window.show()
    exit_code = app.exec()
    logger.info("=== Aplicación finalizada con código %s ===", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
