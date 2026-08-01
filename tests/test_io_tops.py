"""
Regression tests for data-integrity fixes in modules/formation_tops.py.
Imports the production FormationTops directly (previously untested).

Covered fixes:
  - convert_to_feet() is unit-aware: a feet-native tops file is no longer
    wrongly multiplied by 3.28084; meters files still convert
  - honest depth-unit detection with warning when undetected
  - half-open boundary interval (shared boundary resolves to one formation)
  - missing bottom column defaults to the next formation's top (not zero thickness)
  - reversed top/bottom rows are repaired (swapped), not hidden by abs()
  - NaN top rows dropped before sorting
"""

import io
import pytest

from modules.formation_tops import FormationTops


def _buf(text):
    return io.StringIO(text)


# --------------------------------------------------------------------------- #
# Depth-unit / double-conversion
# --------------------------------------------------------------------------- #
def test_feet_file_not_converted_by_convert_to_feet():
    tops = FormationTops()
    assert tops.read_tops_from_buffer(
        _buf("Formation\tTop (ft)\tBottom (ft)\nA\t5000\t5100\nB\t5100\t5200\n")
    )
    assert tops.depth_unit == "FT"
    assert tops.depth_unit_detected is True
    tops.convert_to_feet()  # UI always calls this; must be a no-op for feet
    assert tops.formations[0].top_depth == pytest.approx(5000.0)


def test_meters_file_is_converted():
    tops = FormationTops()
    assert tops.read_tops_from_buffer(
        _buf("Formation\tTop (m)\tBottom (m)\nA\t1000\t1100\n")
    )
    assert tops.depth_unit == "M"
    tops.convert_to_feet()
    assert tops.formations[0].top_depth == pytest.approx(1000.0 * 3.28084)
    assert tops.depth_unit == "FT"


def test_undetected_unit_warns_and_not_converted():
    tops = FormationTops()
    assert tops.read_tops_from_buffer(
        _buf("Formation\tTop\tBottom\nA\t1000\t1100\n")
    )
    assert tops.depth_unit_detected is False
    assert tops.depth_unit_warning is not None
    tops.convert_to_feet()
    assert tops.formations[0].top_depth == pytest.approx(1000.0)


# --------------------------------------------------------------------------- #
# Boundary interval
# --------------------------------------------------------------------------- #
def test_shared_boundary_resolves_to_single_formation():
    tops = FormationTops()
    tops.read_tops_from_buffer(
        _buf("Formation\tTop (ft)\tBottom (ft)\nA\t5000\t5100\nB\t5100\t5200\n")
    )
    # Exactly on the A/B boundary -> B (half-open [top, bottom)).
    assert tops.get_formation_name_at_depth(5100) == "B"
    # Interior points resolve to their own formation.
    assert tops.get_formation_name_at_depth(5050) == "A"
    # Deepest bottom stays inclusive.
    assert tops.get_formation_name_at_depth(5200) == "B"


# --------------------------------------------------------------------------- #
# Missing bottom / swaps / NaN handling
# --------------------------------------------------------------------------- #
def test_missing_bottom_defaults_to_next_top():
    tops = FormationTops()
    tops.read_tops_from_buffer(
        _buf("Formation\tTop (m)\nA\t1000\nB\t1200\nC\t1500\n")
    )
    a, b, c = tops.formations
    assert a.bottom_depth == pytest.approx(1200.0)
    assert a.thickness == pytest.approx(200.0)
    assert b.bottom_depth == pytest.approx(1500.0)
    # Last formation has no next top -> bottom falls back to its own top.
    assert c.bottom_depth == pytest.approx(1500.0)


def test_reversed_top_bottom_is_repaired():
    tops = FormationTops()
    tops.read_tops_from_buffer(
        _buf("Formation\tTop (m)\tBottom (m)\nA\t1100\t1000\n")
    )
    fm = tops.formations[0]
    assert fm.top_depth == pytest.approx(1000.0)
    assert fm.bottom_depth == pytest.approx(1100.0)
    # Range query now works because top < bottom.
    assert tops.get_formation_name_at_depth(1050) == "A"


def test_nan_top_rows_dropped():
    tops = FormationTops()
    tops.read_tops_from_buffer(
        _buf("Formation\tTop (m)\tBottom (m)\nA\t1000\t1100\nBad\t\t1200\nB\t1100\t1300\n")
    )
    names = [f.name for f in tops.formations]
    assert "Bad" not in names
    assert names == ["A", "B"]


def test_filter_by_formations_selects_ranges():
    import pandas as pd
    tops = FormationTops()
    tops.read_tops_from_buffer(
        _buf("Formation\tTop (ft)\tBottom (ft)\nA\t5000\t5100\nB\t5100\t5200\n")
    )
    data = pd.DataFrame({"DEPTH": [5010, 5050, 5150, 5190]})
    out = tops.filter_by_formations(data, ["A"])
    assert out["DEPTH"].tolist() == [5010, 5050]


def test_reusing_tops_resets_unit_conversion_state():
    tops = FormationTops()
    assert tops.read_tops_from_buffer(
        _buf("Formation\tTop (m)\tBottom (m)\nA\t1000\t1100\n")
    )
    tops.convert_to_feet()
    assert tops.formations[0].top_depth == pytest.approx(1000.0 * 3.28084)

    # A second meter file must be detected and converted independently.
    assert tops.read_tops_from_buffer(
        _buf("Formation\tTop (m)\tBottom (m)\nB\t2000\t2100\n")
    )
    assert tops.converted_to_feet is False
    tops.convert_to_feet()
    assert tops.formations[0].top_depth == pytest.approx(2000.0 * 3.28084)

    # A subsequent feet file clears any old warning and remains unchanged.
    assert tops.read_tops_from_buffer(
        _buf("Formation\tTop (ft)\tBottom (ft)\nC\t6000\t6100\n")
    )
    assert tops.depth_unit_warning is None
    assert tops.converted_to_feet is False
    tops.convert_to_feet()
    assert tops.formations[0].top_depth == pytest.approx(6000.0)


def test_filter_uses_same_half_open_boundary_as_lookup():
    import pandas as pd

    tops = FormationTops()
    assert tops.read_tops_from_buffer(
        _buf("Formation\tTop (ft)\tBottom (ft)\nA\t5000\t5100\nB\t5100\t5200\n")
    )
    data = pd.DataFrame({"DEPTH": [5000, 5099.9, 5100, 5199.9, 5200]})

    assert tops.filter_by_formations(data, ["A"])["DEPTH"].tolist() == [5000, 5099.9]
    assert tops.filter_by_formations(data, ["B"])["DEPTH"].tolist() == [5100, 5199.9, 5200]


def test_range_query_uses_half_open_shared_boundary():
    tops = FormationTops()
    assert tops.read_tops_from_buffer(
        _buf("Formation\tTop (ft)\tBottom (ft)\nA\t5000\t5100\nB\t5100\t5200\n")
    )

    assert [fm.name for fm in tops.get_formations_in_range(5100, 5100)] == ["B"]
