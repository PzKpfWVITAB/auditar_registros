from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QMessageBox, QFileDialog, QProgressDialog
)
from PySide6.QtCore import Qt, QThread, Signal
from config import settings
from database import db_manager, connection


class _ImportCatalogWorker(QThread):
    progress = Signal(int, int)
    finished_result = Signal(bool, dict)

    def __init__(self, source_path):
        super().__init__()
        self.source_path = source_path

    def run(self):
        ok, res = db_manager.import_registros_existentes(
            source_path=self.source_path,
            progress_callback=lambda cur, tot: self.progress.emit(cur, tot),
            replace=True,
        )
        self.finished_result.emit(ok, res if isinstance(res, dict) else {"message": str(res)})


class DbToolsDialog(QDialog):
    """
    Formulario modal de Windows para administrar la base de datos MySQL
    (estructura, catálogo registros_existentes, base limpia o vaciar auditorías previas).
    """

    def __init__(self, parent=None, on_db_changed=None):
        super().__init__(parent)
        self.on_db_changed = on_db_changed
        self._import_worker = None
        self.setWindowTitle("Herramientas de Base de Datos MySQL")
        self.setMinimumWidth(560)
        self.setModal(True)
        self._init_ui()
        self._refresh_status()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Encabezado
        title = QLabel("Administración de Base de Datos MySQL")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #0f172a;")
        layout.addWidget(title)

        info_label = QLabel(
            f"Servidor: <b>{settings.DB_HOST}:{settings.DB_PORT}</b> &nbsp;|&nbsp; "
            f"Usuario: <b>{settings.DB_USER}</b> &nbsp;|&nbsp; "
            f"Base de Datos: <b>{settings.DB_NAME}</b>"
        )
        info_label.setStyleSheet("color: #475569; font-size: 12px;")
        layout.addWidget(info_label)

        self.status_label = QLabel("Verificando conexión...")
        self.status_label.setStyleSheet(
            "padding: 8px 12px; border-radius: 6px; font-size: 12px; font-weight: bold;"
        )
        layout.addWidget(self.status_label)

        self.catalog_label = QLabel("Catálogo registros_existentes: --")
        self.catalog_label.setStyleSheet(
            "background-color: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; "
            "padding: 7px 12px; border-radius: 6px; font-size: 12px; font-weight: bold;"
        )
        layout.addWidget(self.catalog_label)

        # Tarjeta 1: Inicializar / Reparar (Seguro)
        layout.addWidget(self._make_action_card(
            title="Inicializar / Reparar Estructura Completa",
            desc="Crea la base de datos y todas las tablas (incluida 'registros_existentes') conservando los datos actuales.",
            btn_text="Inicializar",
            btn_color="#2563eb",
            callback=lambda: self._run_action("init", clean=False)
        ))

        # Tarjeta 2: Generar Estructura Tabla registros_existentes
        layout.addWidget(self._make_action_card(
            title="Generar Estructura: Tabla 'registros_existentes'",
            desc="Crea únicamente la tabla catálogo de PDFs existentes y la columna de colisión sin tocar datos.",
            btn_text="Crear Tabla",
            btn_color="#0284c7",
            callback=self._create_registros_table
        ))

        # Tarjeta 3: Alimentar Tabla registros_existentes
        layout.addWidget(self._make_action_card(
            title="Alimentar Tabla 'registros_existentes'",
            desc="Carga los nombres de PDFs desde el catálogo del repositorio (.txt.gz) o desde 'Total registros.txt' y marca colisiones.",
            btn_text="Alimentar Tabla",
            btn_color="#059669",
            callback=self._feed_registros_table
        ))

        # Tarjeta 4: Base de Datos Limpia (Recrear)
        layout.addWidget(self._make_action_card(
            title="Generar Base de Datos Limpia",
            desc="Elimina la base de datos previa y la vuelve a crear completamente limpia desde cero.",
            btn_text="Crear Limpia",
            btn_color="#d97706",
            callback=lambda: self._run_action("init", clean=True)
        ))

        # Tarjeta 5: Vaciar Auditorías
        layout.addWidget(self._make_action_card(
            title="Vaciar Auditorías Anteriores",
            desc="Borra lotes y resultados de auditoría anteriores, conservando el catálogo 'registros_existentes'.",
            btn_text="Vaciar Tablas",
            btn_color="#dc2626",
            callback=lambda: self._run_action("reset", clean=False)
        ))

        # Botón cerrar
        footer = QHBoxLayout()
        footer.addStretch()
        btn_close = QPushButton("Cerrar")
        btn_close.setMinimumWidth(100)
        btn_close.setMinimumHeight(34)
        btn_close.clicked.connect(self.accept)
        footer.addWidget(btn_close)
        layout.addLayout(footer)

    def _make_action_card(self, title, desc, btn_text, btn_color, callback):
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet(
            "QFrame { background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; }"
        )
        h_layout = QHBoxLayout(frame)
        h_layout.setContentsMargins(14, 12, 14, 12)
        h_layout.setSpacing(12)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #1e293b; border: none;")
        lbl_desc = QLabel(desc)
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("font-size: 11px; color: #64748b; border: none;")
        text_layout.addWidget(lbl_title)
        text_layout.addWidget(lbl_desc)

        btn = QPushButton(btn_text)
        btn.setMinimumWidth(115)
        btn.setMinimumHeight(34)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background-color: {btn_color}; color: white; font-weight: bold; "
            f"border-radius: 6px; padding: 6px 12px; border: none; }}"
            f"QPushButton:hover {{ opacity: 0.9; }}"
        )
        btn.clicked.connect(callback)

        h_layout.addLayout(text_layout, 1)
        h_layout.addWidget(btn)
        return frame

    def _refresh_status(self):
        ok, msg = connection.test_connection()
        if ok:
            self.status_label.setText(f"Estado MySQL: Conectado correctamente ({settings.DB_HOST}:{settings.DB_PORT})")
            self.status_label.setStyleSheet(
                "background-color: #dcfce7; color: #166534; border: 1px solid #86efac; "
                "padding: 8px 12px; border-radius: 6px; font-size: 12px; font-weight: bold;"
            )
            cnt = db_manager.get_registros_existentes_count()
            self.catalog_label.setText(f"Catálogo 'registros_existentes': {cnt:,} PDFs registrados")
        else:
            self.status_label.setText(f"Estado MySQL: Sin conexión ({msg})")
            self.status_label.setStyleSheet(
                "background-color: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; "
                "padding: 8px 12px; border-radius: 6px; font-size: 12px; font-weight: bold;"
            )
            self.catalog_label.setText("Catálogo 'registros_existentes': No disponible")

    def _create_registros_table(self):
        ok, msg = db_manager.init_registros_existentes_table()
        self._refresh_status()
        if ok:
            QMessageBox.information(self, "Estructura Creada", msg)
            if self.on_db_changed:
                self.on_db_changed()
        else:
            QMessageBox.critical(self, "Error de Base de Datos", msg)

    def _feed_registros_table(self):
        default_src = db_manager.DEFAULT_REGISTROS_FILE
        source_path = None

        if default_src.exists():
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Alimentar Tabla 'registros_existentes'")
            msg_box.setText(
                f"Se encontró el catálogo incluido en el repositorio:\n{default_src.name}\n\n"
                "¿Deseas cargar directamente este archivo o seleccionar otro (.txt / .txt.gz / .csv)?"
            )
            btn_repo = msg_box.addButton("Usar Catálogo del Repo", QMessageBox.AcceptRole)
            btn_file = msg_box.addButton("Seleccionar Archivo...", QMessageBox.ActionRole)
            btn_cancel = msg_box.addButton("Cancelar", QMessageBox.RejectRole)
            msg_box.exec()

            clicked = msg_box.clickedButton()
            if clicked == btn_cancel:
                return
            elif clicked == btn_repo:
                source_path = str(default_src)
            elif clicked == btn_file:
                chosen, _ = QFileDialog.getOpenFileName(
                    self,
                    "Seleccionar Archivo de Registros",
                    "",
                    "Archivos de Registros (*.txt *.gz *.csv);;Todos (*.*)"
                )
                if not chosen:
                    return
                source_path = chosen
        else:
            chosen, _ = QFileDialog.getOpenFileName(
                self,
                "Seleccionar Archivo de Registros (Total registros.txt)",
                "",
                "Archivos de Registros (*.txt *.gz *.csv);;Todos (*.*)"
            )
            if not chosen:
                return
            source_path = chosen

        prog = QProgressDialog("Cargando nombres de PDFs en MySQL...", None, 0, 100, self)
        prog.setWindowTitle("Alimentando 'registros_existentes'")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)

        self._import_worker = _ImportCatalogWorker(source_path)

        def on_progress(cur, tot):
            pct = int(cur / tot * 100) if tot > 0 else 0
            prog.setValue(pct)
            prog.setLabelText(f"Insertando registros en MySQL: {cur:,} / {tot:,}...")

        def on_done(ok, res):
            prog.close()
            self._refresh_status()
            if ok:
                QMessageBox.information(self, "Catálogo Alimentado", res.get("message", "Operación exitosa."))
                if self.on_db_changed:
                    self.on_db_changed()
            else:
                QMessageBox.critical(self, "Error Alimentando Catálogo", res.get("message", "Error desconocido."))

        self._import_worker.progress.connect(on_progress)
        self._import_worker.finished_result.connect(on_done)
        self._import_worker.start()

    def _run_action(self, action, clean=False):
        if clean or action == "reset":
            confirm = QMessageBox.question(
                self,
                "Confirmar Operación",
                "Esta acción eliminará los registros de auditoría existentes en MySQL.\n¿Deseas continuar?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if confirm != QMessageBox.Yes:
                return

        if action == "init":
            ok, msg = db_manager.init_database(clean=clean)
        else:
            ok, msg = db_manager.reset_database()

        self._refresh_status()

        if ok:
            QMessageBox.information(self, "Operación Exitosa", msg)
            if self.on_db_changed:
                self.on_db_changed()
        else:
            QMessageBox.critical(self, "Error de Base de Datos", msg)
