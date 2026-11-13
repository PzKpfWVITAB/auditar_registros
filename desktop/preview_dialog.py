import os
import io
import json
from PIL import ImageDraw
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QMessageBox, QApplication
)
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtCore import Qt

from core.document_analyzer import extract_page_image
from database import db_manager


class PreviewDialog(QDialog):
    """
    Formulario modal de Inspección Visual: muestra la página 1 del PDF con
    recuadros de colores sobre las zonas detectadas por OCR y el diagnóstico completo.
    """

    def __init__(self, doc_id: int, parent=None, on_renamed=None):
        super().__init__(parent)
        self.doc_id = doc_id
        self.on_renamed = on_renamed
        self.doc = db_manager.get_document_by_id(doc_id)
        self.base_pixmap = None
        self.zoom_factor = 1.0

        self.setWindowTitle("Inspección Visual de Documento - Auditoría OCR")
        self.resize(1100, 760)
        self.setModal(True)

        self._init_ui()
        self._load_document_data()

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(14)

        # Panel Izquierdo: Visor de Imagen + Controles de Zoom
        left_layout = QVBoxLayout()
        toolbar = QHBoxLayout()

        self.lbl_file_title = QLabel("Cargando...")
        self.lbl_file_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #0f172a;")
        toolbar.addWidget(self.lbl_file_title, 1)

        btn_zoom_out = QPushButton(" - ")
        btn_zoom_out.setFixedWidth(36)
        btn_zoom_out.clicked.connect(lambda: self._adjust_zoom(0.85))

        btn_zoom_fit = QPushButton("Ajustar")
        btn_zoom_fit.clicked.connect(self._fit_image)

        btn_zoom_in = QPushButton(" + ")
        btn_zoom_in.setFixedWidth(36)
        btn_zoom_in.clicked.connect(lambda: self._adjust_zoom(1.15))

        toolbar.addWidget(btn_zoom_out)
        toolbar.addWidget(btn_zoom_fit)
        toolbar.addWidget(btn_zoom_in)
        left_layout.addLayout(toolbar)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setStyleSheet("background-color: #1e293b; border-radius: 8px;")

        self.image_label = QLabel("Generando vista previa...")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("color: #cbd5e1;")
        self.scroll_area.setWidget(self.image_label)

        left_layout.addWidget(self.scroll_area, 1)
        main_layout.addLayout(left_layout, 7)

        # Panel Derecho: Leyenda, Metadatos y Acciones
        right_frame = QFrame()
        right_frame.setFixedWidth(340)
        right_frame.setStyleSheet(
            "QFrame { background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; }"
        )
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)

        lbl_sec1 = QLabel("ZONAS DETECTADAS POR OCR")
        lbl_sec1.setStyleSheet("font-weight: bold; font-size: 11px; color: #64748b; border: none;")
        right_layout.addWidget(lbl_sec1)

        self.lbl_header_box = self._make_legend_box("#dcfce7", "#166534", "#22c55e", "Verde - Encabezado: --")
        self.lbl_footer_box = self._make_legend_box("#dbeafe", "#1e40af", "#3b82f6", "Azul - Pie de Página: --")
        self.lbl_del_box = self._make_legend_box("#f3e8ff", "#6b21a8", "#9333ea", "Morado - Delegación: --")
        self.lbl_ant_box = self._make_legend_box("#fee2e2", "#991b1b", "#ef4444", "Rojo - Antecedente (Trampa): --")

        right_layout.addWidget(self.lbl_header_box)
        right_layout.addWidget(self.lbl_footer_box)
        right_layout.addWidget(self.lbl_del_box)
        right_layout.addWidget(self.lbl_ant_box)

        lbl_sec2 = QLabel("DIAGNÓSTICO DEL AUDITOR")
        lbl_sec2.setStyleSheet("font-weight: bold; font-size: 11px; color: #64748b; border: none; margin-top: 6px;")
        right_layout.addWidget(lbl_sec2)

        self.lbl_motivo = QLabel("--")
        self.lbl_motivo.setWordWrap(True)
        self.lbl_motivo.setStyleSheet(
            "background-color: white; border: 1px solid #e2e8f0; border-radius: 6px; "
            "padding: 10px; font-size: 12px; color: #334155;"
        )
        right_layout.addWidget(self.lbl_motivo)

        lbl_sec3 = QLabel("COMPARATIVA")
        lbl_sec3.setStyleSheet("font-weight: bold; font-size: 11px; color: #64748b; border: none; margin-top: 6px;")
        right_layout.addWidget(lbl_sec3)

        self.lbl_comparativa = QLabel("--")
        self.lbl_comparativa.setWordWrap(True)
        self.lbl_comparativa.setStyleSheet("font-size: 12px; color: #1e293b; border: none;")
        right_layout.addWidget(self.lbl_comparativa)

        right_layout.addStretch()

        self.btn_copy = QPushButton("Copiar Nombre Propuesto")
        self.btn_copy.setMinimumHeight(34)
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.clicked.connect(self._copy_proposed)
        right_layout.addWidget(self.btn_copy)

        btn_close = QPushButton("Cerrar")
        btn_close.setMinimumHeight(34)
        btn_close.clicked.connect(self.accept)
        right_layout.addWidget(btn_close)

        main_layout.addWidget(right_frame)

    def _make_legend_box(self, bg, fg, border, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border: 1px solid {border}; "
            f"border-radius: 6px; padding: 8px; font-size: 12px; font-weight: bold;"
        )
        return lbl

    def _load_document_data(self):
        if not self.doc:
            self.image_label.setText("Documento no encontrado en base de datos.")
            self.btn_copy.setEnabled(False)
            return

        self.lbl_file_title.setText(f"Archivo: {self.doc['nombre_archivo']}")
        self.lbl_header_box.setText(f"Verde - Encabezado: {self.doc.get('registro_encabezado') or 'No detectado'}")
        self.lbl_footer_box.setText(f"Azul - Pie de Página: {self.doc.get('registro_pie') or 'No detectado'}")
        
        del_det = self.doc.get("municipio_detectado")
        del_clave = self.doc.get("delegacion_detectada_clave")
        del_text = f"{del_clave} - {del_det}" if del_det else "No detectada"
        self.lbl_del_box.setText(f"Morado - Delegación: {del_text}")
        
        self.lbl_ant_box.setText(f"Rojo - Antecedente (Trampa): {self.doc.get('registro_antecedente') or 'Ninguno'}")
        self.lbl_motivo.setText(self.doc.get("motivo_discrepancia") or "Sin observaciones.")

        propuesto = self.doc.get("nombre_propuesto") or "N/A"
        choca_html = (
            "<span style='color:#b91c1c; font-weight:bold;'>SÍ (Ya existe en registros_existentes)</span>"
            if self.doc.get("colision_bd")
            else "<span style='color:#166534;'>NO</span>"
        )
        
        del_coin = self.doc.get("delegacion_coincide")
        del_coin_html = (
            "<span style='color:#166534; font-weight:bold;'>SÍ</span>" if del_coin == 1
            else ("<span style='color:#b91c1c; font-weight:bold;'>NO (Discrepancia)</span>" if del_coin == 0
            else "<span style='color:#64748b;'>No detectada</span>")
        )

        self.lbl_comparativa.setText(
            f"<b>Nombre Actual:</b> {self.doc['nombre_archivo']}<br>"
            f"<b>Delegación Archivo:</b> {self.doc.get('delegacion_archivo_nombre') or self.doc.get('delegacion_actual') or '-'}<br>"
            f"<b>Municipio Detectado:</b> {del_det or '-'}<br>"
            f"<b>Del. Coincide:</b> {del_coin_html} ({self.doc.get('confianza_delegacion', 0)}%)<br>"
            f"<b>Nombre Propuesto:</b> <span style='color:#059669;'>{propuesto}</span><br>"
            f"<b>Choca en BD:</b> {choca_html}<br>"
            f"<b>Año Detectado:</b> {self.doc.get('anio_detectado') or '-'}<br>"
            f"<b>Confianza OCR Reg:</b> {self.doc.get('confianza_score', 0)}%"
        )

        self.btn_copy.setEnabled(bool(self.doc.get("nombre_propuesto")))

        self._render_preview_image()

    def _render_preview_image(self):
        file_path = self.doc.get("ruta_completa", "")
        if not os.path.exists(file_path):
            self.image_label.setText(f"El archivo físico no existe en:\n{file_path}")
            return

        try:
            img = extract_page_image(file_path, page_number=0, dpi=150).convert("RGB")
            draw = ImageDraw.Draw(img)

            boxes_raw = self.doc.get("bounding_boxes_json")
            boxes = json.loads(boxes_raw) if boxes_raw else {}

            for key, box in boxes.items():
                x, y, w, h = box["x"], box["y"], box["w"], box["h"]
                color = box.get("color", "#10b981")
                label = box.get("label", key)

                for offset in range(3):
                    draw.rectangle([x - offset, y - offset, x + w + offset, y + h + offset], outline=color)

                draw.rectangle([x, max(0, y - 20), x + max(130, len(label) * 8), y], fill=color)
                draw.text((x + 4, max(0, y - 18)), label, fill="#ffffff")

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            qimg = QImage.fromData(buf.getvalue())
            self.base_pixmap = QPixmap.fromImage(qimg)
            self._fit_image()
        except Exception as e:
            self.image_label.setText(f"Error renderizando vista previa:\n{e}")

    def _fit_image(self):
        if not self.base_pixmap:
            return
        avail_w = max(400, self.scroll_area.viewport().width() - 20)
        scaled = self.base_pixmap.scaledToWidth(avail_w, Qt.SmoothTransformation)
        self.zoom_factor = avail_w / max(1, self.base_pixmap.width())
        self.image_label.setPixmap(scaled)

    def _adjust_zoom(self, factor):
        if not self.base_pixmap:
            return
        self.zoom_factor = max(0.3, min(3.0, self.zoom_factor * factor))
        new_w = int(self.base_pixmap.width() * self.zoom_factor)
        scaled = self.base_pixmap.scaledToWidth(new_w, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)

    def _copy_proposed(self):
        prop = self.doc.get("nombre_propuesto")
        if prop:
            QApplication.clipboard().setText(prop)
            QMessageBox.information(self, "Copiado", f"Nombre copiado al portapapeles:\n{prop}")
