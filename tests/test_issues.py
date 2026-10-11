"""P0-UI/UX U1: run issues derived from a well's last summary (services/issues.py)."""

from types import SimpleNamespace

from modules.pipeline import AUTO_UNAVAILABLE
from services.issues import Issue, collect_issues, issue_counts

CUTOFFS = {"vsh_cutoff": 0.4, "phi_cutoff": 0.1, "sw_cutoff": 0.6}


def _ds(summary=None, error=None, key="W1"):
    return SimpleNamespace(key=key, summary=summary, error=error)


def _summary(**extra):
    summary = {
        "warnings": [
            "Rsh could not be estimated automatically; using the entered Rsh of 2.0.",
            "PHIE from DENSITY covers 80 % of the samples; the rest have no porosity "
            "and are excluded from pay and HCPV",
        ],
        "rw_source": "auto",
        "rsh_source": AUTO_UNAVAILABLE,
        "zone_diagnostics": {
            "A": {"status": "no_reservoir", "cutoffs": CUTOFFS, "gross": 40.0},
            "B": {"status": "no_pay", "cutoffs": CUTOFFS, "net_reservoir": 12.0},
            "C": {"status": "ok", "cutoffs": CUTOFFS},
        },
    }
    summary.update(extra)
    return summary


def test_spec_case_gives_three_warnings_and_one_info():
    issues = collect_issues(_ds(_summary()))
    assert issue_counts(issues) == {"error": 0, "warning": 3, "info": 1}
    texts = [i.text for i in issues]
    assert len(texts) == len(set(texts))
    assert [i.severity for i in issues] == ["warning", "warning", "warning", "info"]


def test_targets_and_zones():
    issues = collect_issues(_ds(_summary()))
    by_text = {i.text[:4]: i for i in issues}
    assert by_text["Rsh "].target == "params.rw"
    assert by_text["PHIE"].target == "params.porosity"
    zoned = [i for i in issues if i.zone]
    assert {i.zone for i in zoned} == {"A", "B"}
    assert all(i.target == "diagnostics" for i in zoned)
    assert all(i.well == "W1" for i in issues)


def test_auto_fallback_without_a_warning_is_added_once():
    issues = collect_issues(_ds({"warnings": [], "rw_source": AUTO_UNAVAILABLE}))
    assert issues == [Issue("warning", "Rw could not be estimated automatically.", "W1",
                            target="params.rw")]


def test_failed_dataset_gives_one_error_first():
    issues = collect_issues(_ds(None, error="Formation X not found in this well's tops"))
    assert issue_counts(issues) == {"error": 1, "warning": 0, "info": 0}
    issues = collect_issues(_ds(_summary(), error="boom"))
    assert issues[0].severity == "error"


def test_never_run_dataset_has_no_issues():
    assert collect_issues(_ds()) == []
    assert issue_counts([]) == {"error": 0, "warning": 0, "info": 0}


def test_tops_and_solver_targets():
    issues = collect_issues(_ds({"warnings": [
        "Selected formations not in this well's tops: X",
        "Waxman-Smits: 3 no-root, 0 failed solver points.",
        "VSH defaulted to 0.3 because no GR curve was available.",
    ]}))
    assert [i.target for i in issues] == ["tops", "diagnostics", None]
