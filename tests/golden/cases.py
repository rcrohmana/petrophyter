"""Shared pipeline regression cases.

Used by ``generate.py`` to write golden outputs and by
``tests/test_pipeline_regression.py`` to compare against them. Datasets come
from the conftest fixtures so the cases stay in step with the rest of the suite.
"""

import copy
import io
from types import SimpleNamespace

import numpy as np
import pandas as pd

from modules.formation_tops import FormationTops
from modules.shf import BASIS_CORE, BASIS_LOG, ShfFit
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


# Literal rock-type definitions (as Project.rock_types stores them) for the
# rock_typing_enabled case: three FZI types, pooled over the project.
ROCK_TYPE_SET = {
    "n_rt": 3, "centers": [-0.3, 0.35, 0.85], "boundaries": [0.025, 0.6],
    "fzi": [0.5011872336272722, 2.2387211385683394, 7.079457843841379],
    "n_samples": [20, 30, 25], "sd": [0.1, 0.1, 0.1], "feature_range": [-0.6, 1.1],
    "k_rmse_log10": [0.2, 0.2, 0.2], "edited": False, "basis": "golden literal",
}
ROCK_TYPE_SETTINGS = {
    "seed": 0, "restarts": 10, "min_samples": 20, "min_per_rt": 5, "reservoir_only": True,
    "min_phie": 0.02, "use_core_labels": True, "margin_min": 0.05, "lorenz": True,
    "r35_column": True, "perm_rt_column": True, "ob_phi_factor": 1.0, "ob_k_factor": 1.0,
    "core_phi_min": 0.01, "core_phi_max": 0.5,
}
ROCK_TYPE_DEFS = {
    "version": 1, "method": "fzi", "feature": "log10_fzi", "fit_scope": "project",
    "sets": {"*": ROCK_TYPE_SET}, "settings": ROCK_TYPE_SETTINGS,
}



def _power_fit(basis):
    """A literal "All" power-law saturation-height fit (as Project.shf["fits"] stores it)."""
    fit = ShfFit(rock_type="All", model="power", params={"c": 0.45, "d": -0.55}, basis=basis,
                 n_samples=12, n_points=120, rmse=0.03, bias=0.0, r2=0.97)
    return fit.to_dict()


# Saturation height on the sample log: MD stands in for TVD (no TVD curve), FWL 1090 ft.
SHF_CONTACTS = {"datum": "TVD", "kb_ft": None, "default": {"fwl": 1090.0, "fluid": "oil"},
                "zones": {}}

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
    # Rock typing on, no core (log-derived types), PERM_RT as primary permeability.
    "rock_typing_enabled": {
        "data": "sample_log_data",
        "params": {"rock_typing_enabled": True, "perm_primary": "Rock type"},
        "rock_types": ROCK_TYPE_DEFS,
        "tops": True,
    },
    # Saturation height from a core-Pc fit, used for pay and HCPV.
    "shf_core_pc": {
        "data": "sample_log_data",
        "params": {},
        "shf": {"settings": {"enabled": True, "use_for_pay": True,
                             "fits": {"All": _power_fit(BASIS_CORE)}},
                "contacts": SHF_CONTACTS},
    },
    # A log-derived fit with use for pay requested: refused, pay stays on resistivity Sw.
    "shf_log_derived": {
        "data": "sample_log_data",
        "params": {},
        "shf": {"settings": {"enabled": True, "use_for_pay": True,
                             "fits": {"All": _power_fit(BASIS_LOG)}},
                "contacts": SHF_CONTACTS},
    },
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
    params = dict(spec["params"])
    if spec.get("rock_types"):
        # What AppModel.params_for_well hands the pipeline for an uncored well.
        defs = spec["rock_types"]
        params["rock_types"] = {
            "method": defs["method"], "feature": defs["feature"], "fit_scope": defs["fit_scope"],
            "set": defs["sets"]["*"], "zone_sets": {}, "settings": dict(defs["settings"]),
            "basis": "pooled", "core_max_dist": 2.0}
        params["rock_core"] = None
    if spec.get("shf"):
        # What AppModel.params_for_well hands the pipeline when saturation height is on.
        from models.app_model import AppModel

        model = AppModel()
        model.project.shf.update(copy.deepcopy(spec["shf"]["settings"]))
        params["shf"] = model._shf_params(
            SimpleNamespace(shf_contacts=copy.deepcopy(spec["shf"]["contacts"])))
    return data, mapping, params, tops


def apply_to_model(model, name, params):
    """Set a case's params on an AppModel; definitions go to ``Project.rock_types``."""
    for key, value in params.items():
        if key in ("rock_types", "rock_core", "shf"):
            continue
        assert hasattr(model, key), key
        setattr(model, key, value)
    if CASES[name].get("rock_types"):
        model.project.rock_types = CASES[name]["rock_types"]
    if CASES[name].get("shf"):
        model.project.shf.update(copy.deepcopy(CASES[name]["shf"]["settings"]))
        model._well.shf_contacts = copy.deepcopy(CASES[name]["shf"]["contacts"])
