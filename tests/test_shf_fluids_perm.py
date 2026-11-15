"""Saturation-height notes: permeability from the resistivity Sw, built-in fluids, export columns."""

import copy

import numpy as np
import pandas as pd
import pytest

from models.app_model import AppModel
from modules.shf import BASIS_LOG
from modules.shf_stage import (
    describe_fluids, fluids_at_defaults, perm_from_resistivity, perm_from_resistivity_text)
from services.export_service import SHF_COLUMNS, well_shf_rows

from tests.test_shf_pipeline import fit_dict, issue_codes, log, run, shf_p  # noqa: F401


def issues_of(summary, code):
    return [i for i in summary["issues"] if i["code"] == code]


def confirmed(**over):
    return shf_p(fluids_confirmed=True, **over)


# ---- permeability from the resistivity Sw ---------------------------------------------------
def test_pay_with_a_log_permeability_names_the_column(log):
    _, summary = run(log, confirmed(use_for_pay=True))
    perm = summary["shf"]["perm_source"]
    assert perm in ("PERM_TIMUR", "PERM_WR")
    (issue,) = issues_of(summary, "SHF_PERM_FROM_RT")
    assert issue["severity"] == "warning" and issue["target"] == "diagnostics"
    assert issue["text"] == (
        f"Saturation-height Sw is used for pay with permeability {perm}, which is calculated "
        "from the resistivity Sw (through Swirr), so the pay Sw is not independent of "
        "resistivity. Check the pay against the resistivity Sw, or use a core-based "
        "permeability.")


def test_no_note_when_pay_is_not_requested(log):
    _, summary = run(log, confirmed(use_for_pay=False))
    assert issues_of(summary, "SHF_PERM_FROM_RT") == []


def test_no_note_when_pay_is_refused_for_a_log_fit(log):
    _, summary = run(log, confirmed(fits={"All": fit_dict(basis=BASIS_LOG)}, use_for_pay=True))
    assert summary["shf"]["pay_refused"] is True
    assert issues_of(summary, "SHF_PERM_FROM_RT") == []


def test_chosen_perm_column_is_the_one_named(log):
    results, _ = run(log, confirmed(use_for_pay=True))
    other = "PERM_WR" if "PERM_WR" in results.columns else None
    if other is None:
        pytest.skip("no second permeability column in this run")
    _, summary = run(log, confirmed(use_for_pay=True, perm_source=other))
    assert f"permeability {other}," in issues_of(summary, "SHF_PERM_FROM_RT")[0]["text"]


def frame(sources, sw=0.5):
    return pd.DataFrame({"SW_SHF": [sw] * len(sources), "ROCK_TYPE_SOURCE": sources})


def test_helper_log_columns_count_every_modelled_sample():
    results = frame(["core", "core", "log"])
    results.loc[2, "SW_SHF"] = np.nan
    assert perm_from_resistivity("PERM_TIMUR", results) == (2, 2)
    assert perm_from_resistivity("PERM_WR", results) == (2, 2)
    assert perm_from_resistivity("PERM_CORE", results) is None
    assert perm_from_resistivity(None, results) is None


def test_helper_perm_rt_counts_samples_with_a_log_rock_type():
    assert perm_from_resistivity("PERM_RT", frame(["log", "log", "core", "core"])) == (2, 4)
    assert perm_from_resistivity("PERM_RT", frame(["core", "core"])) is None
    results = frame(["log", "log", "core"])
    results.loc[0, "SW_SHF"] = np.nan                # not modelled: not counted
    assert perm_from_resistivity("PERM_RT", results) == (1, 2)
    assert perm_from_resistivity("PERM_RT", results[["SW_SHF"]]) is None


def test_perm_rt_text():
    assert perm_from_resistivity_text("PERM_RT", (120, 180)) == (
        "Saturation-height Sw is used for pay with permeability PERM_RT; 120 of 180 samples take "
        "their rock type from the logs, which is calculated from the resistivity Sw (through "
        "Swirr), so the pay Sw is not independent of resistivity. Check the pay against the "
        "resistivity Sw, or use a core-based permeability.")


# ---- built-in fluids -------------------------------------------------------------------------
BUILT_IN = "water 1.03 g/cc, oil 0.75 g/cc, 26 dyne/cm"


def test_built_in_fluids_are_info_without_pay(log):
    _, summary = run(log, shf_p())
    (issue,) = issues_of(summary, "SHF_FLUIDS_DEFAULT")
    assert issue["severity"] == "info" and issue["target"] == "diagnostics"
    assert issue["text"] == (
        f"Saturation height uses the built-in fluid densities and interfacial tension "
        f"({BUILT_IN}); enter your reservoir values or confirm them on the Saturation-Height "
        "tab.")


def test_built_in_fluids_are_a_warning_when_pay_uses_the_shf_sw(log):
    _, summary = run(log, shf_p(use_for_pay=True))
    (issue,) = issues_of(summary, "SHF_FLUIDS_DEFAULT")
    assert issue["severity"] == "warning"
    assert issue["text"] == (
        f"Saturation-height Sw is used for pay with the built-in fluid densities and "
        f"interfacial tension ({BUILT_IN}). Enter your reservoir values or press Confirm on "
        "the Saturation-Height tab.")


def test_pay_requested_but_refused_stays_info(log):
    _, summary = run(log, shf_p(fits={"All": fit_dict(basis=BASIS_LOG)}, use_for_pay=True))
    (issue,) = issues_of(summary, "SHF_FLUIDS_DEFAULT")
    assert issue["severity"] == "info"


def test_no_note_once_confirmed(log):
    _, summary = run(log, confirmed())
    assert issues_of(summary, "SHF_FLUIDS_DEFAULT") == []


@pytest.mark.parametrize("fluids, sigma", [
    ({"water": 1.03, "oil": 0.80, "gas": 0.25}, {"oil": 26.0, "gas": 50.0}),
    ({"water": 1.05, "oil": 0.75, "gas": 0.25}, {"oil": 26.0, "gas": 50.0}),
    ({"water": 1.03, "oil": 0.75, "gas": 0.25}, {"oil": 30.0, "gas": 50.0}),
])
def test_an_edited_value_clears_the_note(log, fluids, sigma):
    _, summary = run(log, shf_p(fluids=fluids, sigma_cos_res=sigma))
    assert issues_of(summary, "SHF_FLUIDS_DEFAULT") == []


def test_a_contact_with_its_own_water_density_clears_the_note(log):
    contacts = {"datum": "TVD", "kb_ft": None,
                "default": {"fwl": 1090.0, "fluid": "oil", "water_density": 1.1}, "zones": {}}
    _, summary = run(log, shf_p(contacts=contacts))
    assert issues_of(summary, "SHF_FLUIDS_DEFAULT") == []


def test_only_the_fluids_in_use_are_named(log):
    gas = {"datum": "TVD", "kb_ft": None, "default": {"fwl": 1090.0, "fluid": "gas"}, "zones": {}}
    _, summary = run(log, shf_p(contacts=gas))
    (issue,) = issues_of(summary, "SHF_FLUIDS_DEFAULT")
    assert "(water 1.03 g/cc, gas 0.25 g/cc, 50 dyne/cm)" in issue["text"]
    assert "oil" not in issue["text"]


def test_helpers_on_two_fluids():
    used = {"UPPER": {"fluid": "oil", "water_density": 1.03, "fluid_density": 0.75,
                      "sigma_cos": 26.0},
            "LOWER": {"fluid": "gas", "water_density": 1.03, "fluid_density": 0.25,
                      "sigma_cos": 50.0}}
    assert describe_fluids(used) == (
        "water 1.03 g/cc, oil 0.75 g/cc, gas 0.25 g/cc, 26 dyne/cm (oil), 50 dyne/cm (gas)")
    assert fluids_at_defaults({}, used) is True
    assert fluids_at_defaults({"fluids_confirmed": True}, used) is False
    assert fluids_at_defaults({}, {}) is False
    used["LOWER"]["sigma_cos"] = 45.0
    assert fluids_at_defaults({}, used) is False


def test_sigma_cos_is_in_the_summary_per_contact(log):
    _, summary = run(log, shf_p(sigma_cos_res={"oil": 31.5, "gas": 50.0}))
    (contact,) = summary["shf"]["fluids"].values()
    assert contact["sigma_cos"] == 31.5 and contact["fluid"] == "oil"


def test_confirmed_flag_enters_the_parameters_and_the_stale_hash():
    model = AppModel()
    model.project.shf["enabled"] = True
    before = model.well_params_hash()
    assert "fluids_confirmed" not in model.params_for_well()["shf"]
    model.project.shf["fluids_confirmed"] = True
    assert model.params_for_well()["shf"]["fluids_confirmed"] is True
    assert model.well_params_hash() != before


# ---- export ----------------------------------------------------------------------------------
def test_export_rows_carry_fluid_density_and_sigma_cos(log):
    _, summary = run(log, shf_p(sigma_cos_res={"oil": 31.5, "gas": 50.0}))
    shf = copy.deepcopy(summary["shf"])
    zone = next(iter(shf["fluids"]))
    shf["stats"]["zones"] = [{"zone": zone, "n": 3, "bias": 0.01, "rmse": 0.02, "mae": 0.02,
                              "r2": 0.9, "basis": "core_pc"}]
    rows = well_shf_rows(shf, "A")
    columns = SHF_COLUMNS
    assert columns.index("Fluid density") == columns.index("Water density") + 1
    assert columns.index("Sigma cos") == columns.index("Delta rho") + 1
    assert all(len(r) == len(columns) for r in rows)
    zone_rows = [r for r in rows if r[columns.index("Fluid")]]
    assert zone_rows
    for r in zone_rows:
        assert r[columns.index("Fluid density")] == pytest.approx(0.75)
        assert r[columns.index("Sigma cos")] == pytest.approx(31.5)
        assert r[columns.index("Delta rho")] == pytest.approx(0.28)
    well_row = rows[0]
    assert well_row[columns.index("Sigma cos")] != well_row[columns.index("Sigma cos")]   # NaN
