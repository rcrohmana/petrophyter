"""Shared pipeline regression cases.

Used by ``generate.py`` to write golden outputs and by
``tests/test_pipeline_regression.py`` to compare against them. Datasets come
from the conftest fixtures so the cases stay in step with the rest of the suite.
"""

import io

import numpy as np
import pandas as pd

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

def mixed_depth_step_data():
    """30 ft sampled every 0.1524 ft, then 40 ft every 0.5 ft (a log with a step change).

    Locks the local-step thickness and HCPV rule (C10) and the weighted pay
    averages (C12): porosity varies along the interval, so the pore-volume
    weighted Sw differs from the arithmetic mean.
    """
    rng = np.random.default_rng(20261010)
    fine = 1000.0 + 0.1524 * np.arange(197)
    coarse = fine[-1] + 0.5 * np.arange(1, 81)
    depth = np.concatenate([fine, coarse])
    n = len(depth)
    wave = np.sin(depth / 6.0)
    return pd.DataFrame({
        "DEPTH": depth,
        "GR": 55.0 + 25.0 * wave + 5.0 * rng.random(n),
        "RHOB": 2.33 + 0.08 * wave + 0.03 * rng.random(n),
        "NPHI": 0.22 + 0.05 * wave + 0.02 * rng.random(n),
        "DT": 85.0 + 8.0 * wave + 3.0 * rng.random(n),
        "RT": 25.0 + 20.0 * np.cos(depth / 9.0) + 10.0 * rng.random(n),
    })


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
    "dual_water_primary": {
        "data": "dual_water_data",
        "params": {
            "vsh_baseline_method": "Custom (Manual)",
            "gr_min_manual": 20.0,
            "gr_max_manual": 120.0,
            "primary_phie_method": "PHIE_DN",
            "sw_methods": ["Archie", "Waxman-Smits", "Dual-Water"],
            "sw_primary_method": "Dual-Water",
            "swirr_method": "Buckles Number",
        },
    },
    "no_rt_no_dt": {"data": "sample_log_data", "drop": ["RT", "DT"], "params": {}},
    "mixed_depth_step": {"builder": mixed_depth_step_data, "params": {}},
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
    data = spec["builder"]() if "builder" in spec else fixture_frame(spec["data"])
    mapping = dict(FULL_MAPPING)
    for curve in spec.get("drop", []):
        data = data.drop(columns=[curve])
        mapping[curve] = "None"
    tops = make_tops() if spec.get("tops") else None
    return data, mapping, dict(spec["params"]), tops
