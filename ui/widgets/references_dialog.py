"""Help > Scientific References: every registry entry, grouped by method."""

import html

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from modules import references
from themes.colors import get_color
from themes.helpers import set_status


def _entry_html(key: str) -> str:
    ref = references.REFERENCES[key]
    text = html.escape(references.format_full(key))
    if ref.doi:
        shown = html.escape(f"doi:{ref.doi}")
        href = html.escape(f"https://doi.org/{ref.doi}", quote=True)
        text = text.replace(shown, f'<a href="{href}">{shown}</a>', 1)
    elif ref.url:
        shown = html.escape(ref.url)
        text = text.replace(shown, f'<a href="{html.escape(ref.url, quote=True)}">{shown}</a>', 1)
    if ref.status != "verified":
        note = html.escape(references.UNVERIFIED_NOTE)
        text = text.replace(note, f'<span style="color: {get_color("text_muted")};">{note}</span>')
    return f"<li>{text}</li>"


def build_html() -> str:
    """One section per group (registry order), an entry under every group it belongs to."""
    known = list(references.GROUP_ORDER)
    extra = sorted({g for r in references.REFERENCES.values() for g in r.groups} - set(known))
    parts = []
    for group in known + extra:
        keys = sorted(
            (k for k, r in references.REFERENCES.items() if group in r.groups),
            key=lambda k: (references.format_short(k).lower(), k),
        )
        if not keys:
            continue
        parts.append(f"<h3>{html.escape(group)}</h3><ul>")
        parts.extend(_entry_html(k) for k in keys)
        parts.append("</ul>")
    ungrouped = sorted(k for k, r in references.REFERENCES.items() if not r.groups)
    if ungrouped:
        parts.append("<h3>Other</h3><ul>")
        parts.extend(_entry_html(k) for k in ungrouped)
        parts.append("</ul>")
    return "".join(parts)


class ReferencesDialog(QDialog):
    """Read-only list of the scientific references behind the methods."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scientific References")
        self.setMinimumSize(640, 520)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        intro = QLabel(
            "Sources behind the methods in Petrophyter. Entries marked "
            f"{references.UNVERIFIED_NOTE} are listed as recalled and still need checking "
            "against the original."
        )
        intro.setWordWrap(True)
        set_status(intro, "muted")
        layout.addWidget(intro)

        self.browser = QTextBrowser()
        self.browser.setReadOnly(True)
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(build_html())
        layout.addWidget(self.browser, 1)

        buttons = QHBoxLayout()
        self.export_btn = QPushButton("Export BibTeX…")
        self.export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_btn.clicked.connect(self._export_bibtex)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.export_btn)
        buttons.addStretch()
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

    def _export_bibtex(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export BibTeX", "references.bib", "BibTeX (*.bib);;All files (*)"
        )
        if not path:
            return
        references.write_bibtex(path)
