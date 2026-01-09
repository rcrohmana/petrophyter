from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QFrame,
    QScrollArea,
    QWidget,
    QTextEdit,
    QApplication,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QPixmap, QFont
import os


class AboutDialog(QDialog):
    """
    Dialog to display information about the software.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About Petrophyter")
        self.setMinimumSize(600, 500)
        self.setModal(True)

        # Setup layout
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Header Section (Logo & Title) ---
        header = QFrame()
        header.setStyleSheet(
            "background-color: #E0DBD1; border-bottom: 1px solid #C9C0B0;"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 20, 20, 20)

        # Logo (if available, otherwise just use text)
        icon_label = QLabel()
        # Try to find the icon
        icon_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "icons",
            "app_icon.svg",
        )
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                icon_label.setPixmap(
                    pixmap.scaled(
                        64,
                        64,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )

        # Title Text
        title_container = QWidget()
        title_layout = QVBoxLayout(title_container)
        title_layout.setSpacing(5)
        title_layout.setContentsMargins(10, 0, 0, 0)

        app_title = QLabel("Petrophyter")
        app_title.setStyleSheet("font-size: 24px; font-weight: bold; color: #1E88E5;")

        app_subtitle = QLabel("Petrophysics Master - v1.3.0 (Build 20260109)")
        app_subtitle.setStyleSheet("font-size: 14px; font-weight: bold; color: #555;")

        title_layout.addWidget(app_title)
        title_layout.addWidget(app_subtitle)

        header_layout.addWidget(icon_label)
        header_layout.addWidget(title_container)
        header_layout.addStretch()

        layout.addWidget(header)

        # --- Content Section ---
        content_area = QScrollArea()
        content_area.setWidgetResizable(True)
        content_area.setFrameShape(QFrame.Shape.NoFrame)
        content_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content_area.setStyleSheet("background-color: transparent;")

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(30, 10, 30, 20)
        content_layout.setSpacing(15)

        # 1. History Info (paling atas)
        history_group = self._create_info_section("History & Development")
        history_text = (
            "<p style='margin-bottom: 8px;'><b>Version History:</b></p>"
            "<p style='margin: 0 0 8px 0;'><b>v1.3.0 (Build 20260109) - Current Release</b></p>"
            "<ul style='margin: 0 0 10px 20px; padding: 0;'>"
            "<li>New Project button to reset application state</li>"
            "<li>Porosity Method selector in sidebar (choose primary PHIE)</li>"
            "<li>Sw histogram overlay with density mode</li>"
            "</ul>"
            "<p style='margin: 0 0 8px 0;'><b>v1.2 (Build 20260106)</b></p>"
            "<ul style='margin: 0 0 10px 20px; padding: 0;'>"
            "<li>HCPV calculation with multiple display modes</li>"
            "<li>Waxman-Smits and Dual-Water saturation models</li>"
            "<li>PyQtGraph OpenGL GPU acceleration (~30 FPS throttling)</li>"
            "</ul>"
            "<p style='margin: 0 0 8px 0;'><b>v1.1 (Dec 30, 2025)</b></p>"
            "<ul style='margin: 0 0 10px 20px; padding: 0;'>"
            "<li>Interactive Log Display (PyQtGraph, 6-track composite)</li>"
            "<li>Session Save/Load (JSON), Gas Correction for PHIE</li>"
            "<li>Async background calculations, Unit tests foundation</li>"
            "</ul>"
            "<p style='margin: 0 0 8px 0;'><b>v1.0 Final (Dec 23, 2025) - Initial Release</b></p>"
            "<ul style='margin: 0 0 10px 20px; padding: 0;'>"
            "<li>LAS file loading, Multi-LAS merging with quality scoring</li>"
            "<li>VShale (4 methods), Porosity (4 methods), Sw (Archie, Indonesian, Simandoux)</li>"
            "<li>Permeability (Timur, Wyllie-Rose), Net Pay Analysis, QC with outlier detection</li>"
            "<li>Excel/CSV/LAS export, Classic Log Display (Matplotlib)</li>"
            "</ul>"
            "<p style='margin-top: 12px;'><b>Purpose:</b></p>"
            "<p>Academic software for teaching <i>Well Log Analysis</i> and <i>Formation Evaluation</i>, "
            "and research within the Petrophysics TAU Research Group. Built with scalability for future commercial use.</p>"
        )
        history_label = QLabel(history_text)
        history_label.setTextFormat(Qt.TextFormat.RichText)
        history_label.setWordWrap(True)
        history_label.setStyleSheet("font-size: 12px; line-height: 1.4;")
        history_group.layout().addWidget(history_label)
        content_layout.addWidget(history_group)

        # 2. Author Info (setelah history)
        author_group = self._create_info_section("Developed by:")
        author_text = (
            "<p><b>Rian Cahya Rohmana</b> — Petroleum Engineering, Tanri Abeng University "
            "(Petrophysics TAU Research Group)</p>"
        )
        author_label = QLabel(author_text)
        author_label.setTextFormat(Qt.TextFormat.RichText)
        author_label.setOpenExternalLinks(True)
        author_label.setWordWrap(True)
        author_label.setStyleSheet("font-size: 13px; line-height: 1.4;")
        author_group.layout().addWidget(author_label)
        content_layout.addWidget(author_group)

        # 3. Citation Info (paling akhir)
        citation_group = self._create_info_section("How to Cite")
        citation_text = (
            "Rohmana, R. C. (2026). Petrophyter: An Application for "
            "Petrophysical Analysis (Version 1.3). "
            "Petrophysics TAU Research Group, Petroleum Engineering, Tanri Abeng University."
        )
        citation_box = QTextEdit()
        citation_box.setPlainText(citation_text)
        citation_box.setReadOnly(True)
        citation_box.setFixedHeight(70)
        citation_box.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        citation_box.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        citation_box.setStyleSheet(
            "font-size: 12px; font-family: 'Consolas', monospace; "
            "background-color: #f5f5f5; border: 1px solid #ddd; padding: 8px;"
        )
        citation_group.layout().addWidget(citation_box)

        # Copy button
        copy_btn = QPushButton("📋 Copy Citation")
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard(citation_text))
        citation_group.layout().addWidget(copy_btn)
        content_layout.addWidget(citation_group)

        # 4. License Info (after citation)
        license_group = self._create_info_section("License")
        license_text = (
            "<p><b>This project is dual-licensed under your choice of:</b></p>"
            "<table style='border-collapse: collapse; margin: 10px 0; width: 100%;'>"
            "<thead>"
            "<tr style='background-color: #E0DBD1;'>"
            "<th style='padding: 8px; border: 1px solid #C9C0B0; text-align: left;'>License</th>"
            "<th style='padding: 8px; border: 1px solid #C9C0B0; text-align: left;'>File</th>"
            "<th style='padding: 8px; border: 1px solid #C9C0B0; text-align: left;'>Use Case</th>"
            "</tr>"
            "</thead>"
            "<tbody>"
            "<tr>"
            "<td style='padding: 8px; border: 1px solid #C9C0B0;'><b>Apache-2.0</b></td>"
            "<td style='padding: 8px; border: 1px solid #C9C0B0;'>LICENSE-APACHE-2.0</td>"
            "<td style='padding: 8px; border: 1px solid #C9C0B0;'>Permissive reuse of core modules</td>"
            "</tr>"
            "<tr>"
            "<td style='padding: 8px; border: 1px solid #C9C0B0;'><b>GPL-3.0</b></td>"
            "<td style='padding: 8px; border: 1px solid #C9C0B0;'>LICENSE-GPL-3.0</td>"
            "<td style='padding: 8px; border: 1px solid #C9C0B0;'>Full application with PyQt6</td>"
            "</tr>"
            "</tbody>"
            "</table>"
            "<p style='margin-top: 12px;'><b>Note:</b></p>"
            "<ul style='margin-top: 5px;'>"
            "<li>If you use the <b>core calculation modules only</b> (modules/petrophysics.py, etc.) without PyQt6 UI: "
            "You may use <b>Apache-2.0</b> (permissive, no copyleft).</li>"
            "<li>If you use the <b>complete application</b> (including PyQt6 UI): <b>GPL-3.0 applies</b> due to PyQt6's licensing terms.</li>"
            "<li>If you want to use PyQt6 without GPL: Purchase a commercial PyQt6 license.</li>"
            "</ul>"
            "<p style='margin-top: 12px;'><b>Third-Party Licenses:</b></p>"
            "<p>See <b>NOTICE</b> file for complete list of third-party components and their licenses.</p>"
        )
        license_label = QLabel(license_text)
        license_label.setTextFormat(Qt.TextFormat.RichText)
        license_label.setWordWrap(True)
        license_label.setStyleSheet("font-size: 13px; line-height: 1.4;")
        license_group.layout().addWidget(license_label)
        content_layout.addWidget(license_group)

        # Footer Note
        footer_label = QLabel(
            "<i>© 2024-2026 Rian Cahya Rohmana. All rights reserved.</i>"
        )
        footer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_label.setStyleSheet("color: #777; font-size: 11px; margin-top: 10px;")
        content_layout.addWidget(footer_label)

        content_layout.addStretch()
        content_area.setWidget(content_widget)
        layout.addWidget(content_area)

        # --- Bottom Button ---
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(20, 10, 20, 20)
        button_layout.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFixedWidth(100)
        close_btn.clicked.connect(self.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _create_info_section(self, title):
        """Helper to create a styled section group."""
        group = QFrame()
        group.setStyleSheet("""
            QFrame {
                background-color: #F0EBE1;
                border: 1px solid #C9C0B0;
                border-radius: 6px;
            }
        """)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(15, 15, 15, 15)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            "font-weight: bold; font-size: 14px; color: #333; margin-bottom: 5px;"
        )
        layout.addWidget(title_lbl)

        # Add a subtle separator line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("background-color: #D5CFC4; margin-bottom: 10px;")
        layout.addWidget(line)

        return group

    def _copy_to_clipboard(self, text: str):
        """Copy text to clipboard and show feedback."""
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        # Brief visual feedback could be added here if needed
