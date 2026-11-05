"""Closed list of run issue codes and the collector the pipeline fills (U1.2).

Pure (no Qt, no pipeline import). Every message the pipeline raises goes through
:meth:`IssueLog.add` with a code from :data:`ISSUE_CODES`; an unknown code is a
programming error. ``summary["issues"]`` holds the structured records;
``summary["warnings"]`` keeps the texts of the warning and error ones only, for
readers older than v1.7.2 (info texts are never in it).
"""

from typing import Dict, List, Optional, Tuple

SEVERITIES = ("error", "warning", "info")

# code -> (default severity, default target). Targets are "page.group.field" strings
# understood by MainWindow._on_goto_target; "diagnostics" is the Diagnostics tab.
ISSUE_CODES: Dict[str, Tuple[str, Optional[str]]] = {
    # Input curves
    "RT_NONPOSITIVE": ("warning", None),
    "RHOB_NONPOSITIVE": ("warning", None),
    "DT_NONPOSITIVE": ("warning", None),
    "INPUT_RENAMED": ("warning", None),
    "VSH_DEFAULTED": ("warning", None),
    "SHALE_POINT_UNAVAILABLE": ("warning", None),
    # Porosity
    "NPHI_PERCENT": ("warning", "params.porosity"),
    "PHIT_UNAVAILABLE": ("warning", "params.porosity"),
    "PHIE_NO_VALID": ("warning", "params.porosity"),
    "PHIE_SUBSTITUTED": ("warning", "params.porosity"),
    # Rw / Rsh
    "RW_AUTO_UNAVAILABLE": ("warning", "params.rw.rw_value"),
    "RW_AUTO_NO_WATER": ("warning", "params.rw.rw_value"),
    "RW_AUTO_UNIFORM": ("warning", "params.rw.rw_value"),
    "RW_AUTO_CLAMPED": ("warning", "params.rw.rw_value"),
    "RW_AUTO_NOTE": ("warning", "params.rw.rw_value"),
    "RSH_AUTO_UNAVAILABLE": ("warning", "params.rw.rsh_value"),
    "RSH_AUTO_FEW_SHALE": ("warning", "params.rw.rsh_value"),
    "RSH_AUTO_CLAMPED": ("warning", "params.rw.rsh_value"),
    "RSH_AUTO_NOTE": ("warning", "params.rw.rsh_value"),
    # Rock typing (only when the feature is on)
    "ROCK_TYPES_UNCORED": ("warning", None),
    "ROCK_TYPES_NO_DEFINITIONS": ("warning", None),
    "PERM_PRIMARY_FALLBACK": ("warning", None),
    # Tops and zones
    "FORMATION_MISSING": ("warning", "tops"),
    "FORMATION_OVERLAP": ("warning", "tops"),
    "ZONE_NO_SHALE": ("info", "diagnostics"),
    # Temperature
    "TEMPERATURE_NOTE": ("warning", None),
    "WS_B_RW_UNCORRECTED": ("warning", None),
    # Saturation and solver
    "SW_DEFAULTED_NO_METHOD": ("warning", "params.sat"),
    "SW_DEFAULTED_NO_RT": ("warning", None),
    "BVH_CAPPED": ("warning", "diagnostics"),
    "PHIE_ABOVE_PHIT": ("warning", "diagnostics"),
    "SW_AT_BOUND": ("warning", "diagnostics"),
    "SW_NO_PHIT": ("warning", "diagnostics"),
    "SOLVER_FAILED": ("warning", "diagnostics"),
    # Swirr (counts are info below SWIRR_COUNT_SHARE of the samples with a Swirr)
    "SWIRR_FLOOR": ("info", "params.swirr"),
    "SWIRR_LIMITED": ("info", "params.swirr"),
    "SWIRR_MAXED": ("info", "params.swirr"),
    "SWIRR_FALLBACK": ("warning", "params.swirr"),
    # Saturation-height model
    "SHF_NO_CONTACT": ("warning", "diagnostics"),
    "SHF_NO_MODEL": ("warning", "diagnostics"),
    "SHF_NO_PERM_PHI": ("warning", "diagnostics"),
    "SHF_UNCLASSIFIED": ("warning", "diagnostics"),
    "SHF_TVD_NOTE": ("warning", "diagnostics"),
    "SHF_TVDSS_SUSPECT": ("warning", "diagnostics"),
    "SHF_PAY_FALLBACK": ("warning", "diagnostics"),
    "SHF_PAY_REFUSED": ("warning", "diagnostics"),
    "SHF_ZONE_SCOPE_RT": ("info", "diagnostics"),
    # LRLC (opt-in low-resistivity low-contrast layer)
    "LRLC_STEP_UNKNOWN": ("warning", None),
    "LRLC_STEP_INVALID": ("warning", "diagnostics"),
    "LRLC_STEP_FALLBACK": ("warning", "diagnostics"),
    "LRLC_NO_RT": ("info", None),
    "LRLC_AUX_MISSING": ("warning", None),
    "LRLC_AUX_NONPOSITIVE": ("info", None),
    "LRLC_CRITERION_UNAVAILABLE": ("info", "diagnostics"),
    "LRLC_CUT_NO_ROOT": ("info", "diagnostics"),
    "LRLC_CUT_NO_BASIS": ("info", "diagnostics"),
    "LRLC_SWIRR_MISSING": ("info", "diagnostics"),
    "LRLC_SWIRR_COLUMN": ("warning", None),
    # LRLC: Thomas-Stieber, laminated sand, guard, pyrite, Qv, diagnosis, baseline
    "LRLC_TS_NO_ENDPOINTS": ("warning", None),
    "LRLC_TS_ENDPOINTS_INVALID": ("warning", None),
    "LRLC_TS_VSH_DEFAULTED": ("warning", None),
    "LRLC_TS_OUTSIDE": ("info", "diagnostics"),
    "LRLC_TS_GAS_BIAS": ("info", "diagnostics"),
    "LRLC_HAG_NO_VLAM": ("warning", None),
    "LRLC_HAG_SENSITIVE": ("info", "diagnostics"),
    "LRLC_HAG_RT_BELOW_RSH": ("info", "diagnostics"),
    "LRLC_GUARD_BLOCKED": ("warning", None),
    "LRLC_GUARD_WARNED": ("warning", None),
    "LRLC_GUARD_SBC_RT": ("warning", None),
    "LRLC_GUARD_NO_TS": ("info", None),
    "LRLC_GUARD_HINT": ("info", None),
    "LRLC_LAM_VSH_DOUBLE": ("warning", None),
    "LRLC_LAM_BULK_PHI": ("info", None),
    "LRLC_LAM_NO_SAND_BASIS": ("warning", "diagnostics"),
    "LRLC_PYR_NO_INPUT": ("warning", None),
    "LRLC_PYR_ILL_CONDITIONED": ("warning", None),
    "LRLC_PYR_NEGATIVE": ("info", "diagnostics"),
    "LRLC_PYR_IMPLAUSIBLE": ("warning", "diagnostics"),
    "LRLC_PYR_F_ZERO": ("info", None),
    "LRLC_PYR_SENSITIVE": ("info", "diagnostics"),
    "LRLC_PYR_PEF_CAUTION": ("info", None),
    "LRLC_PYR_PHI_BIAS": ("info", "diagnostics"),
    "LRLC_QV_OUT_OF_RANGE": ("info", "diagnostics"),
    "LRLC_QV_FALLBACK": ("warning", "diagnostics"),
    "LRLC_QV_NOT_USED": ("info", None),
    "LRLC_QV_NO_CORE_PAIRS": ("info", None),
    "LRLC_DIAG_INSUFFICIENT": ("info", "diagnostics"),
    "LRLC_BASE_SHF_HELD": ("info", "diagnostics"),
}


class IssueLog(list):
    """The plain ``warnings`` list plus the structured issues behind it.

    As a list it holds the texts of warning and error issues only, so every
    existing ``warnings.append`` / ``extend`` / dedupe keeps working; ``issues``
    holds every issue, info included.
    """

    def __init__(self):
        super().__init__()
        self.issues: List[dict] = []

    def add(self, code, text, severity=None, zone=None, target=None):
        if code not in ISSUE_CODES:
            raise KeyError(f"unknown issue code {code!r}")
        default_severity, default_target = ISSUE_CODES[code]
        severity = severity or default_severity
        if severity not in SEVERITIES:
            raise ValueError(f"bad severity {severity!r}")
        self.issues.append({
            "code": code, "severity": severity, "text": str(text), "zone": zone,
            "target": target if target is not None else default_target,
        })
        if severity != "info":
            self.append(str(text))

    def dedupe(self):
        """Drop repeated texts (the same message from several zone segments)."""
        self[:] = list(dict.fromkeys(self))
        seen, unique = set(), []
        for issue in self.issues:
            marker = (issue["code"], issue["zone"], issue["text"])
            if marker not in seen:
                seen.add(marker)
                unique.append(issue)
        self.issues = unique
