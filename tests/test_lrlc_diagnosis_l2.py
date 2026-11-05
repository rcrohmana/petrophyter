import numpy as np
import pandas as pd
import pytest

from modules.lrlc import diagnosis as dg
from modules.lrlc.config import DIAGNOSIS_DEFAULTS, GUARD_DEFAULTS

TH = dict(DIAGNOSIS_DEFAULTS)
GS = dict(GUARD_DEFAULTS)


def frame(n=20, **cols):
    d = {"NET_RES_FLAG": np.ones(n)}
    d.update({k: (np.full(n, v) if np.isscalar(v) else np.asarray(v, float)) for k, v in cols.items()})
    return pd.DataFrame(d)


def evidence(fr, ts=None, qv=None, rw=0.1, **kw):
    args = dict(sw_cutoff=0.6, screen_rt_max=5.0, a=1.0, m=2.0, rw_eff=rw, ts_stats=ts,
                qv_value=qv, min_n=10)
    args.update(kw)
    return dg.zone_evidence(fr, np.full(len(fr), 0.5), **args)


def keys(res, level=None):
    return [c["key"] for c in res["causes"] if level is None or c["level"] == level]


def test_evidence_weighted_median_and_selection():
    fr = pd.DataFrame({"NET_RES_FLAG": [1, 1, 1, 0], "SW": [0.2, 0.9, 0.9, 0.0],
                       "RT": [10, 10, 10, 10], "PHIT": [0.2] * 4})
    ev = dg.zone_evidence(fr, np.array([1.0, 1.0, 5.0, 1.0]), sw_cutoff=0.6, screen_rt_max=5.0,
                          a=1.0, m=2.0, rw_eff=0.1, ts_stats=None, qv_value=None, min_n=1)
    assert ev["n_res"] == 3
    assert ev["thickness_ft"] == pytest.approx(7.0)
    assert ev["sw_median"] == pytest.approx(0.9)       # weight 5 of 7 sits at 0.9
    assert ev["rt_ro_median"] == pytest.approx(10 / (0.1 / 0.04))
    assert ev["vpyr_median"] is None and ev["pef_median"] is None


def test_laminated_fires():
    ts = {"lam_share": 0.62, "mean_vlam": 0.12, "class13_share": 0.7}
    res = dg.diagnose_zone(evidence(frame(), ts=ts), TH, GS)
    assert res["status"] == "ok" and res["primary"] == "laminated"
    c = res["causes"][0]
    assert c["level"] == "probable" and c["score"] == 1.0 and c["n_eval"] == 3
    assert c["criteria"][0] == {"id": "lam_share", "value": 0.62, "op": ">=",
                                "threshold": GS["vlam_share"], "met": True}
    assert res["guard"] == {"laminated": True, "lam_share": 0.62}
    assert res["ts"]["lam_share"] == 0.62


def test_microporosity_fires():
    fr = frame(SW=0.8, WATER_FREE_FLAG=1.0, BVW=0.10)
    res = dg.diagnose_zone(evidence(fr), TH, GS)
    assert "microporosity" in keys(res, "probable")
    crit = next(c for c in res["causes"] if c["key"] == "microporosity")["criteria"]
    assert [c["met"] for c in crit] == [True, True, True]      # cv 0 <= 0.2


def test_saline_fires():
    fr = frame(RT=1.0, PHIT=0.25)
    res = dg.diagnose_zone(evidence(fr, rw=0.03), TH, GS)
    assert res["primary"] == "saline"
    # Rt/Ro = 1 / (0.03/0.0625) = 2.08 <= 3
    assert next(c for c in res["causes"] if c["key"] == "saline")["score"] == 1.0


def test_conductive_mineral_one_of_one():
    res = dg.diagnose_zone(evidence(frame(VPYR=0.03)), TH, GS)
    c = next(c for c in res["causes"] if c["key"] == "conductive_mineral")
    assert c["n_eval"] == 1 and c["level"] == "probable"
    assert res["primary"] == "conductive_mineral"
    res = dg.diagnose_zone(evidence(frame(VPYR=0.03, PEF=2.0)), TH, GS)
    c = next(c for c in res["causes"] if c["key"] == "conductive_mineral")
    assert c["score"] == 0.5 and c["level"] == "possible"
    assert res["primary"] is None


def test_clay_conductivity_fires_and_qv_source():
    fr = frame(VSH=0.25, SW=0.5, SW_ARCHIE=0.8)
    res = dg.diagnose_zone(evidence(fr, qv=0.5), TH, GS)
    assert res["primary"] == "clay_conductivity"
    assert res["causes"][0]["criteria"][0]["value"] == 0.5
    # QV_EST in the frame takes precedence over the scalar
    fr2 = frame(VSH=0.25, QV_EST=0.1)
    ev = evidence(fr2, qv=0.9)
    assert ev["qv"] == pytest.approx(0.1)


def test_not_evaluable_excluded():
    # Only vsh evaluable for clay (no qv, no SW_ARCHIE) -> 1 of 1 evaluable is not enough
    res = dg.diagnose_zone(evidence(frame(VSH=0.3)), TH, GS)
    assert res["causes"] == [] or "clay_conductivity" not in keys(res, "probable")
    ev = evidence(frame(VSH=0.3, SW=0.5, SW_ARCHIE=0.9))
    r = dg.diagnose_zone(ev, TH, GS)
    c = next(c for c in r["causes"] if c["key"] == "clay_conductivity")
    qv_crit = c["criteria"][0]
    assert qv_crit["met"] is None and qv_crit["value"] is None
    assert c["n_eval"] == 2 and c["score"] == 1.0


def test_levels_and_score_cutoffs():
    # 2 of 3 counts as 0.67 -> probable
    ts = {"lam_share": 0.8, "mean_vlam": 0.2, "class13_share": 0.0}
    c = dg.diagnose_zone(evidence(frame(), ts=ts), TH, GS)["causes"][0]
    assert c["level"] == "probable" and c["score"] == pytest.approx(2 / 3)
    # 1 of 3 is below the possible cut-off -> not listed
    ts = {"lam_share": 0.8, "mean_vlam": 0.0, "class13_share": 0.0}
    assert dg.diagnose_zone(evidence(frame(), ts=ts), TH, GS)["causes"] == []
    # 1 of 2 evaluable -> possible, no primary
    res = dg.diagnose_zone(evidence(frame(SW=0.8, WATER_FREE_FLAG=0.0)), TH, GS)
    c = res["causes"][0]
    assert c["key"] == "microporosity" and c["level"] == "possible" and c["score"] == 0.5
    assert res["primary"] is None


def test_ties_follow_table_order():
    ts = {"lam_share": 0.9, "mean_vlam": 0.2, "class13_share": 0.9}
    fr = frame(VPYR=0.05, PEF=6.0)
    res = dg.diagnose_zone(evidence(fr, ts=ts), TH, GS)
    assert keys(res, "probable") == ["laminated", "conductive_mineral"]
    assert res["primary"] == "laminated"
    # higher score beats earlier order
    ts2 = {"lam_share": 0.9, "mean_vlam": 0.2, "class13_share": 0.0}   # 2/3
    res = dg.diagnose_zone(evidence(fr, ts=ts2), TH, GS)
    assert res["primary"] == "conductive_mineral"


def test_insufficient():
    res = dg.diagnose_zone(evidence(frame(n=5, VPYR=0.1)), TH, GS)
    assert res["status"] == "insufficient" and res["primary"] is None and res["causes"] == []
    assert res["n_res"] == 5
    assert dg.lrlc_note(res) is None
    empty = dg.zone_evidence(pd.DataFrame({"X": []}), np.array([]), sw_cutoff=0.6,
                             screen_rt_max=5.0, a=1.0, m=2.0, rw_eff=0.1, ts_stats=None,
                             qv_value=None, min_n=10)
    assert empty["n_res"] == 0
    assert dg.diagnose_zone(empty, TH, GS)["status"] == "insufficient"


def test_note_text():
    ts = {"lam_share": 0.62, "mean_vlam": 0.12, "class13_share": 0.7}
    res = dg.diagnose_zone(evidence(frame(), ts=ts), TH, GS)
    assert dg.lrlc_note(res) == "LRLC: probable laminated sand (Vlam share 0.62); see Remediation."
    res = dg.diagnose_zone(evidence(frame(VPYR=0.03)), TH, GS)
    assert dg.lrlc_note(res) == "LRLC: probable conductive minerals; see Remediation."
    assert dg.lrlc_note({"primary": None}) is None


def test_remedy_mapping():
    r = dg._remedy
    assert r("laminated")["rt_steps"] == ["laminated"] and r("laminated")["sw_basis"] == "sand"
    assert r("conductive_mineral")["rt_steps"] == ["pyrite"]
    assert r("clay_conductivity")["qv_source"] == "estimate"
    assert "Dual-Water" in r("clay_conductivity")["sw_models"]
    assert r("microporosity")["rt_steps"] == [] and r("saline")["rt_steps"] == []
    out = r("laminated")
    out["rt_steps"].append("x")
    assert r("laminated")["rt_steps"] == ["laminated"]       # copies, not shared state
    res = dg.diagnose_zone(evidence(frame(VPYR=0.03)), TH, GS)
    assert res["causes"][0]["remedy"]["rt_steps"] == ["pyrite"]


def test_array_rw():
    fr = frame(RT=1.0, PHIT=0.25)
    ev = evidence(fr, rw=np.full(len(fr), 0.03))
    assert ev["rw_median"] == pytest.approx(0.03)
