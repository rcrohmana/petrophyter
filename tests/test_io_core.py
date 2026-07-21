"""
Regression tests for data-integrity fixes in modules/core_handler.py.
Imports the production CoreDataHandler directly (previously untested).

Covered fixes:
  - token-based column detection: alias 'k' no longer matches 'Remarks',
    'por' no longer matches 'Report_ID' (false-positive perm/porosity columns)
  - honest depth-unit detection: a bare 'Depth' column under Auto is NOT
    silently assumed meters and tripled; a warning is recorded instead
"""

import io
import numpy as np
import pytest

from modules.core_handler import CoreDataHandler


def _buf(text):
    return io.StringIO(text)


# --------------------------------------------------------------------------- #
# Column detection (token matching)
# --------------------------------------------------------------------------- #
def test_k_alias_does_not_match_remarks():
    handler = CoreDataHandler()
    ok = handler.read_core_from_buffer(
        _buf("Depth (m)\tRemarks\tPorosity (%)\n"
             "1000\tclean sand\t20\n1001\tshale streak\t18\n1002\tclean\t22\n"),
        separator="\t",
    )
    assert ok
    # 'Remarks' must not be mistaken for a permeability column.
    assert handler.perm_col is None
    assert handler.porosity_col == "porosity (%)"


def test_k_alias_matches_real_perm_column():
    handler = CoreDataHandler()
    ok = handler.read_core_from_buffer(
        _buf("Depth (m)\tK (mD)\tRemarks\n"
             "1000\t150\tnote\n1001\t200\tnote\n1002\t50\tnote\n"),
        separator="\t",
    )
    assert ok
    assert handler.perm_col == "k (md)"


def test_por_alias_does_not_match_report_id():
    handler = CoreDataHandler()
    ok = handler.read_core_from_buffer(
        _buf("Depth (m)\tReport_ID\tPermeability (mD)\n"
             "1000\tR1\t10\n1001\tR2\t20\n1002\tR3\t30\n"),
        separator="\t",
    )
    assert ok
    # 'Report_ID' contains the substring 'por' but is not a porosity column.
    assert handler.porosity_col is None
    assert handler.perm_col == "permeability (md)"


# --------------------------------------------------------------------------- #
# Depth-unit honesty
# --------------------------------------------------------------------------- #
def _feet_native_bare_depth():
    return _buf("Depth\tPorosity (%)\n5000\t20\n5010\t22\n5020\t18\n5030\t25\n")


def test_bare_depth_auto_is_not_converted_and_warns():
    handler = CoreDataHandler()
    assert handler.read_core_from_buffer(_feet_native_bare_depth(), depth_unit="Auto")
    assert handler.depth_unit_detected is False
    assert handler.depth_unit_warning is not None
    assert handler.converted_to_feet is False
    depths = handler.get_core_depths()
    # Left unchanged (~5000), NOT tripled to ~16400.
    assert depths.min() == pytest.approx(5000.0)


def test_meters_column_auto_is_converted():
    handler = CoreDataHandler()
    assert handler.read_core_from_buffer(
        _buf("Depth (m)\tPorosity (%)\n1000\t20\n1010\t22\n1020\t18\n"),
        depth_unit="Auto",
    )
    assert handler.depth_unit_detected is True
    assert handler.converted_to_feet is True
    assert handler.get_core_depths().min() == pytest.approx(1000.0 * 3.28084)


def test_feet_column_auto_is_not_converted():
    handler = CoreDataHandler()
    assert handler.read_core_from_buffer(
        _buf("Depth (ft)\tPorosity (%)\n5000\t20\n5010\t22\n5020\t18\n"),
        depth_unit="Auto",
    )
    assert handler.depth_unit_detected is True
    assert handler.converted_to_feet is False
    assert handler.get_core_depths().min() == pytest.approx(5000.0)


def test_explicit_ft_overrides_bare_column():
    handler = CoreDataHandler()
    assert handler.read_core_from_buffer(_feet_native_bare_depth(), depth_unit="FT")
    assert handler.depth_unit_detected is True
    assert handler.converted_to_feet is False
    assert handler.get_core_depths().min() == pytest.approx(5000.0)


# --------------------------------------------------------------------------- #
# Porosity unit handling
# --------------------------------------------------------------------------- #
def test_percent_porosity_converted_to_fraction():
    handler = CoreDataHandler()
    assert handler.read_core_from_buffer(
        _buf("Depth (ft)\tPorosity (%)\n5000\t20\n5010\t22\n5020\t18\n"),
        depth_unit="FT",
    )
    _, por = handler.get_core_porosity()
    assert handler.porosity_converted is True
    assert por.max() <= 1.0


def test_corrupt_porosity_over_100_warns(caplog):
    handler = CoreDataHandler()
    with caplog.at_level("WARNING"):
        handler.read_core_from_buffer(
            _buf("Depth (ft)\tPorosity (%)\n5000\t200\n5010\t350\n5020\t180\n"),
            depth_unit="FT",
        )
    assert any("> 100" in rec.message or "100" in rec.message for rec in caplog.records)
