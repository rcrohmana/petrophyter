"""Small styling helpers — the only sanctioned dynamic-styling mechanism in ui/."""
from PyQt6.QtWidgets import QWidget

_ALLOWED = {"success", "warning", "error", "muted", "accent", None}


def set_status(widget: QWidget, status: str | None) -> None:
    """Set the `status` dynamic property and repolish so QSS re-applies."""
    if status not in _ALLOWED:
        raise ValueError(f"unknown status {status!r}")
    widget.setProperty("status", status)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


def set_variant(widget: QWidget, variant: str) -> None:
    """Set the button `variant` property (primary/ghost/link) before show."""
    widget.setProperty("variant", variant)
