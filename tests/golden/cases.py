"""Shared pipeline regression cases.

Used by ``generate.py`` to write golden outputs and by
``tests/test_pipeline_regression.py`` to compare against them. Datasets come
from the conftest fixtures so the cases stay in step with the rest of the suite.
"""

import io

from modules.formation_tops import FormationTops
from tests import conftest

FULL_MAPPING = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "DT": "DT", "RT": "RT"}

TOPS_TXT = (
    "Formation\tTop (ft)\tBottom (ft)\n"
    "Upper\t1000\t1040\n"
    "Lower\t1040\t1100\n"
)

ALL_SW = ["Archie", "Indonesian", "Simandoux", "Waxman-Smits", "Dual-Water"]
ALL_VSH = ["Linear", "Larionov Tertiary", "Larionov Older"]

CASES = {
    "defaults_whole_well": {"data": "sample_log_data", "params": {}},
    "gas_all_sw_models": {
        "data": "gas_zone_data",
        "params": {
            "gas_correction_enabled": True,
            "primary_phie_method": "PHIE_GAS",
            "sw_methods": ALL_SW,
            "sw_primary_method": "Waxman-Smits",
            "swirr_method": "All Methods",
        },
    },
    "shaly_manual_baseline": {
        "data": "shaly_data",
        "params": {
            "vsh_baseline_method": "Custom (Manual)",
            "gr_min_manual": 40.0,
            "gr_max_manual": 130.0,
            "vsh_methods": ALL_VSH,
            "primary_phie_method": "PHIE_N",
            "sw_methods": ["Archie", "Indonesian"],
            "sw_primary_method": "Archie",
            "rw": 0.01,
            "rw_mode": "auto",
            "swirr_method": "Buckles Number",
            "nphi_matrix": 0.0,
            "lithology_preset": "Limestone",
        },
    },
    "per_formation_lower": {
        "data": "sample_log_data",
        "params": {"analysis_mode": "Per-Formation", "selected_formations": ["Lower"]},
        "tops": True,
    },
    "no_rt_no_dt": {"data": "sample_log_data", "drop": ["RT", "DT"], "params": {}},
}


def fixture_frame(name):
    """Call a conftest fixture function directly, outside of pytest injection."""
    return getattr(conftest, name).__wrapped__()


def make_tops():
    tops = FormationTops()
    assert tops.read_tops_from_buffer(io.StringIO(TOPS_TXT))
    return tops


def build_case(name):
    """Return (data, curve_mapping, params, formation_tops) for a case."""
    spec = CASES[name]
    data = fixture_frame(spec["data"])
    mapping = dict(FULL_MAPPING)
    for curve in spec.get("drop", []):
        data = data.drop(columns=[curve])
        mapping[curve] = "None"
    tops = make_tops() if spec.get("tops") else None
    return data, mapping, dict(spec["params"]), tops
