"""Merge LAS Files task dialog (spec §2.6)."""
import pandas as pd
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHeaderView, QLabel, QTableView, QVBoxLayout,
)

from themes.icon_loader import get_icon

from .table_model import PandasTableModel

_COLUMNS = ["File", "Rows", "Top (ft)", "Bottom (ft)"]


class MergeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MergeDialog")
        self.setWindowTitle("Merge LAS Files")
        self.setModal(True)
        self.resize(560, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("PlaceholderLabel")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        self.file_model = PandasTableModel(pd.DataFrame(columns=_COLUMNS), float_decimals=1)
        self.file_table = QTableView()
        self.file_table.setModel(self.file_model)
        self.file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.file_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.file_table.verticalHeader().setVisible(False)
        self.file_table.horizontalHeader().setStretchLastSection(True)
        self.file_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.file_table, 1)

        form = QFormLayout()
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.1, 1.0)
        self.step_spin.setValue(0.5)
        self.step_spin.setSingleStep(0.1)
        self.gap_spin = QDoubleSpinBox()
        self.gap_spin.setRange(1.0, 50.0)
        self.gap_spin.setValue(5.0)
        self.gap_spin.setSingleStep(1.0)
        form.addRow("Step (ft)", self.step_spin)
        form.addRow("Gap limit", self.gap_spin)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setText("Merge")
        ok_button.setIcon(get_icon("merge"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.set_files([])

    def set_files(self, rows: list):
        """rows: (name, row count, top, bottom) per pending file."""
        frame = pd.DataFrame(
            [(name, n, float(top), float(bottom)) for name, n, top, bottom in rows],
            columns=_COLUMNS,
        )
        self.file_model.set_dataframe(frame)
        self.summary_label.setText(
            f"{len(rows)} LAS files selected. They are resampled to one depth step "
            "and joined into a single well dataset."
        )

    def update_model(self, model):
        model.merge_step = self.step_spin.value()
        model.merge_gap_limit = self.gap_spin.value()
