import os
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QProgressBar, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QFileDialog, QMessageBox, QAbstractItemView, QApplication
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont

from config import settings
from database import db_manager, connection
from core.auditor import auditor_instance
from desktop.db_dialog import DbToolsDialog
from desktop.preview_dialog import PreviewDialog


class MainWindow(QMainWindow):
    """
    Formulario principal de Windows para el Sistema de Auditoría Registral por OCR.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sistema de Auditoría Registral por OCR | RPPC & MySQL")
        self.resize(1320, 840)

        self.current_filter = "TODOS"
        self.current_page = 1
        self.page_size = 25
        self.total_pages = 1
        self.search_query = ""
        self.was_running = False

        self._init_ui()
        self._setup_timers()

        # Carga inicial
        self._check_db_status()
        self._load_summary()
        self._load_table_data()

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(16, 14, 16, 14)
        root_layout.setSpacing(12)

        # ------------------------------------------------------------------
        # 1. ENCABEZADO Y ESTADO MYSQL
        # ------------------------------------------------------------------
        header_layout = QHBoxLayout()
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        lbl_title = QLabel("Sistema de Auditoría Registral por OCR")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #0f172a;")
        lbl_sub = QLabel("Verificación espacial de inscripciones PDF, detección de discrepancias y control en MySQL")
        lbl_sub.setStyleSheet("font-size: 12px; color: #64748b;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        header_layout.addLayout(title_box, 1)

        self.lbl_db_status = QLabel("MySQL: Verificando...")
        self.lbl_db_status.setStyleSheet(
            "padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: bold;"
        )
        header_layout.addWidget(self.lbl_db_status)

        btn_db_tools = QPushButton("Herramientas Base de Datos")
        btn_db_tools.setMinimumHeight(34)
        btn_db_tools.setCursor(Qt.PointingHandCursor)
        btn_db_tools.setStyleSheet(
            "QPushButton { background-color: #1e293b; color: white; font-weight: bold; "
            "border-radius: 6px; padding: 6px 14px; }"
            "QPushButton:hover { background-color: #334155; }"
        )
        btn_db_tools.clicked.connect(self._open_db_dialog)
        header_layout.addWidget(btn_db_tools)

        root_layout.addLayout(header_layout)

        # ------------------------------------------------------------------
        # 2. PANEL DE CONTROL DE ESCANEO
        # ------------------------------------------------------------------
        control_frame = QFrame()
        control_frame.setStyleSheet(
            "QFrame { background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; }"
        )
        control_vbox = QVBoxLayout(control_frame)
        control_vbox.setContentsMargins(14, 12, 14, 12)
        control_vbox.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(8)

        lbl_dir = QLabel("Directorio PDFs:")
        lbl_dir.setStyleSheet("font-weight: bold; font-size: 12px; color: #1e293b; border: none;")
        row1.addWidget(lbl_dir)

        self.txt_directory = QLineEdit(settings.DEFAULT_SCAN_PATH)
        self.txt_directory.setMinimumHeight(32)
        self.txt_directory.setPlaceholderText(r"\\172.40.5.84\ssdirec\COPIA_REGISTROS o C:\pdfs")
        self.txt_directory.setStyleSheet(
            "background-color: white; border: 1px solid #94a3b8; border-radius: 5px; padding: 4px 8px; font-family: Consolas;"
        )
        row1.addWidget(self.txt_directory, 1)

        btn_browse = QPushButton("Examinar...")
        btn_browse.setMinimumHeight(32)
        btn_browse.setCursor(Qt.PointingHandCursor)
        btn_browse.clicked.connect(self._browse_directory)
        row1.addWidget(btn_browse)

        self.chk_recursive = QCheckBox("Subcarpetas")
        self.chk_recursive.setChecked(settings.SCAN_RECURSIVE)
        self.chk_recursive.setStyleSheet("border: none; font-size: 12px; color: #334155;")
        row1.addWidget(self.chk_recursive)

        self.cmb_limit = QComboBox()
        self.cmb_limit.setMinimumHeight(32)
        self.cmb_limit.addItem("Sin límite (Todos)", None)
        self.cmb_limit.addItem("10 archivos (Prueba)", 10)
        self.cmb_limit.addItem("50 archivos", 50)
        self.cmb_limit.addItem("200 archivos", 200)
        row1.addWidget(self.cmb_limit)

        self.btn_start = QPushButton("Iniciar Auditoría")
        self.btn_start.setMinimumHeight(34)
        self.btn_start.setMinimumWidth(140)
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setStyleSheet(
            "QPushButton { background-color: #059669; color: white; font-weight: bold; "
            "border-radius: 6px; padding: 6px 14px; border: none; }"
            "QPushButton:hover { background-color: #047857; }"
            "QPushButton:disabled { background-color: #94a3b8; }"
        )
        self.btn_start.clicked.connect(self._start_scan)
        row1.addWidget(self.btn_start)

        self.btn_stop = QPushButton("Detener")
        self.btn_stop.setMinimumHeight(34)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setStyleSheet(
            "QPushButton { background-color: #dc2626; color: white; font-weight: bold; "
            "border-radius: 6px; padding: 6px 14px; border: none; }"
            "QPushButton:hover { background-color: #b91c1c; }"
            "QPushButton:disabled { background-color: #cbd5e1; color: #64748b; }"
        )
        self.btn_stop.clicked.connect(self._stop_scan)
        row1.addWidget(self.btn_stop)

        control_vbox.addLayout(row1)

        # Barra de progreso
        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimumHeight(18)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        progress_row.addWidget(self.progress_bar, 1)

        self.lbl_progress_info = QLabel("Listo para auditar")
        self.lbl_progress_info.setMinimumWidth(260)
        self.lbl_progress_info.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_progress_info.setStyleSheet("font-size: 11px; color: #475569; border: none;")
        progress_row.addWidget(self.lbl_progress_info)

        control_vbox.addLayout(progress_row)
        root_layout.addWidget(control_frame)

        # ------------------------------------------------------------------
        # 3. TARJETAS KPI
        # ------------------------------------------------------------------
        kpi_layout = QHBoxLayout()
        kpi_layout.setSpacing(10)

        self.kpi_total = self._make_kpi_card("Total Auditados", "0", "#1e293b", "#f1f5f9")
        self.kpi_correctos = self._make_kpi_card("Correctos", "0", "#166534", "#dcfce7")
        self.kpi_discrepancias = self._make_kpi_card("Con Discrepancias", "0", "#b45309", "#fef3c7")
        self.kpi_colisiones = self._make_kpi_card("Chocan en BD", "0", "#991b1b", "#fee2e2")
        self.kpi_errores = self._make_kpi_card("Errores Lectura", "0", "#7f1d1d", "#fecaca")
        self.kpi_tasa = self._make_kpi_card("Tasa Discrepancia", "0.0%", "#3730a3", "#e0e7ff")

        for card in (
            self.kpi_total, self.kpi_correctos, self.kpi_discrepancias,
            self.kpi_colisiones, self.kpi_errores, self.kpi_tasa
        ):
            kpi_layout.addWidget(card["frame"], 1)

        root_layout.addLayout(kpi_layout)

        # ------------------------------------------------------------------
        # 4. BARRA DE FILTROS, BÚSQUEDA Y EXPORTACIÓN
        # ------------------------------------------------------------------
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(8)

        self.filter_buttons = {}
        for key, label in [
            ("TODOS", "Todos"),
            ("DISCREPANCIAS", "Solo Discrepancias"),
            ("COLISION_BD", "Chocan en BD"),
            ("CORRECTO", "Correctos"),
            ("ERROR_LECTURA", "Errores")
        ]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setMinimumHeight(32)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, k=key: self._set_filter(k))
            self.filter_buttons[key] = btn
            filter_layout.addWidget(btn)

        self._update_filter_buttons_style()
        filter_layout.addStretch()

        self.txt_search = QLineEdit()
        self.txt_search.setMinimumHeight(32)
        self.txt_search.setMinimumWidth(240)
        self.txt_search.setPlaceholderText("Buscar archivo o número de registro...")
        self.txt_search.textChanged.connect(self._on_search_changed)
        filter_layout.addWidget(self.txt_search)

        btn_excel = QPushButton("Exportar Excel (.xlsx)")
        btn_excel.setMinimumHeight(32)
        btn_excel.setCursor(Qt.PointingHandCursor)
        btn_excel.setStyleSheet(
            "QPushButton { background-color: #15803d; color: white; font-weight: bold; "
            "border-radius: 5px; padding: 4px 12px; }"
            "QPushButton:hover { background-color: #166534; }"
        )
        btn_excel.clicked.connect(self._export_excel)
        filter_layout.addWidget(btn_excel)

        btn_csv = QPushButton("Exportar CSV")
        btn_csv.setMinimumHeight(32)
        btn_csv.setCursor(Qt.PointingHandCursor)
        btn_csv.clicked.connect(self._export_csv)
        filter_layout.addWidget(btn_csv)

        self.btn_retry_errors = QPushButton("Reintentar Errores")
        self.btn_retry_errors.setMinimumHeight(32)
        self.btn_retry_errors.setCursor(Qt.PointingHandCursor)
        self.btn_retry_errors.setStyleSheet(
            "QPushButton { background-color: #d97706; color: white; font-weight: bold; "
            "border-radius: 5px; padding: 4px 12px; }"
            "QPushButton:hover { background-color: #b45309; }"
            "QPushButton:disabled { background-color: #cbd5e1; color: #64748b; }"
        )
        self.btn_retry_errors.clicked.connect(self._retry_all_errors)
        filter_layout.addWidget(self.btn_retry_errors)

        btn_refresh = QPushButton("Refrescar")
        btn_refresh.setMinimumHeight(32)
        btn_refresh.clicked.connect(self._refresh_all)
        filter_layout.addWidget(btn_refresh)

        root_layout.addLayout(filter_layout)

        # ------------------------------------------------------------------
        # 5. TABLA DE RESULTADOS
        # ------------------------------------------------------------------
        self.table = QTableWidget()
        self.table.setColumnCount(12)
        self.table.setHorizontalHeaderLabels([
            "Estado", "Archivo Actual", "Reg. Actual", "Reg. Encabezado",
            "Reg. Pie", "Doble Marca", "Antecedente (Trampa)",
            "Nombre Propuesto", "Choca en BD", "Confianza", "Diagnóstico / Motivo", "Acciones"
        ])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self._on_row_double_clicked)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(10, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 145)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 80)
        self.table.setColumnWidth(3, 105)
        self.table.setColumnWidth(4, 75)
        self.table.setColumnWidth(5, 80)
        self.table.setColumnWidth(6, 125)
        self.table.setColumnWidth(7, 160)
        self.table.setColumnWidth(8, 95)
        self.table.setColumnWidth(9, 75)
        self.table.setColumnWidth(11, 130)

        root_layout.addWidget(self.table, 1)

        # ------------------------------------------------------------------
        # 6. PAGINACIÓN
        # ------------------------------------------------------------------
        pag_layout = QHBoxLayout()
        self.lbl_page_info = QLabel("Mostrando 0 registros")
        self.lbl_page_info.setStyleSheet("font-size: 12px; color: #475569;")
        pag_layout.addWidget(self.lbl_page_info)
        pag_layout.addStretch()

        self.btn_prev = QPushButton("◀ Anterior")
        self.btn_prev.setEnabled(False)
        self.btn_prev.clicked.connect(lambda: self._change_page(-1))

        self.lbl_page_num = QLabel("Página 1 de 1")
        self.lbl_page_num.setStyleSheet("font-weight: bold; font-size: 12px; padding: 0 8px;")

        self.btn_next = QPushButton("Siguiente ▶")
        self.btn_next.setEnabled(False)
        self.btn_next.clicked.connect(lambda: self._change_page(1))

        pag_layout.addWidget(self.btn_prev)
        pag_layout.addWidget(self.lbl_page_num)
        pag_layout.addWidget(self.btn_next)
        root_layout.addLayout(pag_layout)

    def _make_kpi_card(self, title, value, fg_color, bg_color):
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background-color: {bg_color}; border: 1px solid #cbd5e1; border-radius: 8px; }}"
        )
        vbox = QVBoxLayout(frame)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(2)

        lbl_t = QLabel(title)
        lbl_t.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {fg_color}; border: none;")
        lbl_v = QLabel(value)
        lbl_v.setStyleSheet(f"font-size: 22px; font-weight: bold; color: {fg_color}; border: none;")
        vbox.addWidget(lbl_t)
        vbox.addWidget(lbl_v)
        return {"frame": frame, "value_label": lbl_v}

    def _setup_timers(self):
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(500)
        self.poll_timer.timeout.connect(self._poll_progress)
        self.poll_timer.start()

        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)
        self.search_timer.timeout.connect(self._execute_search)

    # ------------------------------------------------------------------
    # ACCIONES Y EVENTOS
    # ------------------------------------------------------------------
    def _check_db_status(self):
        ok, msg = connection.test_connection()
        if ok:
            self.lbl_db_status.setText(f"MySQL: Conectado ({settings.DB_NAME})")
            self.lbl_db_status.setStyleSheet(
                "background-color: #dcfce7; color: #166534; border: 1px solid #86efac; "
                "padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: bold;"
            )
        else:
            self.lbl_db_status.setText("MySQL: Desconectado")
            self.lbl_db_status.setStyleSheet(
                "background-color: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; "
                "padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: bold;"
            )

    def _browse_directory(self):
        start_dir = self.txt_directory.text().strip()
        if not os.path.exists(start_dir):
            start_dir = os.path.expanduser("~")
        selected = QFileDialog.getExistingDirectory(self, "Seleccionar Directorio de PDFs", start_dir)
        if selected:
            self.txt_directory.setText(os.path.normpath(selected))

    def _start_scan(self):
        directory = self.txt_directory.text().strip()
        if not directory or not os.path.exists(directory):
            QMessageBox.warning(
                self,
                "Directorio Inválido",
                f"La ruta especificada no existe o no es accesible:\n{directory}"
            )
            return

        limit = self.cmb_limit.currentData()
        recursive = self.chk_recursive.isChecked()

        ok, msg = auditor_instance.start_audit(directory=directory, recursive=recursive, limit=limit)
        if not ok:
            QMessageBox.warning(self, "Aviso", msg)
        else:
            self.was_running = True
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.progress_bar.setValue(0)
            self.lbl_progress_info.setText("Iniciando escaneo...")

    def _stop_scan(self):
        auditor_instance.stop()

    def _poll_progress(self):
        try:
            prog = auditor_instance.get_progress()
            status = prog["status"]

            if status == "RUNNING":
                self.was_running = True
                self.btn_start.setEnabled(False)
                self.btn_retry_errors.setEnabled(False)
                self.btn_stop.setEnabled(True)
                self.progress_bar.setValue(int(prog["progress_pct"]))
                self.lbl_progress_info.setText(
                    f"{prog['processed_files']}/{prog['total_files']} | "
                    f"{prog['rate_docs_per_sec']} docs/s | {prog['current_file']}"
                )
                # Actualizar KPIs en memoria sin saturar MySQL durante el escaneo
                proc = int(prog["processed_files"])
                disc = int(prog["discrepancy_files"])
                tasa = round((disc / proc * 100), 2) if proc > 0 else 0.0
                self.kpi_total["value_label"].setText(f"{proc:,}")
                self.kpi_correctos["value_label"].setText(f"{int(prog['correct_files']):,}")
                self.kpi_discrepancias["value_label"].setText(f"{disc:,}")
                self.kpi_errores["value_label"].setText(f"{int(prog['error_files']):,}")
                self.kpi_tasa["value_label"].setText(f"{tasa}%")
            else:
                self.btn_start.setEnabled(True)
                self.btn_retry_errors.setEnabled(True)
                self.btn_stop.setEnabled(False)
                if self.was_running:
                    self.was_running = False
                    self.progress_bar.setValue(100 if status == "COMPLETED" else int(prog["progress_pct"]))
                    self.lbl_progress_info.setText(
                        f"Finalizado ({prog['processed_files']}/{prog['total_files']}) en {prog['elapsed_seconds']}s"
                    )
                    self._refresh_all()
        except Exception:
            pass

    def _load_summary(self):
        try:
            s = db_manager.get_audit_summary()
            self.kpi_total["value_label"].setText(f"{int(s.get('total') or 0):,}")
            self.kpi_correctos["value_label"].setText(f"{int(s.get('correctos') or 0):,}")
            self.kpi_discrepancias["value_label"].setText(f"{int(s.get('discrepancias') or 0):,}")
            self.kpi_colisiones["value_label"].setText(f"{int(s.get('colisiones') or 0):,}")
            self.kpi_errores["value_label"].setText(f"{int(s.get('errores') or 0):,}")
            self.kpi_tasa["value_label"].setText(f"{float(s.get('tasa_discrepancia_pct') or 0.0)}%")
        except Exception:
            pass

    def _load_table_data(self):
        try:
            filters = {}
            if self.current_filter != "TODOS":
                filters["estado"] = self.current_filter
            if self.search_query:
                filters["search"] = self.search_query

            data = db_manager.get_audit_results(
                filters=filters,
                page=self.current_page,
                page_size=self.page_size
            )
            self.total_pages = data["total_pages"]
            self._populate_table(data["items"])

            start = (data["page"] - 1) * data["page_size"] + (1 if data["items"] else 0)
            end = min(data["page"] * data["page_size"], data["total"])
            self.lbl_page_info.setText(f"Mostrando {start} - {end} de {data['total']} registros")
            self.lbl_page_num.setText(f"Página {data['page']} de {data['total_pages']}")
            self.btn_prev.setEnabled(data["page"] > 1)
            self.btn_next.setEnabled(data["page"] < data["total_pages"])
        except Exception as e:
            self.lbl_page_info.setText(f"Error consultando MySQL: {e}")

    def _populate_table(self, items):
        self.table.setRowCount(0)
        bold_font = QFont()
        bold_font.setBold(True)

        for row_idx, doc in enumerate(items):
            self.table.insertRow(row_idx)
            self.table.setRowHeight(row_idx, 34)

            estado = doc["estado"]
            item_estado = QTableWidgetItem(estado)
            item_estado.setFont(bold_font)
            item_estado.setData(Qt.UserRole, doc["id"])

            if estado == "CORRECTO":
                item_estado.setForeground(QColor("#166534"))
                item_estado.setBackground(QColor("#dcfce7"))
            elif "DISCREPANCIA" in estado:
                item_estado.setForeground(QColor("#b45309"))
                item_estado.setBackground(QColor("#fef3c7"))
            else:
                item_estado.setForeground(QColor("#991b1b"))
                item_estado.setBackground(QColor("#fee2e2"))

            self.table.setItem(row_idx, 0, item_estado)
            self.table.setItem(row_idx, 1, QTableWidgetItem(doc["nombre_archivo"]))

            it_actual = QTableWidgetItem(str(doc.get("registro_actual") or "-"))
            it_actual.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 2, it_actual)

            it_enc = QTableWidgetItem(str(doc.get("registro_encabezado") or "-"))
            it_enc.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 3, it_enc)

            it_pie = QTableWidgetItem(str(doc.get("registro_pie") or "-"))
            it_pie.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 4, it_pie)

            doble = "SÍ" if doc.get("coincide_encabezado_pie") else "NO"
            it_doble = QTableWidgetItem(doble)
            it_doble.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 5, it_doble)

            it_ant = QTableWidgetItem(str(doc.get("registro_antecedente") or "-"))
            it_ant.setTextAlignment(Qt.AlignCenter)
            if doc.get("registro_antecedente"):
                it_ant.setForeground(QColor("#b91c1c"))
                it_ant.setFont(bold_font)
            self.table.setItem(row_idx, 6, it_ant)

            it_prop = QTableWidgetItem(str(doc.get("nombre_propuesto") or "-"))
            if doc.get("nombre_propuesto"):
                it_prop.setForeground(QColor("#047857"))
                it_prop.setFont(bold_font)
            self.table.setItem(row_idx, 7, it_prop)

            choca = bool(doc.get("colision_bd"))
            it_col = QTableWidgetItem("SÍ (CHOCA)" if choca else ("NO" if doc.get("nombre_propuesto") else "-"))
            it_col.setTextAlignment(Qt.AlignCenter)
            if choca:
                it_col.setForeground(QColor("#991b1b"))
                it_col.setBackground(QColor("#fee2e2"))
                it_col.setFont(bold_font)
            self.table.setItem(row_idx, 8, it_col)

            it_conf = QTableWidgetItem(f"{doc.get('confianza_score', 0)}%")
            it_conf.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 9, it_conf)

            motivo = doc.get("motivo_discrepancia") or "-"
            it_mot = QTableWidgetItem(motivo)
            it_mot.setToolTip(motivo)
            self.table.setItem(row_idx, 10, it_mot)

            # Botones de acción en celda (solo auditoría: Ver y Reintentar errores)
            actions_widget = QWidget()
            act_layout = QHBoxLayout(actions_widget)
            act_layout.setContentsMargins(4, 2, 4, 2)
            act_layout.setSpacing(4)

            btn_view = QPushButton("Ver")
            btn_view.setCursor(Qt.PointingHandCursor)
            btn_view.setStyleSheet(
                "QPushButton { background-color: #2563eb; color: white; border-radius: 4px; padding: 2px 8px; font-size: 11px; }"
            )
            btn_view.clicked.connect(lambda checked, did=doc["id"]: self._open_preview(did))
            act_layout.addWidget(btn_view)

            if estado in ("ERROR_LECTURA", "NOMBRE_INVALIDO"):
                btn_ret = QPushButton("Reintentar")
                btn_ret.setCursor(Qt.PointingHandCursor)
                btn_ret.setStyleSheet(
                    "QPushButton { background-color: #d97706; color: white; border-radius: 4px; padding: 2px 8px; font-size: 11px; }"
                )
                btn_ret.clicked.connect(lambda checked, did=doc["id"]: self._retry_single(did))
                act_layout.addWidget(btn_ret)

            self.table.setCellWidget(row_idx, 11, actions_widget)

    def _set_filter(self, key):
        self.current_filter = key
        self.current_page = 1
        self._update_filter_buttons_style()
        self._load_table_data()

    def _update_filter_buttons_style(self):
        for key, btn in self.filter_buttons.items():
            active = (key == self.current_filter)
            btn.setChecked(active)
            if active:
                btn.setStyleSheet(
                    "QPushButton { background-color: #2563eb; color: white; font-weight: bold; "
                    "border-radius: 5px; padding: 4px 12px; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { background-color: #e2e8f0; color: #334155; "
                    "border-radius: 5px; padding: 4px 12px; }"
                )

    def _on_search_changed(self):
        self.search_timer.start()

    def _execute_search(self):
        self.search_query = self.txt_search.text().strip()
        self.current_page = 1
        self._load_table_data()

    def _change_page(self, delta):
        self.current_page = max(1, min(self.total_pages, self.current_page + delta))
        self._load_table_data()

    def _on_row_double_clicked(self, row, col):
        item = self.table.item(row, 0)
        if item:
            doc_id = item.data(Qt.UserRole)
            if doc_id:
                self._open_preview(doc_id)

    def _open_preview(self, doc_id):
        dlg = PreviewDialog(doc_id, parent=self)
        dlg.exec()

    def _open_db_dialog(self):
        dlg = DbToolsDialog(parent=self, on_db_changed=self._refresh_all)
        dlg.exec()

    def _export_excel(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar Reporte Excel", "reporte_auditoria_ocr.xlsx", "Excel (*.xlsx)"
        )
        if not path:
            return
        try:
            count = db_manager.export_results_to_excel(path, estado=self.current_filter)
            QMessageBox.information(self, "Exportación Exitosa", f"Se exportaron {count} registros a:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error de Exportación", str(e))

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar Reporte CSV", "reporte_auditoria_ocr.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            count = db_manager.export_results_to_csv(path, estado=self.current_filter)
            QMessageBox.information(self, "Exportación Exitosa", f"Se exportaron {count} registros a:\n{path}")
        except Exception as e:
            QMessageBox.critical(self, "Error de Exportación", str(e))

    def _retry_all_errors(self):
        ok, msg = auditor_instance.start_retry_errors()
        if not ok:
            QMessageBox.information(self, "Reintento de Errores", msg)
        else:
            self.was_running = True
            self.btn_start.setEnabled(False)
            self.btn_retry_errors.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.progress_bar.setValue(0)
            self.lbl_progress_info.setText(msg)

    def _retry_single(self, doc_id):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, msg, _ = auditor_instance.retry_single_document(doc_id)
        finally:
            QApplication.restoreOverrideCursor()

        if ok:
            QMessageBox.information(self, "Reintento Exitoso", msg)
            self._refresh_all()
        else:
            QMessageBox.warning(self, "Error en Reintento", msg)

    def _refresh_all(self):
        self._check_db_status()
        self._load_summary()
        self._load_table_data()
