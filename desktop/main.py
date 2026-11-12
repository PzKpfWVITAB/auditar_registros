import sys
from pathlib import Path

# Agregar raíz del proyecto al PYTHONPATH
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from database import connection, db_manager
from desktop.main_window import MainWindow


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
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
