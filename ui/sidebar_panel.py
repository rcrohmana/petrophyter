"""
Sidebar Panel for Petrophyter PyQt
Left panel with file upload and parameter controls.
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QFrame,
    QLabel,
    QPushButton,
    QGroupBox,
    QFileDialog,
    QMessageBox,
    QComboBox,
    QDoubleSpinBox,
    QProgressBar,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
import os
from themes.colors import get_color


class SidebarPanel(QWidget):
    """
    Left sidebar panel with file upload and parameter controls.
    Replaces Streamlit's st.sidebar.
    """

    # Signals
    merge_requested = pyqtSignal()
    download_merged_clicked = pyqtSignal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._progress_cb = None
        self.setMinimumWidth(340)  # Slightly wider for better readability
        self.setMaximumWidth(420)  # Increased max width
        self._setup_ui()

    def _setup_ui(self):
        """Setup the sidebar UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # Content widget
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(10)

        # =====================================================================
        # DATA INPUT SECTION
        # =====================================================================
        self._create_data_input_section()

        # =====================================================================
        # FORMATION TOPS SECTION
        # =====================================================================
        self._create_formation_tops_section()

        # =====================================================================
        # CORE DATA SECTION
        # =====================================================================
        self._create_core_data_section()

        # Push remaining space to top
        self.content_layout.addStretch()

        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def _create_data_input_section(self):
        """Create the data input section."""
        group = QGroupBox("📁 Data Input")
        layout = QVBoxLayout(group)

        # LAS file upload button
        self.las_btn = QPushButton("📂 Open LAS File(s)...")
        layout.addWidget(self.las_btn)

        # File info label
        self.las_info_label = QLabel("")
        self.las_info_label.setWordWrap(True)
        self.las_info_label.setStyleSheet(
            f"color: {get_color('text_secondary')}; background-color: transparent;"
        )
        layout.addWidget(self.las_info_label)

        # Merge controls (hidden by default)
        self.merge_frame = QFrame()
        merge_layout = QVBoxLayout(self.merge_frame)

        merge_layout.addWidget(QLabel("🔗 Multi-LAS Merge"))

        # Merge settings
        settings_layout = QHBoxLayout()
        settings_layout.addWidget(QLabel("Step (ft):"))
        self.merge_step_spin = QDoubleSpinBox()
        self.merge_step_spin.setRange(0.1, 1.0)
        self.merge_step_spin.setValue(0.5)
        self.merge_step_spin.setSingleStep(0.1)
        settings_layout.addWidget(self.merge_step_spin)

        settings_layout.addWidget(QLabel("Gap Limit:"))
        self.merge_gap_spin = QDoubleSpinBox()
        self.merge_gap_spin.setRange(1.0, 50.0)
        self.merge_gap_spin.setValue(5.0)
        self.merge_gap_spin.setSingleStep(1.0)
        settings_layout.addWidget(self.merge_gap_spin)
        merge_layout.addLayout(settings_layout)

        self.merge_btn = QPushButton("🔄 Merge LAS Files")
        self.merge_btn.setStyleSheet(
            f"background-color: {get_color('success')}; color: white;"
        )
        self.merge_btn.clicked.connect(self.merge_requested.emit)
        merge_layout.addWidget(self.merge_btn)

        self.download_merged_btn = QPushButton("📥 Download Merged LAS")
        self.download_merged_btn.clicked.connect(self.download_merged_clicked.emit)
        self.download_merged_btn.setVisible(False)
        merge_layout.addWidget(self.download_merged_btn)

        self.merge_frame.setVisible(False)
        layout.addWidget(self.merge_frame)

        self.content_layout.addWidget(group)

    def _create_formation_tops_section(self):
        """Create formation tops section."""
        group = QGroupBox("📋 Formation Tops")
        layout = QVBoxLayout(group)

        self.tops_btn = QPushButton("📂 Open Formation Tops...")
        layout.addWidget(self.tops_btn)

        self.tops_info_label = QLabel("")
        self.tops_info_label.setStyleSheet("color: green;")
        layout.addWidget(self.tops_info_label)

        self.content_layout.addWidget(group)

    def _create_core_data_section(self):
        """Create core data section."""
        group = QGroupBox("🔬 Core Data (Optional)")
        layout = QVBoxLayout(group)

        self.core_btn = QPushButton("📂 Open Core Data...")
        layout.addWidget(self.core_btn)

        self.core_info_label = QLabel("")
        self.core_info_label.setStyleSheet("color: green;")
        layout.addWidget(self.core_info_label)

        self.content_layout.addWidget(group)

    def set_open_callbacks(self, open_las, open_tops, open_core):
        """Wire the Open buttons to MainWindow's file dialogs."""
        self.las_btn.clicked.connect(open_las)
        self.tops_btn.clicked.connect(open_tops)
        self.core_btn.clicked.connect(open_core)

    # =========================================================================
    # PUBLIC METHODS
    # =========================================================================

    def update_las_info(
        self, filename: str, rows: int, curves: int, is_merged: bool = False
    ):
        """Update LAS file info display."""
        if is_merged:
            self.las_info_label.setText(f"✅ Merged: {rows:,} rows, {curves} curves")
            self.las_info_label.setStyleSheet(f"color: {get_color('success')};")
            self.download_merged_btn.setVisible(True)
        else:
            self.las_info_label.setText(
                f"✅ Loaded: {os.path.basename(filename)}\n📊 {rows:,} rows, {curves} curves"
            )
            self.las_info_label.setStyleSheet(f"color: {get_color('success')};")

    def update_multiple_files_info(self, count: int):
        """Show multiple files selected info."""
        self.las_info_label.setText(f"📁 {count} files selected")
        self.las_info_label.setStyleSheet(f"color: {get_color('primary')};")
        self.merge_frame.setVisible(True)

    def update_tops_info(self, count: int):
        """Update formation tops info."""
        self.tops_info_label.setText(f"✅ Loaded {count} formations")

    def update_core_info(self, count: int, unit: str, por_converted: bool = False):
        """Update core data info."""
        msg = f"✅ Loaded {count} samples ({unit})"
        if por_converted:
            msg += "\nℹ️ Porosity auto-converted % → fraction"
        self.core_info_label.setText(msg)

    def set_progress(self, value: int, message: str = None):
        """Forward progress to the callback set by MainWindow (status bar)."""
        if self._progress_cb is not None:
            self._progress_cb(value, message)

    def update_model_from_ui(self):
        """Update model from sidebar-held values (merge settings)."""
        self.model.merge_step = self.merge_step_spin.value()
        self.model.merge_gap_limit = self.merge_gap_spin.value()

    def reset_ui(self):
        """Reset sidebar UI to fresh/initial state."""
        # Reset LAS info
        self.las_info_label.setText("")
        self.las_info_label.setStyleSheet(
            f"color: {get_color('text_secondary')}; background-color: transparent;"
        )

        # Hide merge controls
        self.merge_frame.setVisible(False)
        self.download_merged_btn.setVisible(False)

        # Reset formation tops info
        self.tops_info_label.setText("")

        # Reset core data info
        self.core_info_label.setText("")


    def refresh_theme(self):
        """Refresh widget styling when theme changes."""
        # Refresh info labels/help color
        self.las_info_label.setStyleSheet(
            f"color: {get_color('text_secondary')}; background-color: transparent;"
        )
