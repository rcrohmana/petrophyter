"""Flat label/value strip — replaces boxed MetricCard (design.md §6.5)."""
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from themes.helpers import set_status


class InfoStrip(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("InfoStrip")
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 4, 0, 4)
        self._layout.setSpacing(16)
        self._values: dict[str, QLabel] = {}

    def add_block(self, key: str, label: str):
        if self._values:
            rule = QFrame()
            rule.setObjectName("InfoStripRule")
            rule.setFixedWidth(1)
            self._layout.addWidget(rule)
        block = QVBoxLayout()
        block.setSpacing(0)
        caption = QLabel(label.upper())
        caption.setObjectName("InfoStripLabel")
        value = QLabel("—")
        value.setObjectName("InfoStripValue")
        block.addWidget(caption)
        block.addWidget(value)
        self._layout.addLayout(block)
        self._values[key] = value

    def value_label(self, key: str) -> QLabel:
        return self._values[key]

    def set_value(self, key: str, value: str):
        self._values[key].setText(value)

    def set_status(self, key: str, status: str | None):
        set_status(self._values[key], status)
