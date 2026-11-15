"""Beds thinner than the deconvolution response width: the per-zone count and the message."""
import numpy as np
import pytest

from modules.issue_codes import ISSUE_CODES
from modules.lrlc.decon import Bed
from modules.lrlc.decon_step import DECON_THIN_WARN_SHARE, thin_bed_issue, thin_bed_stats


def bed(top, bottom):
    return Bed(top=top, bottom=bottom, n_rows=int((bottom - top) / 0.5), rt_prior=10.0,
               rt_decon=10.0, at_bound=False)


DEPTH = np.arange(1000.0, 1100.0, 0.5)


def stats_for(beds, width=4.0, keys=None, active=None):
    keys = np.array(["UPPER"] * len(DEPTH), dtype=object) if keys is None else keys
    active = np.ones(len(DEPTH), dtype=bool) if active is None else active
    return thin_bed_stats(beds, DEPTH, keys, active, width)


def test_the_code_is_registered_as_info_with_a_target():
    assert ISSUE_CODES["LRLC_DECON_THIN_BEDS"] == ("info", "lrlc.remediation.decon")
    assert DECON_THIN_WARN_SHARE == 0.25


def test_thin_means_strictly_below_the_width():
    st = stats_for([bed(1000, 1004), bed(1004, 1007.5), bed(1007.5, 1030)])["UPPER"]
    assert st["n_beds"] == 3 and st["n_thin"] == 1            # the 4.0 ft bed is not thin
    assert st["thin_ft"] == pytest.approx(3.5) and st["thick_ft"] == pytest.approx(30.0)
    assert st["share"] == pytest.approx(3.5 / 30.0)


def test_beds_are_counted_in_the_zone_and_the_active_rows_of_their_midpoint():
    keys = np.array(["UPPER"] * 100 + ["LOWER"] * 100, dtype=object)
    active = np.ones(len(DEPTH), dtype=bool)
    active[:20] = False                                          # 1000-1010 not active
    beds = [bed(1002, 1008), bed(1020, 1022), bed(1060, 1080), bed(1080, 1083)]
    st = stats_for(beds, keys=keys, active=active)
    assert st["UPPER"]["n_beds"] == 1 and st["UPPER"]["n_thin"] == 1
    assert st["LOWER"]["n_beds"] == 2 and st["LOWER"]["n_thin"] == 1
    # the same bed twice (two windows) is one bed
    assert stats_for([bed(1020, 1022), bed(1020, 1022)])["UPPER"]["n_beds"] == 1


def test_info_below_a_quarter_of_the_thickness():
    st = {"n_beds": 6, "n_thin": 2, "thin_ft": 8.0, "thick_ft": 80.0, "share": 0.10}
    text, severity = thin_bed_issue("Zone LOWER", st, 4.0)
    assert severity == "info"
    assert text == ("Deconvolution: 2 of 6 beds in Zone LOWER are thinner than the response width "
                    "(4.0 ft), 10 % of the bed thickness. Thin beds are only partly recovered: "
                    "Rt stays low there and Sw is too high.")


def test_warning_at_a_quarter_of_the_thickness():
    st = {"n_beds": 8, "n_thin": 2, "thin_ft": 10.0, "thick_ft": 40.0, "share": 0.25}
    text, severity = thin_bed_issue("Zone UPPER", st, 4.0)
    assert severity == "warning"
    assert text.endswith(" Check them against the log or use the laminated-sand correction.")


def test_warning_when_more_than_half_of_the_beds_are_thin():
    st = {"n_beds": 5, "n_thin": 3, "thin_ft": 9.0, "thick_ft": 100.0, "share": 0.09}
    assert thin_bed_issue("Zone UPPER", st, 4.0)[1] == "warning"
    even = {"n_beds": 4, "n_thin": 2, "thin_ft": 6.0, "thick_ft": 100.0, "share": 0.06}
    assert thin_bed_issue("Zone UPPER", even, 4.0)[1] == "info"       # exactly half is not "more"


def test_no_message_without_thin_beds_and_one_bed_reads_singular():
    assert thin_bed_issue("Zone UPPER", {"n_beds": 4, "n_thin": 0, "share": 0.0}, 4.0) is None
    one = {"n_beds": 4, "n_thin": 1, "thin_ft": 2.7, "thick_ft": 40.0, "share": 0.07}
    assert "1 of 4 beds in Zone UPPER is thinner" in thin_bed_issue("Zone UPPER", one, 4.0)[0]
