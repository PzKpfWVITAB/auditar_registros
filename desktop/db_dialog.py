from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QMessageBox
)
from PySide6.QtCore import Qt
from config import settings
from database import db_manager, connection


class DbToolsDialog(QDialog):
    """
    Formulario modal de Windows para administrar la base de datos MySQL
    (crear limpia, reparar estructura o vaciar auditorías previas).
    """

    def __init__(self, parent=None, on_db_changed=None):
        super().__init__(parent)
        self.on_db_changed = on_db_changed
        self.setWindowTitle("Herramientas de Base de Datos MySQL")
        self.setMinimumWidth(520)
        self.setModal(True)
        self._init_ui()
        self._refresh_status()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
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

        # Tarjeta 1: Inicializar / Reparar (Seguro)
        layout.addWidget(self._make_action_card(
            title="Inicializar / Reparar Estructura",
            desc="Crea la base de datos y las tablas necesarias si no existen, conservando los datos actuales.",
            btn_text="Inicializar",
            btn_color="#2563eb",
            callback=lambda: self._run_action("init", clean=False)
        ))

        # Tarjeta 2: Base de Datos Limpia (Recrear)
        layout.addWidget(self._make_action_card(
            title="Generar Base de Datos Limpia",
            desc="Elimina la base de datos previa y la vuelve a crear completamente limpia desde cero.",
            btn_text="Crear Limpia",
            btn_color="#d97706",
            callback=lambda: self._run_action("init", clean=True)
        ))

        # Tarjeta 3: Vaciar Registros
        layout.addWidget(self._make_action_card(
            title="Vaciar Auditorías Anteriores",
            desc="Conserva la estructura de tablas pero borra todos los registros de corridas anteriores.",
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
        else:
            self.status_label.setText(f"Estado MySQL: Sin conexión ({msg})")
            self.status_label.setStyleSheet(
                "background-color: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; "
                "padding: 8px 12px; border-radius: 6px; font-size: 12px; font-weight: bold;"
            )

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
