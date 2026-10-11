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
