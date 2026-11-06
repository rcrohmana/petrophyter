"""Variable m / n: formulas, the carbonate gate, build_mn_curves, settings and issue codes."""

import numpy as np
import pytest

from modules.issue_codes import ISSUE_CODES
from modules.lrlc import variable_mn as vm
from modules.lrlc.config import (
    L3_PARAM_KEYS, LRLC_PARAM_DEFAULTS, clean_param, lrlc_defaults, merge_lrlc, resolve_lrlc)


def _curve(**kw):
    base = {"mn_mode": "curve", "m_model": "formula", "m_coef": [1.9, 0.5, 0.3, 0.0],
            "shell_confirm": False, "n_model": "constant", "n_coef": [2.0, 0.0]}
    base.update(kw)
    return base


def _build(phi, vsh, settings, lithology="Sandstone (Humble)", labels=None, sm=2.15, sn=2.0,
           clip=(1.0, 4.0)):
    phi = np.atleast_1d(np.asarray(phi, dtype=float))
    vsh = np.broadcast_to(np.asarray(vsh, dtype=float), phi.shape).copy()
    labels = np.array(["Z"] * phi.size, dtype=object) if labels is None else labels
    return vm.build_mn_curves(phi, vsh, labels, settings, sm, sn, clip, clip, lithology)


def test_worked_formula_check():
    assert vm.m_formula(0.20, 0.30, [1.9, 0.5, 0.3, 0.0]) == pytest.approx(2.09, abs=1e-12)


def test_shell_worked_checks():
    got = vm.shell_m(np.array([0.05, 0.10, 0.20]))
    assert got == pytest.approx([2.25, 2.06, 1.965], abs=1e-12)
    assert vm.m_formula(0.10, 0.5, [1.87, 0, 0, 0.019]) == pytest.approx(2.06)


def test_m_formula_per_row_coefficients():
    coef = np.array([[2.0, 0, 0, 0], [1.0, 1.0, 0, 0]])
    out = vm.m_formula(np.array([0.1, 0.2]), np.array([0.0, 0.0]), coef)
    assert out == pytest.approx([2.0, 1.2])


def test_n_formula():
    assert vm.n_formula(np.array([0.0, 0.5]), [1.8, 0.6]) == pytest.approx([1.8, 2.1])
    assert vm.n_formula(0.5, np.array([[2.0, 1.0], [1.0, 0.0]])) == pytest.approx([2.5, 1.0])


def test_curve_mode_formula_and_n_vsh():
    st = {"Z": _curve(n_model="vsh", n_coef=[1.8, 0.6])}
    r = _build([0.20], [0.30], st)
    assert r.m[0] == pytest.approx(2.09)
    assert r.n[0] == pytest.approx(1.98)
    assert r.m_valid[0] and r.n_valid[0]
    assert r.counts["Z"]["n_eval"] == 1 and r.counts["Z"]["n_fallback"] == 0
    assert r.any_curve


def test_default_coefficients_are_identity_for_default_m():
    st = {"Z": _curve(m_coef=[2.15, 0, 0, 0])}
    r = _build([0.1, 0.2, 0.3], [0.1, 0.2, 0.3], st, sm=2.15)
    assert np.array_equal(r.m, np.full(3, 2.15))


def test_scalar_zone_keeps_scalar_values():
    r = _build([0.1, 0.2], [0.1, 0.2], {"Z": {"mn_mode": "scalar"}}, sm=1.9, sn=1.7)
    assert np.array_equal(r.m, [1.9, 1.9]) and np.array_equal(r.n, [1.7, 1.7])
    assert not r.m_valid.any() and not r.n_valid.any()
    assert not r.any_curve
    assert _build([0.1], [0.1], {}).counts["Z"]["mode"] == "scalar"


def test_shell_refused_outside_carbonate_with_code():
    st = {"Z": _curve(m_model="shell")}
    r = _build([0.05, 0.10], [0.1, 0.1], st, lithology="Sandstone (Humble)", sm=2.15)
    assert np.array_equal(r.m, [2.15, 2.15])
    assert not r.m_valid.any()
    assert r.counts["Z"]["shell_refused"] == 2
    issues = vm.mn_issues(r)
    shell = [i for i in issues if i["code"] == "LRLC_MN_SHELL_LITHOLOGY"]
    assert len(shell) == 1 and shell[0]["severity"] == "warning"
    assert all(i["code"] in ISSUE_CODES for i in issues)


def test_shell_evaluated_in_carbonate_zone():
    st = {"Z": _curve(m_model="shell")}
    r = _build([0.05, 0.10, 0.20], [0.0, 0.0, 0.0], st, lithology={"Z": "Carbonate"})
    assert r.m == pytest.approx([2.25, 2.06, 1.965])
    assert r.counts["Z"]["shell_refused"] == 0
    assert not any(i["code"] == "LRLC_MN_SHELL_LITHOLOGY" for i in vm.mn_issues(r))


def test_shell_confirmed_outside_carbonate_is_info():
    st = {"Z": _curve(m_model="shell", shell_confirm=True)}
    r = _build([0.10], [0.0], st, lithology="Sandstone (Humble)")
    assert r.m[0] == pytest.approx(2.06)
    shell = [i for i in vm.mn_issues(r) if i["code"] == "LRLC_MN_SHELL_LITHOLOGY"]
    assert len(shell) == 1 and shell[0]["severity"] == "info"


def test_fallback_for_nan_and_low_porosity():
    st = {"Z": _curve(n_model="vsh", n_coef=[1.8, 0.6])}
    phi = [0.20, np.nan, 0.01, 0.20]
    vsh = [0.30, 0.30, 0.30, np.nan]
    r = _build(phi, vsh, st, sm=2.5, sn=1.5)
    assert np.isfinite(r.m).all() and np.isfinite(r.n).all()
    assert r.m[0] == pytest.approx(2.09)
    assert list(r.m[1:]) == [2.5, 2.5, 2.5] and list(r.n[1:]) == [1.5, 1.5, 1.5]
    assert list(r.m_valid) == [True, False, False, False]
    c = r.counts["Z"]
    assert (c["n_samples"], c["n_eval"], c["n_fallback"]) == (4, 1, 3)
    codes = {i["code"]: i["severity"] for i in vm.mn_issues(r)}
    assert codes["LRLC_MN_FALLBACK"] == "warning"


def test_fallback_info_below_five_percent():
    st = {"Z": _curve()}
    phi = np.full(100, 0.2)
    phi[0] = np.nan
    r = _build(phi, 0.1, st)
    sev = {i["code"]: i["severity"] for i in vm.mn_issues(r)}
    assert sev["LRLC_MN_FALLBACK"] == "info"


def test_clipping_counts_and_severity():
    st = {"Z": _curve(m_coef=[5.0, 0, 0, 0])}   # always 5 -> clipped to 4
    r = _build([0.1, 0.2], [0.1, 0.2], st)
    assert np.array_equal(r.m, [4.0, 4.0])
    c = r.counts["Z"]
    assert c["n_clipped_m"] == 2 and c["m_raw_max"] == pytest.approx(5.0)
    sev = [i for i in vm.mn_issues(r, 0.05) if i["code"] == "LRLC_MN_CLIPPED"]
    assert sev[0]["severity"] == "warning"
    assert vm.mn_issues(r, 1.0)[0]["severity"] == "info"


def test_n_clipped_and_nan_free():
    st = {"Z": _curve(n_model="vsh", n_coef=[1.0, -3.0])}
    r = _build([0.2, 0.2], [0.0, 1.0], st)
    assert list(r.n) == [1.0, 1.0] and r.counts["Z"]["n_clipped_n"] == 1


def test_per_zone_arrays():
    labels = np.array(["A", "A", "B", "B"], dtype=object)
    st = {"A": _curve(m_coef=[1.9, 0.5, 0.3, 0]), "B": {"mn_mode": "scalar"}}
    r = _build([0.2] * 4, [0.3] * 4, st, labels=labels, sm=2.4)
    assert r.m == pytest.approx([2.09, 2.09, 2.4, 2.4])
    assert r.counts["A"]["mode"] == "curve" and r.counts["B"]["mode"] == "scalar"
    pct = vm.curve_percentiles(r, labels)
    assert set(pct) == {"A"} and pct["A"]["m_p50"] == pytest.approx(2.09)


def test_scalar_values_may_be_arrays():
    r = _build([0.2, 0.2], [0.3, 0.3], {"Z": {"mn_mode": "scalar"}}, sm=np.array([2.0, 2.2]))
    assert list(r.m) == [2.0, 2.2]


@pytest.mark.parametrize("bad", [
    {"m_coef": [1.9, 0.5]}, {"m_coef": [1.9, np.nan, 0, 0]}, {"m_coef": None},
    {"mn_mode": "other"}, {"m_model": "nope"}, {"n_model": "vsh", "n_coef": [1.0]},
])
def test_invalid_settings_fall_back_to_scalar(bad):
    r = _build([0.2], [0.3], {"Z": _curve(**bad)}, sm=2.3, sn=1.9)
    assert r.m[0] == 2.3 and r.n[0] == 1.9
    assert r.counts["Z"]["invalid_setting"] and r.counts["Z"]["mode"] == "scalar"
    assert [i["code"] for i in vm.mn_issues(r)] == ["LRLC_MN_SETTING_INVALID"]


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        vm.build_mn_curves([0.1, 0.2], [0.1], np.array(["Z", "Z"], dtype=object), {}, 2.0, 2.0,
                           (1, 4), (1, 4), None)


# ---- configuration keys ---------------------------------------------------------------
def test_issue_codes_registered():
    for code in ("LRLC_MN_CLIPPED", "LRLC_MN_FALLBACK", "LRLC_MN_SHELL_LITHOLOGY",
                 "LRLC_MN_SETTING_INVALID"):
        assert code in ISSUE_CODES
    assert ISSUE_CODES["LRLC_MN_SHELL_LITHOLOGY"][0] == "warning"
    assert ISSUE_CODES["LRLC_MN_CLIPPED"][1] == "lrlc.remediation.variable_mn"


def test_param_defaults_and_ladder():
    d = LRLC_PARAM_DEFAULTS
    assert d["mn_mode"] == "scalar" and d["m_coef"] == [2.15, 0.0, 0.0, 0.0]
    assert d["n_coef"] == [2.0, 0.0] and d["rmf"] is None and d["inv_di_max"] == 120.0
    assert set(L3_PARAM_KEYS) <= set(d)
    zone = resolve_lrlc({"default": {"mn_mode": "curve"}, "zones": {}}, {}, "Upper")
    assert zone["mn_mode"] == "curve"


@pytest.mark.parametrize("key,value,ok", [
    ("mn_mode", "curve", True), ("mn_mode", "other", False),
    ("m_model", "shell", True), ("n_model", "vsh", True), ("phi_source", "phit", True),
    ("phi_source", "PHIE", False),
    ("shell_confirm", True, True), ("shell_confirm", 1, False),
    ("m_coef", [1.9, 0.5, 0.3, 0], True), ("m_coef", [1.9, 0.5, 0.3], False),
    ("m_coef", [6.0, 0, 0, 0], False), ("m_coef", [2.0, 0, 0, 0.6], False),
    ("m_coef", [2.0, 0, 0, float("nan")], False), ("m_coef", "x", False),
    ("n_coef", [2.0, 1.0], True), ("n_coef", [0.5, 0.0], False),
    ("inv_tool", "custom", True), ("inv_tool", "vendor", False),
    ("inv_r50", {"deep": 80, "medium": 45, "shallow": 20}, True),
    ("inv_r50", {"deep": 80, "medium": 45}, False), ("inv_r50", None, True),
    ("inv_r50", {"deep": 500, "medium": 45, "shallow": 20}, False),
    ("inv_p", 2.5, True), ("inv_p", 0.5, False), ("inv_rxo_mode", "ignore", True),
    ("inv_di_min", 3.0, False), ("inv_di_max", 300.0, True), ("inv_di_max", 301.0, False),
    ("inv_min_contrast", 1.0, False), ("inv_max_rms", 1.0, True),
    ("rmf", None, True), ("rmf", 0.35, True), ("rmf", 0.001, False),
    ("rmf_temp", 68, True), ("rmf_temp", 20, False),
])
def test_clean_param_new_keys(key, value, ok):
    out, valid = clean_param(key, value)
    assert valid is ok
    if ok and value is not None and key not in ("inv_r50",):
        assert out == (value if not isinstance(value, (int, float)) or isinstance(value, bool)
                       else float(value)) or key in ("m_coef", "n_coef")


def test_blocks_defaults_and_tolerant_merge():
    d = lrlc_defaults()
    assert d["variable_mn"]["clip_m"] == [1.0, 4.0]
    assert d["variable_mn"]["fit"]["min_points_per_param"] == 15
    assert d["invasion"] == {"rt_bounds": [0.05, 20000.0], "chunk": 20000, "max_iter": 40}
    out = merge_lrlc({"variable_mn": {
        "clip_m": [1.2, 3.5], "clip_n": [4.0, 1.0], "clip_warn_fraction": 2.0,
        "fit": {"min_points_per_param": 20, "phi_window": [0.6, 0.03], "f_scale": "x"}},
        "invasion": {"chunk": 5000, "max_iter": 0}})
    vmn = out["variable_mn"]
    assert vmn["clip_m"] == [1.2, 3.5] and vmn["clip_n"] == [1.0, 4.0]
    assert vmn["clip_warn_fraction"] == 0.05
    assert vmn["fit"]["min_points_per_param"] == 20
    assert vmn["fit"]["phi_window"] == [0.03, 0.60] and vmn["fit"]["f_scale"] == 0.1
    assert out["invasion"]["chunk"] == 5000 and out["invasion"]["max_iter"] == 40
    assert merge_lrlc(None) == lrlc_defaults()


def test_summary_params_do_not_gain_keys_at_defaults():
    from modules.lrlc.stage import _summary_params
    resolved = {"default": dict(resolve_lrlc({}, {}, None)), "zones": {}}
    out = _summary_params(resolved)
    assert not set(out["default"]) & set(L3_PARAM_KEYS)
    resolved["default"]["mn_mode"] = "curve"
    assert _summary_params(resolved)["default"]["mn_mode"] == "curve"


def test_no_internal_ids_in_module_text():
    import re
    text = open(vm.__file__, encoding="utf-8").read()
    assert not re.search(r"(?<!soft )\b(L[1-4]|S[1-8]|A[1-4]|B[1-3])\b|spec", text)
