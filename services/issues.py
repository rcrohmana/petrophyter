"""Run issues of a well, built from what its last run's summary already holds.

Pure (no Qt). A summary with ``issues`` (v1.7.2, structured codes) is read as is.
Older summaries have no codes, so the list is derived from their warnings
(P0-UI/UX U1):

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
    target: Optional[str] = None  # "params.rw.rw_value", "params.porosity", "tops", "diagnostics"
    code: Optional[str] = None    # closed list in modules.issue_codes; None for v1.7.1 runs


def _warning_target(text: str) -> Optional[str]:
    for prefix, target in _TARGET_PREFIXES:
        if text.startswith(prefix):
            return target
    if _SOLVER_MARK in text:
        return "diagnostics"
    return None


def _unavailable_text(name: str) -> str:
    return f"{name} could not be estimated automatically."


def _issue_from_record(rec, key):
    return Issue(str(rec.get("severity") or "warning"), str(rec.get("text", "")), key,
                 zone=rec.get("zone"), target=rec.get("target"), code=rec.get("code"))


def collect_issues(ds) -> list:
    """Issues of ``ds``'s last run: errors, then warnings, then infos; no duplicate text."""
    key = getattr(ds, "key", "") or ""
    issues = []
    if getattr(ds, "error", None):
        issues.append(Issue("error", str(ds.error), key))
    summary = getattr(ds, "summary", None) or {}
    records = summary.get("issues")
    structured = records is not None
    if structured:
        for rec in records:
            issues.append(_issue_from_record(rec, key))
        texts = [i.text for i in issues if i.severity != "error"]
    else:
        texts = [str(w) for w in summary.get("warnings") or []]
        for text in texts:
            issues.append(Issue("warning", text, key, target=_warning_target(text)))
    for name in ("Rw", "Rsh"):
        if summary.get(f"{name.lower()}_source") != AUTO_UNAVAILABLE:
            continue
        if any(w.startswith(f"{name} could not be estimated") for w in texts):
            continue
        issues.append(Issue("warning", _unavailable_text(name), key, target="params.rw"))
    for zone, diag in (summary.get("zone_diagnostics") or {}).items():
        if structured and diag:
            # The pipeline's ZONE_NO_SHALE issue already carries the baseline note.
            diag = {**diag, "note": None}
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
