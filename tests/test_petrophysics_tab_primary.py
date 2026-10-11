"""U8: Petrophysics tab histograms and table follow the primary Sw."""

import numpy as np
import pandas as pd
import pytest

from models.app_model import AppModel
from ui.tabs.petrophysics_tab import PetrophysicsTab


def _tab(qtbot, **extra):
    n = 30
    sw = np.linspace(0.2, 0.8, n)
    data = {
        "DEPTH": np.linspace(1000.0, 1010.0, n),
        "VSH": np.linspace(0.1, 0.5, n),
        "PHIE": np.linspace(0.1, 0.25, n),
        "PHIT": np.linspace(0.12, 0.27, n),
        "SW": sw,
        "SW_SIMAN": sw,
        "SW_ARCHIE": sw * 0.8,
        "PERM_WR": np.linspace(1.0, 100.0, n),
    }
    data.update(extra)
    model = AppModel()
    model._well.calculated = True
    model._well.results = pd.DataFrame(data)
    model._well.summary = {}
    tab = PetrophysicsTab(model)
    qtbot.addWidget(tab)
    tab.update_display()
    return tab


def _combo_items(combo):
    return [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]


def test_simandoux_run_histogram_shows_primary_sw(qtbot):
    tab = _tab(qtbot)

    assert tab.sw_method_combo.currentData() == "SW"
    assert tab.sw_hist.figure.axes[0].get_title() == "Sw — Simandoux (primary)"
    assert not tab.sw_hist.isHidden()
    assert tab.sw_hist.figure.axes[0].patches


def test_sw_selector_lists_every_present_method(qtbot):
    tab = _tab(qtbot)

    assert _combo_items(tab.sw_method_combo) == [
        ("Sw — Simandoux (primary)", "SW"),
        ("Sw — Archie", "SW_ARCHIE"),
        ("Sw — Simandoux", "SW_SIMAN"),
    ]
    tab.sw_method_combo.setCurrentIndex(1)
    assert tab.sw_hist.figure.axes[0].get_title() == "Sw — Archie"


def test_permeability_selector_lists_present_perm_curves(qtbot):
    tab = _tab(qtbot)

    assert _combo_items(tab.perm_method_combo) == [
        ("Permeability (Wyllie-Rose)", "PERM_WR")
    ]
    assert tab.perm_hist.figure.axes[0].get_title() == "Permeability (Wyllie-Rose)"

    tab = _tab(qtbot, PERM_TIMUR=np.linspace(2.0, 90.0, 30))
    assert [d for _, d in _combo_items(tab.perm_method_combo)] == ["PERM_TIMUR", "PERM_WR"]


def test_table_whitelist_adds_sw_curves_and_phit(qtbot):
    tab = _tab(qtbot, SWT_X=np.linspace(0.3, 0.9, 30))
    cols = list(tab.results_model._df.columns)

    assert "SW" in cols and "SW_SIMAN" in cols and "SW_ARCHIE" in cols
    assert "SWT_X" in cols and "PHIT" in cols and "PERM_WR" in cols
    assert "SW_INDO" not in cols  # absent curves are not shown
    assert "PERM_TIMUR" not in cols


def test_selection_survives_a_new_run(qtbot):
    tab = _tab(qtbot)
    tab.sw_method_combo.setCurrentIndex(1)
    tab.update_display()
    assert tab.sw_method_combo.currentData() == "SW_ARCHIE"
