"""
Petrophysics Tab for Petrophyter PyQt
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QGroupBox,
    QTableView,
    QScrollArea,
    QSizePolicy,
    QDoubleSpinBox,
    QPushButton,
    QHeaderView,
    QComboBox,
)
from PyQt6.QtCore import Qt
import pandas as pd

from ..widgets.info_strip import InfoStrip
from ..widgets.plot_widget import HistogramPlot
from ..widgets.table_model import PandasTableModel
from ..widgets import track_specs as ts


class PetrophysicsTab(QWidget):
    """Petrophysics calculation results tab."""

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Scroll area (outer) - untuk scroll vertikal seluruh konten tab (seperti QC tab)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content_layout = QVBoxLayout(content)

        # =====================================================================
        # DATA-DRIVEN PARAMETERS
        # =====================================================================
        params_group = QGroupBox("Data-Driven Parameters")
        params_layout = QHBoxLayout(params_group)

        self.info_strip = InfoStrip()
        self.info_strip.add_block("gr_min", "GR min")
        self.info_strip.add_block("gr_max", "GR max")
        self.info_strip.add_block("rw", "Rw")
        self.info_strip.add_block("rsh", "Rsh")
        for key, text in (
            ("gr_min", "- API"),
            ("gr_max", "- API"),
            ("rw", "- Ω.m"),
            ("rsh", "- Ω.m"),
        ):
            self.info_strip.set_value(key, text)
        params_layout.addWidget(self.info_strip)

        content_layout.addWidget(params_group)

        # =====================================================================
        # RESULTS TABLE (simple like QC tab)
        # =====================================================================
        results_group = QGroupBox("Calculated Results Preview")
        results_layout = QVBoxLayout(results_group)

        # Filter controls
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Top MD:"))
        self.top_md_spin = QDoubleSpinBox()
        self.top_md_spin.setRange(0, 100000)
        self.top_md_spin.setDecimals(1)
        self.top_md_spin.setSuffix(" ft")
        filter_layout.addWidget(self.top_md_spin)

        filter_layout.addWidget(QLabel("Bottom MD:"))
        self.bottom_md_spin = QDoubleSpinBox()
        self.bottom_md_spin.setRange(0, 100000)
        self.bottom_md_spin.setDecimals(1)
        self.bottom_md_spin.setSuffix(" ft")
        filter_layout.addWidget(self.bottom_md_spin)

        self.update_table_btn = QPushButton("Update View")
        self.update_table_btn.clicked.connect(self._update_table_view)
        filter_layout.addWidget(self.update_table_btn)

        filter_layout.addStretch()
        results_layout.addLayout(filter_layout)

        # Simple table like QC tab
        self.results_table = QTableView()
        self.results_model = PandasTableModel()
        self.results_table.setModel(self.results_model)
        self.results_table.setMinimumHeight(350)
        self.results_table.setMaximumHeight(500)
        self.results_table.setAlternatingRowColors(True)

        # Enable horizontal scroll on table itself
        self.results_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.results_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        # Header settings
        header = self.results_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setDefaultSectionSize(90)
        header.setMinimumSectionSize(70)

        results_layout.addWidget(self.results_table)
        content_layout.addWidget(results_group)

        # =====================================================================
        # PROPERTY DISTRIBUTIONS (2 rows x 2 cols)
        # =====================================================================
        dist_group = QGroupBox("Property Distributions")
        dist_group.setMinimumHeight(500)
        dist_layout = QGridLayout(dist_group)

        self.vsh_hist = HistogramPlot()
        self.phie_hist = HistogramPlot()
        self.sw_hist = HistogramPlot()
        self.perm_hist = HistogramPlot()

        # Method selectors for the Sw and permeability histograms
        self.sw_method_combo = QComboBox()
        self.sw_method_combo.setToolTip("Water saturation curve shown in the histogram")
        self.sw_method_combo.currentIndexChanged.connect(self._update_sw_hist)
        self.perm_method_combo = QComboBox()
        self.perm_method_combo.setToolTip("Permeability curve shown in the histogram")
        self.perm_method_combo.currentIndexChanged.connect(self._update_perm_hist)

        # 2x2 grid of histograms, selectors above the lower pair
        dist_layout.addWidget(self.vsh_hist, 0, 0)
        dist_layout.addWidget(self.phie_hist, 0, 1)
        dist_layout.addWidget(self.sw_method_combo, 1, 0)
        dist_layout.addWidget(self.perm_method_combo, 1, 1)
        dist_layout.addWidget(self.sw_hist, 2, 0)
        dist_layout.addWidget(self.perm_hist, 2, 1)

        content_layout.addWidget(dist_group)

        # Placeholder
        self.placeholder = QLabel("Run analysis to view petrophysics results")
        self.placeholder.setObjectName("PlaceholderLabel")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.placeholder)

        content_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

    def refresh_theme(self):
        for plot in (
            self.vsh_hist,
            self.phie_hist,
            self.sw_hist,
            self.perm_hist,
        ):
            plot.refresh_theme()

    def update_display(self):
        """Update display with analysis results."""

        # DEBUG: Print state
        # print(f"[DEBUG PetroTab] update_display called")
        # print(f"[DEBUG PetroTab] model.calculated = {self.model.calculated}")
        # print(f"[DEBUG PetroTab] model.results is None = {self.model.results is None}")

        if not self.model.calculated or self.model.results is None:
            self.reset_ui()
            return

        self.placeholder.setVisible(False)

        results = self.model.results
        summary = self.model.summary

        # print(f"[DEBUG PetroTab] results.shape = {results.shape}")
        # print(f"[DEBUG PetroTab] results.columns = {list(results.columns)[:10]}...")

        # Update parameter cards
        if summary:
            self.info_strip.set_value("gr_min", f"{summary.get('gr_min', 0):.1f} API")
            self.info_strip.set_value("gr_max", f"{summary.get('gr_max', 0):.1f} API")
            self.info_strip.set_value("rw", f"{summary.get('rw', 0):.3f} Ω.m")
            self.info_strip.set_value("rsh", f"{summary.get('rsh', 0):.2f} Ω.m")

            # Init filter range if needed (only if 0)
            if self.top_md_spin.value() == 0 and self.bottom_md_spin.value() == 0:
                min_depth = results["DEPTH"].min() if "DEPTH" in results.columns else 0
                max_depth = results["DEPTH"].max() if "DEPTH" in results.columns else 0
                if pd.notna(min_depth):
                    self.top_md_spin.setValue(min_depth)
                if pd.notna(max_depth):
                    self.bottom_md_spin.setValue(max_depth)

        # Update results table
        self._update_table_view()

        # Update histograms - show data or hide if empty
        if "VSH" in results.columns and results["VSH"].dropna().shape[0] > 0:
            self.vsh_hist.setVisible(True)
            self.vsh_hist.plot_histogram(
                results["VSH"].dropna(), "Vshale Distribution", x_label="Vsh"
            )
        else:
            self.vsh_hist.setVisible(False)

        if "PHIE" in results.columns and results["PHIE"].dropna().shape[0] > 0:
            self.phie_hist.setVisible(True)
            self.phie_hist.plot_histogram(
                results["PHIE"].dropna(), "PHIE Distribution", x_label="PHIE"
            )
        else:
            self.phie_hist.setVisible(False)

        self._fill_sw_combo(results)
        self._update_sw_hist()
        self._fill_perm_combo(results)
        self._update_perm_hist()

    def _primary_sw_model(self, results):
        hint = getattr(self.model, "sw_primary_method", None)
        return ts.primary_sw_model(results, hint=hint)

    def _fill_sw_combo(self, results):
        """List the primary Sw first, then every SW_* method present."""
        combo = self.sw_method_combo
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        if "SW" in results.columns:
            combo.addItem(ts.sw_primary_label(self._primary_sw_model(results)), "SW")
        for col in ts.sw_method_columns(results.columns):
            combo.addItem(f"Sw \u2014 {ts.sw_method_name(col)}", col)
        index = combo.findData(previous) if previous else -1
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def _fill_perm_combo(self, results):
        combo = self.perm_method_combo
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for col in ts.perm_columns(results.columns):
            combo.addItem(f"Permeability ({ts.perm_method_name(col)})", col)
        index = combo.findData(previous) if previous else -1
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def _update_sw_hist(self, *_):
        """Sw histogram: the primary SW by default, or the selected SW_* method."""
        results = self.model.results
        column = self.sw_method_combo.currentData()
        if (
            results is None
            or column not in getattr(results, "columns", [])
            or results[column].dropna().shape[0] == 0
        ):
            self.sw_hist.setVisible(False)
            self.sw_method_combo.setVisible(False)
            return
        self.sw_method_combo.setVisible(True)
        self.sw_hist.setVisible(True)
        self.sw_hist.plot_histogram(
            results[column].dropna(),
            self.sw_method_combo.currentText(),
            x_label="Sw",
        )

    def _update_perm_hist(self, *_):
        """Permeability histogram over the selected PERM_* curve."""
        results = self.model.results
        column = self.perm_method_combo.currentData()
        if (
            results is None
            or column not in getattr(results, "columns", [])
            or results[column].dropna().shape[0] == 0
        ):
            self.perm_hist.setVisible(False)
            self.perm_method_combo.setVisible(False)
            return
        self.perm_method_combo.setVisible(True)
        self.perm_hist.setVisible(True)
        self.perm_hist.plot_histogram(
            results[column].dropna(),
            self.perm_method_combo.currentText(),
            x_label="Perm (mD)",
        )

    def _update_table_view(self):
        """Update the table view based on filters."""
        if not self.model.calculated or self.model.results is None:
            return

        results = self.model.results

        result_cols = [
            "DEPTH",
            "VSH",
            "PHID",
            "PHIN",
            "PHIT",
            "PHIE_D",
            "PHIE_N",
            "PHIE_S",
            "PHIE_DN",
            "PHIE",
            "SW",
            *ts.sw_method_columns(results.columns),
            *ts.swt_columns(results.columns),
            "PERM_TIMUR",
            "PERM_WR",
        ]
        display_cols = [c for c in result_cols if c in results.columns]

        if display_cols:
            self.results_table.setVisible(True)

            # Filter by depth
            top = self.top_md_spin.value()
            bottom = self.bottom_md_spin.value()

            if "DEPTH" in results.columns and bottom > top:
                filtered_df = results[
                    (results["DEPTH"] >= top) & (results["DEPTH"] <= bottom)
                ][display_cols]
            else:
                filtered_df = results[display_cols]

            # Limit to 500 rows for performance (better than 100)
            preview_df = filtered_df.head(500).copy()

            # Format numeric columns
            for col in preview_df.columns:
                if preview_df[col].dtype in ["float64", "float32"]:
                    preview_df[col] = preview_df[col].apply(
                        lambda x: f"{x:.4f}" if pd.notna(x) else ""
                    )

            self.results_model.set_dataframe(preview_df)

            # Simple column width - let table handle scroll
            col_count = self.results_model.columnCount()
            for i in range(col_count):
                self.results_table.setColumnWidth(i, 90)

        else:
            self.results_table.setVisible(False)
            self.placeholder.setVisible(True)
            self.placeholder.setText("No displayable columns found in results")

    def reset_ui(self):
        """Reset UI to fresh state for New Project."""
        # Reset spinboxes to 0 so they get updated on next data load
        self.top_md_spin.setValue(0)
        self.bottom_md_spin.setValue(0)

        # Reset metric cards
        self.info_strip.set_value("gr_min", "- API")
        self.info_strip.set_value("gr_max", "- API")
        self.info_strip.set_value("rw", "- Ω.m")
        self.info_strip.set_value("rsh", "- Ω.m")

        # Clear table
        self.results_model.set_dataframe(pd.DataFrame())
        self.results_table.setVisible(False)

        # Clear histograms
        self.vsh_hist.clear()
        self.phie_hist.clear()
        self.sw_hist.clear()
        self.perm_hist.clear()
        for combo in (self.sw_method_combo, self.perm_method_combo):
            combo.blockSignals(True)
            combo.clear()
            combo.blockSignals(False)

        # Show placeholder
        self.placeholder.setVisible(True)
        self.placeholder.setText("Run analysis to view petrophysics results")
