"""Run issues of a well, built from what its last run's summary already holds.

Pure (no Qt). In v1.7.1 the pipeline has no issue codes, so the list is
derived here and the summary goldens stay unchanged (P0-UI/UX U1):

- ``ds.error``                      -> error
- every ``summary["warnings"]`` entry -> warning
- Rw/Rsh auto estimate unavailable  -> warning (unless already in the warnings)
- each zone's diagnostic note       -> its own level, with the zone set

Targets are coarse "go to" hints mapped from the message source.
"""

from dataclasses import dataclass
from typing import Optional

from modules.pipeline import AUTO_UNAVAILABLE, zone_diagnostic_note

SEVERITIES = ("error", "warning", "info")

# Coarse targets, matched on the start of a pipeline warning (v1.7.2 codes replace this).
_TARGET_PREFIXES = (
    ("Rw ", "params.rw"),
    ("Rsh ", "params.rw"),
    ("PHIE ", "params.porosity"),
    ("PHIT ", "params.porosity"),
    ("NPHI curve", "params.porosity"),
    ("Selected formations not in", "tops"),
    ("Formation tops overlap", "tops"),
)
_SOLVER_MARK = "solver points"


@dataclass(frozen=True)
class Issue:
    severity: str                 # "error" | "warning" | "info"
    text: str
    well: str                     # dataset key
    zone: Optional[str] = None
    target: Optional[str] = None  # "params.rw", "params.porosity", "tops", "diagnostics"


def _warning_target(text: str) -> Optional[str]:
    for prefix, target in _TARGET_PREFIXES:
        if text.startswith(prefix):
            return target
    if _SOLVER_MARK in text:
        return "diagnostics"
    return None


def _unavailable_text(name: str) -> str:
    return f"{name} could not be estimated automatically."


def collect_issues(ds) -> list:
    """Issues of ``ds``'s last run: errors, then warnings, then infos; no duplicate text."""
    key = getattr(ds, "key", "") or ""
    issues = []
    if getattr(ds, "error", None):
        issues.append(Issue("error", str(ds.error), key))
    summary = getattr(ds, "summary", None) or {}
    warnings = [str(w) for w in summary.get("warnings") or []]
    for text in warnings:
        issues.append(Issue("warning", text, key, target=_warning_target(text)))
    for name in ("Rw", "Rsh"):
        if summary.get(f"{name.lower()}_source") != AUTO_UNAVAILABLE:
            continue
        if any(w.startswith(f"{name} could not be estimated") for w in warnings):
            continue
        issues.append(Issue("warning", _unavailable_text(name), key, target="params.rw"))
    for zone, diag in (summary.get("zone_diagnostics") or {}).items():
        note = zone_diagnostic_note(diag) if diag else None
        if note:
            level, text = note
            issues.append(Issue(level, text, key, zone=zone, target="diagnostics"))

    seen, unique = set(), []
    for issue in sorted(issues, key=lambda i: SEVERITIES.index(i.severity)):
        marker = (issue.zone, issue.text)
        if marker not in seen:
            seen.add(marker)
            unique.append(issue)
    return unique


def issue_counts(issues) -> dict:
    """``{"error": n, "warning": n, "info": n}``."""
    counts = dict.fromkeys(SEVERITIES, 0)
    for issue in issues:
        counts[issue.severity] += 1
    return counts
