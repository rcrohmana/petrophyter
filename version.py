"""Single source of truth for Petrophyter release metadata."""

APP_VERSION = "1.7.0"
APP_BUILD = "20261010"
APP_VERSION_DISPLAY = f"{APP_VERSION} (Build {APP_BUILD})"


def version_tuple(version) -> tuple:
    """``"1.10.0"`` -> ``(1, 10, 0)``, for numeric version comparison.

    Each dot-separated part contributes its leading digits; a part without
    digits counts as 0 and anything after them (``"2rc1"``) is ignored, so
    ``"1.10.0" > "1.9.0"`` holds, unlike a string comparison.
    """
    parts = []
    for part in str(version or "").strip().split("."):
        digits = ""
        for char in part.strip():
            if not char.isdigit():
                break
            digits += char
        parts.append(int(digits) if digits else 0)
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)
