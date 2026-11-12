import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from PySide6.QtWidgets import QApplication
from database import db_manager
from desktop.main_window import MainWindow
from desktop.db_dialog import DbToolsDialog
from desktop.preview_dialog import PreviewDialog


def run_desktop_tests():
    print("=" * 65)
    print("PRUEBAS DE FORMULARIOS WINDOWS (PYSIDE6 OFFSCREEN)")
    print("=" * 65)

    app = QApplication.instance() or QApplication(sys.argv)

    # 1. MainWindow
    print("[1/4] Instanciando MainWindow...")
    win = MainWindow()
    assert win.table.columnCount() == 11
    print(f" -> KPI Total en UI: {win.kpi_total['value_label'].text()}")
    print(f" -> Filas cargadas en tabla: {win.table.rowCount()}")

    # 2. Filtros
    print("[2/4] Probando filtros de tabla...")
    win._set_filter("DISCREPANCIAS")
    print(f" -> Filas en DISCREPANCIAS: {win.table.rowCount()}")
    win._set_filter("TODOS")

    # 3. DbToolsDialog
    print("[3/4] Instanciando DbToolsDialog...")
    db_dlg = DbToolsDialog(parent=win)
    assert "Conectado" in db_dlg.status_label.text()
    print(f" -> Estado mostrado: {db_dlg.status_label.text()}")
    db_dlg.close()

    # 4. PreviewDialog (si existe al menos 1 documento en BD)
    print("[4/4] Probando PreviewDialog y Exportación...")
    res = db_manager.get_audit_results(page=1, page_size=1)
    if res["items"]:
        doc_id = res["items"][0]["id"]
        prev_dlg = PreviewDialog(doc_id, parent=win)
        print(f" -> Preview abierto para ID={doc_id}: {prev_dlg.lbl_file_title.text()}")
        prev_dlg.close()

    # Exportaciones directas
    xlsx_tmp = str(root_dir / "tests" / "_tmp_export.xlsx")
    csv_tmp = str(root_dir / "tests" / "_tmp_export.csv")
    c_xlsx = db_manager.export_results_to_excel(xlsx_tmp)
    c_csv = db_manager.export_results_to_csv(csv_tmp)
    assert os.path.exists(xlsx_tmp) and os.path.getsize(xlsx_tmp) > 0
    assert os.path.exists(csv_tmp) and os.path.getsize(csv_tmp) > 0
    os.remove(xlsx_tmp)
    os.remove(csv_tmp)
    print(f" -> Exportaciones Excel ({c_xlsx}) y CSV ({c_csv}) verificadas.")

    win.close()
    print("\n[OK] TODAS LAS PRUEBAS DE ESCRITORIO PASARON EXITOSAMENTE.")


if __name__ == "__main__":
    run_desktop_tests()
