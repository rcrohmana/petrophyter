"""
Petrophysics Tab for Petrophyter PyQt
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QGroupBox, QTableView, QScrollArea
)
from PyQt6.QtCore import Qt
import pandas as pd

from .qc_tab import MetricCard, PandasTableModel
from ..widgets.plot_widget import HistogramPlot


class PetrophysicsTab(QWidget):
    """Petrophysics calculation results tab."""
    
    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("🧮 Petrophysics Calculations")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)
        
        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        
        # =====================================================================
        # DATA-DRIVEN PARAMETERS
        # =====================================================================
        params_group = QGroupBox("Data-Driven Parameters")
        params_layout = QHBoxLayout(params_group)
        
        self.gr_min_card = MetricCard("GR min", "- API")
        self.gr_max_card = MetricCard("GR max", "- API")
        self.rw_card = MetricCard("Rw", "- Ω.m")
        self.rsh_card = MetricCard("Rsh", "- Ω.m")
        
        params_layout.addWidget(self.gr_min_card)
        params_layout.addWidget(self.gr_max_card)
        params_layout.addWidget(self.rw_card)
        params_layout.addWidget(self.rsh_card)
        
        content_layout.addWidget(params_group)
        
        # =====================================================================
        # RESULTS TABLE
        # =====================================================================
        results_group = QGroupBox("Calculated Results Preview")
        results_layout = QVBoxLayout(results_group)
        
        self.results_table = QTableView()
        self.results_model = PandasTableModel()
        self.results_table.setModel(self.results_model)
        self.results_table.setMaximumHeight(300)
        results_layout.addWidget(self.results_table)
        
        content_layout.addWidget(results_group)
        
        # =====================================================================
        # PROPERTY DISTRIBUTIONS
        # =====================================================================
        dist_group = QGroupBox("Property Distributions")
        dist_layout = QHBoxLayout(dist_group)
        
        self.vsh_hist = HistogramPlot()
        self.phie_hist = HistogramPlot()
        self.sw_hist = HistogramPlot()
        
        dist_layout.addWidget(self.vsh_hist)
        dist_layout.addWidget(self.phie_hist)
        dist_layout.addWidget(self.sw_hist)
        
        content_layout.addWidget(dist_group)
        
        # Placeholder
        self.placeholder = QLabel("👈 Configure parameters in sidebar and click 'Run Analysis'")
        self.placeholder.setStyleSheet("color: #4A4540; background-color: transparent; font-size: 14px;")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.placeholder)
        
        content_layout.addStretch()
        
        scroll.setWidget(content)
        layout.addWidget(scroll)
    
    def update_display(self):
        """Update display with analysis results."""
        if not self.model.calculated or self.model.results is None:
            self.placeholder.setVisible(True)
            return
        
        self.placeholder.setVisible(False)
        
        results = self.model.results
        summary = self.model.summary
        
        # Update parameter cards
        if summary:
            self.gr_min_card.set_value(f"{summary.get('gr_min', 0):.1f} API")
            self.gr_max_card.set_value(f"{summary.get('gr_max', 0):.1f} API")
            self.rw_card.set_value(f"{summary.get('rw', 0):.3f} Ω.m")
            self.rsh_card.set_value(f"{summary.get('rsh', 0):.2f} Ω.m")
        
        # Update results table
        result_cols = ['DEPTH', 'VSH', 'PHID', 'PHIN', 'PHIT', 
                       'PHIE_D', 'PHIE_N', 'PHIE_S', 'PHIE_DN', 'PHIE',
                       'SW_ARCHIE', 'SW_INDO', 'SW_SIMAN', 
                       'PERM_TIMUR', 'PERM_WR']
        display_cols = [c for c in result_cols if c in results.columns]
        
        if display_cols:
            preview_df = results[display_cols].head(100).copy()
            # Format numeric columns
            for col in preview_df.columns:
                if preview_df[col].dtype in ['float64', 'float32']:
                    preview_df[col] = preview_df[col].apply(lambda x: f"{x:.4f}" if pd.notna(x) else "")
            self.results_model.set_dataframe(preview_df)
        
        # Update histograms
        if 'VSH' in results.columns:
            self.vsh_hist.plot_histogram(results['VSH'].dropna(), "Vshale Distribution", x_label="Vsh")
        
        if 'PHIE' in results.columns:
            self.phie_hist.plot_histogram(results['PHIE'].dropna(), "PHIE Distribution", x_label="PHIE")
        
        if 'SW_INDO' in results.columns:
            self.sw_hist.plot_histogram(results['SW_INDO'].dropna(), "Sw (Indonesian)", x_label="Sw")
        elif 'SW_ARCHIE' in results.columns:
            self.sw_hist.plot_histogram(results['SW_ARCHIE'].dropna(), "Sw (Archie)", x_label="Sw")
