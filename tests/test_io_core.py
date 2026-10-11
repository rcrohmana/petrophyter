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


def test_reusing_handler_resets_conversion_and_warning_state():
    handler = CoreDataHandler()

    # First read an ambiguous, feet-native file.
    assert handler.read_core_from_buffer(_feet_native_bare_depth(), depth_unit="Auto")
    assert handler.depth_unit_warning is not None
    assert handler.converted_to_feet is False

    # A later meter file must still be converted; stale state from a prior read
    # must not suppress the conversion.
    assert handler.read_core_from_buffer(
        _buf("Depth (m)\tPorosity (%)\n1000\t20\n1010\t22\n1020\t18\n"),
        depth_unit="Auto",
    )
    assert handler.depth_unit_warning is None
    assert handler.converted_to_feet is True
    assert handler.get_core_depths().min() == pytest.approx(1000.0 * 3.28084)

    # Reading another meter file after conversion must not inherit the old
    # converted_to_feet guard and leave the new values in meters.
    assert handler.read_core_from_buffer(
        _buf("Depth (m)\tPorosity (%)\n2000\t20\n2010\t22\n2020\t18\n"),
        depth_unit="Auto",
    )
    assert handler.get_core_depths().min() == pytest.approx(2000.0 * 3.28084)


def test_read_core_file_decodes_utf8_headers(tmp_path):
    path = tmp_path / "core_utf8.tsv"
    path.write_bytes(
        "Depth (ft)\tPorosity (%)\tGrain density (g/cm³)\n"
        "5000\t20\t2.65\n"
        "5010\t22\t2.66\n"
        "5020\t18\t2.64\n".encode("utf-8")
    )

    handler = CoreDataHandler()
    assert handler.read_core_file(str(path), separator="\t")
    assert "grain density (g/cm³)" in handler.to_dataframe().columns


# --------------------------------------------------------------------------- #
# I6: null sentinels and non-physical values; I14: matching across log gaps
# --------------------------------------------------------------------------- #
def _plug_text(n=20, sentinel_rows=()):
    rows = ["Depth (ft)\tPorosity\tPerm (mD)"]
    for i in range(n):
        por, perm = 0.10 + 0.005 * i, 5.0 * (1 + i)
        if i in sentinel_rows:
            por, perm = -999.25, -999.25
        rows.append(f"{1000 + i}\t{por}\t{perm}")
    return "\n".join(rows) + "\n"


def test_i6_sentinels_are_excluded_counted_and_statistics_match_clean_file():
    bad = (2, 5, 8, 11, 14)
    sent = CoreDataHandler()
    assert sent.read_core_from_buffer(_buf(_plug_text(sentinel_rows=bad)), separator="\t")
    # five rows x two values, each with a reason
    reasons = [r for _, r in sent.excluded_rows]
    assert len(reasons) == 10 and all("null sentinel" in r for r in reasons)
    assert any("null sentinel" in n for n in sent.notes)

    clean = CoreDataHandler()
    lines = _plug_text().splitlines()
    keep = [ln for i, ln in enumerate(lines) if i == 0 or (i - 1) not in bad]
    assert clean.read_core_from_buffer(_buf("\n".join(keep) + "\n"), separator="\t")

    d1, p1 = sent.get_core_porosity()
    d2, p2 = clean.get_core_porosity()
    assert np.array_equal(d1, d2) and np.allclose(p1, p2)
    k1 = sent.get_core_permeability()[1]
    assert np.allclose(k1, clean.get_core_permeability()[1])
    assert np.nanmin(p1) > 0 and np.nanmin(k1) > 0


def test_i6_negative_porosity_and_nonpositive_perm_are_excluded():
    handler = CoreDataHandler()
    assert handler.read_core_from_buffer(
        _buf("Depth (ft)\tPorosity\tPerm (mD)\n1000\t0.2\t10\n1001\t-0.05\t0\n1002\t0.18\t-3\n1003\t0.21\t30\n"),
        separator="\t")
    reasons = " ".join(r for _, r in handler.excluded_rows)
    assert "negative porosity" in reasons and "permeability not positive" in reasons
    assert np.all(handler.get_core_porosity()[1] > 0)
    assert np.all(handler.get_core_permeability()[1] > 0)


def _gap_handler(depths):
    handler = CoreDataHandler()
    text = "Depth (ft)\tPorosity\n" + "".join(f"{d}\t0.2\n" for d in depths)
    assert handler.read_core_from_buffer(_buf(text), separator="\t")
    return handler


def test_i14_core_beside_a_log_gap_is_nan_and_counted():
    handler = _gap_handler([1002.0])
    out = handler.interpolate_log_to_core(
        np.array([1000.0, 1001.0, 1100.0]), np.array([0.1, 0.2, 0.3]),
        np.array([1002.0]), max_dist_ft=2.0)
    assert np.isnan(out[0]) and handler.n_core_in_log_gaps == 1


def test_i14_close_samples_and_exact_match_still_match():
    handler = _gap_handler([1000.5])
    depth, vals = np.array([1000.0, 1001.0, 1100.0]), np.array([0.1, 0.2, 0.3])
    out = handler.interpolate_log_to_core(depth, vals, np.array([1000.5, 1001.0, 1100.0]), 2.0)
    assert out[0] == pytest.approx(0.15) and out[1] == pytest.approx(0.2) and out[2] == pytest.approx(0.3)
    assert handler.n_core_in_log_gaps == 0


def test_i14_validation_statistics_count_gap_cores():
    depths = [1000.0, 1001.0, 1002.0, 1003.0, 1052.0, 1053.0, 1054.0]
    handler = _gap_handler(depths)
    log_depth = np.array([1000.0, 1001.0, 1002.0, 1003.0, 1100.0])
    result = handler.validate_porosity(log_depth, np.full(5, 0.2), max_dist_ft=2.0)
    assert result.n_points == 4 and result.n_in_log_gaps == 3
