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


def lrlc_screening_data():
    """A shaly log with a shallow resistivity curve (``RS``): thin low-resistivity sands.

    Sand and shale alternate (shale fraction 0 to 1 by a smooth wave); sands read only 3 to 8
    ohm.m, the shallow curve reads below the deep one in the upper half (hydrocarbon-like) and about equal to it
    in the lower half, so the screening criteria split both ways. Deterministic.
    """
    rng = np.random.default_rng(20261021)
    depth = np.linspace(1000.0, 1100.0, 200)
    shale = 0.5 + 0.5 * np.sin(depth / 5.0 + 0.6)
    noise = rng.random(len(depth))
    rt = 1.4 + 6.5 * (1.0 - shale) * (0.55 + 0.45 * rng.random(len(depth)))
    rs_ratio = np.where(depth < 1040.0, 0.7 + 0.2 * rng.random(len(depth)),
                        0.8 + 0.5 * rng.random(len(depth)))
    return pd.DataFrame({
        "DEPTH": depth,
        "GR": 40.0 + 80.0 * shale + 4.0 * noise,
        "RHOB": 2.28 + 0.24 * shale + 0.02 * rng.random(len(depth)),
        "NPHI": 0.15 + 0.22 * shale + 0.015 * rng.random(len(depth)),
        "DT": 78.0 + 38.0 * shale + 3.0 * rng.random(len(depth)),
        "RT": rt,
        "RS": rt * rs_ratio,
    })


def lrlc_laminated_data():
    """Sand laminae and shale laminae from the forward model, Upper laminated and Lower clean.

    The sand laminae carry Archie Sw 0.30 at porosity 0.30; the shale laminae have porosity
    0.08 and Rsh 2 ohm.m. Rt is the parallel combination, total porosity the volume-weighted
    value and the shale volume equals the laminar volume (laminar line). Lower is nearly clean
    sand. Deterministic.
    """
    phi_max, phi_sh, rw, rsh, sw = 0.30, 0.08, 0.05, 2.0, 0.30
    depth = np.linspace(1000.0, 1100.0, 201)
    wave = 0.5 + 0.5 * np.sin(depth / 3.0)
    vlam = np.where(depth < 1040.0, 0.12 + 0.36 * wave, 0.01 + 0.03 * wave)
    phit = (1.0 - vlam) * phi_max + vlam * phi_sh
    rsand = rw / (phi_max ** 2 * sw ** 2)
    rt = 1.0 / ((1.0 - vlam) / rsand + vlam / rsh)
    return pd.DataFrame({
        "DEPTH": depth,
        "GR": 20.0 + 100.0 * vlam,
        "RHOB": 2.65 - 1.65 * phit,
        "RT": rt,
    })


def lrlc_pyrite_data():
    """A clean sand with a pyritic interval: RHOB and PEF from the volumetric model.

    Matrix, pyrite and fluid densities 2.65, 4.99 and 1.0 g/cc; matrix and pyrite PEF 1.81 and
    16.97; the fluid volumetric cross-section 0.36. The true Rt is Archie at Sw 0.40; connected
    pyrite (half of it) adds a parallel conductance with Rpy 0.1 ohm.m. Deterministic.
    """
    rw, rpy, f, sw = 0.05, 0.1, 0.5, 0.40
    depth = np.linspace(2000.0, 2100.0, 201)
    phi = 0.18 + 0.05 * np.sin(depth / 7.0)
    vpyr = 0.05 * np.clip(np.sin(depth / 11.0), 0.0, None)
    vma = 1.0 - phi - vpyr
    rhob = phi * 1.0 + vma * 2.65 + vpyr * 4.99
    u = phi * 0.36 + vma * 1.81 * 2.65 + vpyr * 16.97 * 4.99
    rt_true = rw / (phi ** 2 * sw ** 2)
    rt = 1.0 / (1.0 / rt_true + f * vpyr / rpy)
    return pd.DataFrame({
        "DEPTH": depth,
        "GR": np.full(len(depth), 20.0),
        "RHOB": rhob,
        "PEF": u / rhob,
        "RT": rt,
    })


# Known truth of the invasion case: (top, bottom, Rt, Rxo, di) per interval, ft and in.
INVASION_INTERVALS = (
    (1000.0, 1030.0, 20.0, 2.0, 40.0),     # well posed
    (1030.0, 1050.0, 8.0, 1.5, 25.0),      # well posed
    (1050.0, 1065.0, 12.0, 12.5, 30.0),    # Rxo close to Rt: non-unique
    (1065.0, 1085.0, 15.0, 1.5, 150.0),    # di above the upper bound (120 in)
    (1085.0, 1100.0, 30.0, 3.0, 60.0),     # well posed
)


def invasion_truth(depth):
    """Per-sample true (Rt, Rxo, di) of the invasion case; Rt undulates gently inside an interval."""
    rt, rxo, di = (np.full(len(depth), np.nan) for _ in range(3))
    for top, bottom, t, x, d in INVASION_INTERVALS:
        sel = (depth >= top) & (depth < bottom)
        rt[sel] = t * (1.0 + 0.25 * np.sin(depth[sel] / 4.0))
        rxo[sel] = x
        di[sel] = d
    return rt, rxo, di


def lrlc_invasion_data():
    """A clean sand with a step invasion profile from the forward model, no noise.

    Deep, medium and shallow readings come from the generic induction tool (80, 45 and 20 in,
    shape 2.5). Five intervals: three well posed, one with Rxo close to Rt and one with an
    invasion diameter above the upper bound. A few samples lose a curve (NaN). Deterministic.
    """
    from modules.lrlc.invasion import GENERIC_TOOLS, forward_ra

    tool = GENERIC_TOOLS["generic_induction"]
    depth = np.linspace(1000.0, 1099.5, 200)
    rt, rxo, di = invasion_truth(depth)
    ra = forward_ra(rt, rxo, di, (tool["deep"], tool["medium"], tool["shallow"]), tool["p"])
    wave = np.sin(depth / 5.0)
    data = pd.DataFrame({
        "DEPTH": depth,
        "GR": 30.0 + 6.0 * wave,
        "RHOB": 2.30 + 0.03 * wave,
        "NPHI": 0.20 + 0.02 * wave,
        "DT": 80.0 + 3.0 * wave,
        "RT": ra[:, 0],
        "RM": ra[:, 1],
        "RS": ra[:, 2],
    })
    data.loc[[7, 21], "RS"] = np.nan
    data.loc[[48, 49], "RT"] = np.nan
    data.loc[[170, 171], "RM"] = np.nan
    return data


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
    # LRLC on without a correction step: screening, BVW, water-free flag and the Rt cutoff.
    # A zone-scoped screening threshold for LOWER; primary Simandoux.
    "lrlc_screening": {
        "builder": lrlc_screening_data,
        "params": {
            "vsh_baseline_method": "Custom (Manual)",
            "gr_min_manual": 40.0,
            "gr_max_manual": 120.0,
            "sw_methods": ["Archie", "Simandoux"],
            "sw_primary_method": "Simandoux",
            "rw": 0.06,
            "rw_mode": "manual",
            "rsh": 2.0,
            "rsh_mode": "manual",
        },
        "tops": True,
        "lrlc": {"settings": {"enabled": True, "rt_cutoff": {"enabled": True}},
                 "params": {"default": {}, "zones": {"LOWER": {"screen_rt_max": 8.0}}}},
    },
    # Laminated sand: Thomas-Stieber on in both zones, the Hagiwara step in Upper only; the
    # corrected Rt recovers the forward Sw (0.30) and the baseline columns show the uncorrected one.
    "lrlc_laminated": {
        "builder": lrlc_laminated_data,
        "params": {
            "vsh_baseline_method": "Custom (Manual)",
            "gr_min_manual": 20.0,
            "gr_max_manual": 120.0,
            "sw_methods": ["Archie"],
            "sw_primary_method": "Archie",
            "rw": 0.05,
            "rw_mode": "manual",
            "a": 1.0,
            "m": 2.0,
            "n": 2.0,
            "rsh": 2.0,
            "rsh_mode": "manual",
        },
        "tops": True,
        "lrlc": {"settings": {"enabled": True, "thomas_stieber": {"enabled": True}},
                 "params": {"default": {},
                            "zones": {"UPPER": {"rt_steps": ["laminated"],
                                                "phi_max": 0.30, "phi_sh": 0.08},
                                      "LOWER": {"phi_max": 0.30, "phi_sh": 0.08}}}},
    },
    # Pyrite: volume from RHOB and PEF, half connected, Rpy 0.1 ohm.m; the step restores the
    # resistivity of the pore system.
    "lrlc_pyrite": {
        "builder": lrlc_pyrite_data,
        "params": {
            "vsh_baseline_method": "Custom (Manual)",
            "gr_min_manual": 20.0,
            "gr_max_manual": 120.0,
            "sw_methods": ["Archie"],
            "sw_primary_method": "Archie",
            "rw": 0.05,
            "rw_mode": "manual",
            "a": 1.0,
            "m": 2.0,
            "n": 2.0,
        },
        "lrlc": {"settings": {"enabled": True, "pyrite": {"enabled": True, "u_fluid": 0.36}},
                 "params": {"default": {"rt_steps": ["pyrite"], "pyr_method": "rhob_pef",
                                        "pyr_f": 0.5, "pyr_rpy": 0.1}, "zones": {}}},
    },
    # Variable m and n: Upper in curve mode (m from porosity and clay, n from clay), Lower scalar;
    # all five Sw models, primary Simandoux.
    "lrlc_variable_mn": {
        "data": "shaly_data",
        "params": {
            "vsh_baseline_method": "Custom (Manual)",
            "gr_min_manual": 40.0,
            "gr_max_manual": 130.0,
            "vsh_methods": ALL_VSH,
            "primary_phie_method": "PHIE_N",
            "sw_methods": ALL_SW,
            "sw_primary_method": "Simandoux",
            "rw": 0.01,
            "rw_mode": "auto",
            "swirr_method": "Buckles Number",
            "nphi_matrix": 0.0,
            "lithology_preset": "Limestone",
        },
        "tops": True,
        "lrlc": {"settings": {"enabled": True},
                 "params": {"default": {},
                            "zones": {"UPPER": {"mn_mode": "curve",
                                                "m_coef": [1.9, 0.5, 0.3, 0.0],
                                                "n_model": "vsh", "n_coef": [1.8, 0.6]}}}},
    },
    # Radial invasion from the forward model of the generic induction tool: known Rt, Rxo and di
    # per interval, RM and RS mapped, missing samples, a non-unique and an out-of-range interval.
    "lrlc_invasion": {
        "builder": lrlc_invasion_data,
        "params": {
            "vsh_baseline_method": "Custom (Manual)",
            "gr_min_manual": 20.0,
            "gr_max_manual": 120.0,
            "sw_methods": ["Archie"],
            "sw_primary_method": "Archie",
            "rw": 0.05,
            "rw_mode": "manual",
            "a": 1.0,
            "m": 2.0,
            "n": 2.0,
        },
        "lrlc_curves": {"RM": "RM", "RS": "RS"},
        "lrlc": {"settings": {"enabled": True},
                 "params": {"default": {"rt_steps": ["invasion"], "inv_tool": "generic_induction",
                                        "rt_fallback": "nan"}, "zones": {}}},
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
    if spec.get("lrlc"):
        # What AppModel.params_for_well hands the pipeline when LRLC is on.
        from models.app_model import AppModel

        model = AppModel()
        model.las_data = data
        model.formation_tops = tops
        _set_lrlc(model, spec["lrlc"])
        if spec.get("lrlc_curves"):
            model._well.lrlc_curves = dict(spec["lrlc_curves"])
        params["lrlc"] = model._lrlc_params(model._well)
    if spec.get("shf"):
        # What AppModel.params_for_well hands the pipeline when saturation height is on.
        from models.app_model import AppModel

        model = AppModel()
        model.project.shf.update(copy.deepcopy(spec["shf"]["settings"]))
        params["shf"] = model._shf_params(
            SimpleNamespace(shf_contacts=copy.deepcopy(spec["shf"]["contacts"])))
    return data, mapping, params, tops


def _set_lrlc(model, lrlc):
    """Put a case's LRLC settings and ladder values on ``Project.lrlc``."""
    from modules.lrlc.config import merge_lrlc

    model.project.lrlc = merge_lrlc({**copy.deepcopy(lrlc["settings"]),
                                     "params": copy.deepcopy(lrlc["params"])})


def apply_to_model(model, name, params):
    """Set a case's params on an AppModel; definitions go to ``Project.rock_types``."""
    for key, value in params.items():
        if key in ("rock_types", "rock_core", "shf", "lrlc"):
            continue
        assert hasattr(model, key), key
        setattr(model, key, value)
    if CASES[name].get("rock_types"):
        model.project.rock_types = CASES[name]["rock_types"]
    if CASES[name].get("shf"):
        model.project.shf.update(copy.deepcopy(CASES[name]["shf"]["settings"]))
        model._well.shf_contacts = copy.deepcopy(CASES[name]["shf"]["contacts"])
    if CASES[name].get("lrlc"):
        _set_lrlc(model, CASES[name]["lrlc"])
    if CASES[name].get("lrlc_curves"):
        model._well.lrlc_curves = dict(CASES[name]["lrlc_curves"])
