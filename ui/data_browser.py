"""Read-only Data Browser tree (spec §2.4, §6.13). Reads AppModel only; owns no inputs."""
import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QMenu, QStackedWidget, QTreeView,
    QVBoxLayout, QWidget,
)

from themes.colors import get_color
from themes.icon_loader import get_icon
from themes.tokens import METRICS
from ui.widgets.status_dot import dot_pixmap

_KIND_ROLE = Qt.ItemDataRole.UserRole + 1
_ROLES = ("GR", "RHOB", "NPHI", "DT", "RT")
_DEFAULT_EXPANDED = {"well", "lasgrp", "tops", "results"}
_CONTEXT_ACTIONS = {
    "well": ("open_las", "merge_las"),
    "lasgrp": ("open_las", "merge_las"),
    "las": ("open_las", "merge_las"),
    "curves": ("page_curves",),
    "curve": ("page_curves",),
    "tops": ("open_tops", "page_scope"),
    "top": ("open_tops", "page_scope"),
    "core": ("open_core", "page_core"),
    "results": ("run_analysis",),
    "result": ("run_analysis",),
}


class DataBrowserPanel(QWidget):
    action_requested = pyqtSignal(str)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._actions = {}
        self._sources = []
        self._merged = False
        self._pending = False
        self._results_stale = False
        self.setObjectName("DataBrowser")
        self.setMinimumWidth(METRICS["panel_min_width"])
        self.setMaximumWidth(METRICS["panel_max_width"])

        self.empty_label = QLabel(
            'No data loaded<br><a href="open">Open LAS File(s)…</a>'
        )
        self.empty_label.setObjectName("PlaceholderLabel")
        self.empty_label.setTextFormat(Qt.TextFormat.RichText)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.linkActivated.connect(
            lambda _link: self.action_requested.emit("open_las")
        )

        self.tree_model = QStandardItemModel(self)
        self.tree_model.setColumnCount(2)
        self.tree = QTreeView()
        self.tree.setObjectName("DataTree")
        self.tree.setModel(self.tree_model)
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(16)
        self.tree.setRootIsDecorated(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.doubleClicked.connect(self._on_double_clicked)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.empty_label)
        self.stack.addWidget(self.tree)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)
        self.rebuild()

    # ---- public API ----
    def set_actions(self, actions: dict):
        self._actions = actions

    def set_las_sources(self, files: list, merged: bool = False, pending: bool = False):
        self._sources = list(files)
        self._merged = merged
        self._pending = pending

    def set_results_stale(self, stale: bool):
        self._results_stale = bool(stale)
        group = self._find_group("results")
        if group is None:
            return
        info = self.tree_model.item(0).child(group.row(), 1)
        self._style_results_info(info)

    def refresh_theme(self):
        self.rebuild()

    # ---- building ----
    def _path(self, item) -> str:
        parts = []
        while item is not None:
            parts.append(item.text())
            item = item.parent()
        return "/".join(reversed(parts))

    def _walk(self, item, visit):
        for row in range(item.rowCount()):
            child = item.child(row, 0)
            visit(child)
            self._walk(child, visit)

    def _find_group(self, kind):
        root = self.tree_model.item(0)
        if root is None:
            return None
        for row in range(root.rowCount()):
            child = root.child(row, 0)
            if child.data(_KIND_ROLE) == kind:
                return child
        return None

    def _row(self, name, info, kind, icon=None, tooltip=None, muted=False,
             dot=None, group=False):
        name_item = QStandardItem(name)
        info_item = QStandardItem(info)
        name_item.setData(kind, _KIND_ROLE)
        info_item.setData(kind, _KIND_ROLE)
        info_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        muted_color = QColor(get_color("text_muted"))
        info_item.setData(muted_color, Qt.ItemDataRole.ForegroundRole)
        if muted:
            name_item.setData(muted_color, Qt.ItemDataRole.ForegroundRole)
        if icon:
            name_item.setIcon(get_icon(icon))
        if dot:
            info_item.setData(dot_pixmap(dot), Qt.ItemDataRole.DecorationRole)
        if tooltip:
            name_item.setToolTip(tooltip)
            info_item.setToolTip(tooltip)
        else:
            # Names or info that elide in a narrow panel stay readable.
            name_item.setToolTip(name)
            if info:
                info_item.setToolTip(info)
        if group:
            font = QFont()
            font.setWeight(QFont.Weight.DemiBold)
            name_item.setFont(font)
        info_font = QFont()
        info_font.setPointSize(8)
        if info[:1].isdigit():
            info_font.setFamily("Consolas")
        info_item.setFont(info_font)
        return [name_item, info_item]

    def _style_results_info(self, info_item):
        results = self.model.results
        k = 0
        if results is not None and self.model.las_data is not None:
            k = len([c for c in results.columns if c not in self.model.las_data.columns])
        info_item.setText("out of date" if self._results_stale else f"{k} curves")
        info_item.setData(
            dot_pixmap("warning" if self._results_stale else "success"),
            Qt.ItemDataRole.DecorationRole,
        )

    def rebuild(self):
        old_known, old_expanded = set(), set()
        root_old = self.tree_model.item(0)
        if root_old is not None:
            def collect(item):
                path = self._path(item)
                old_known.add(path)
                if self.tree.isExpanded(item.index()):
                    old_expanded.add(path)
            collect(root_old)
            self._walk(root_old, collect)

        self.tree_model.removeRows(0, self.tree_model.rowCount())
        data = self.model.las_data
        if data is None:
            self.stack.setCurrentWidget(self.empty_label)
            return
        self.stack.setCurrentWidget(self.tree)

        root = self._build_root(data)
        self.tree_model.appendRow(root)

        def restore(item):
            path = self._path(item)
            if path in old_known:
                expand = path in old_expanded
            else:
                expand = item.data(_KIND_ROLE) in _DEFAULT_EXPANDED
            self.tree.setExpanded(item.index(), expand)

        restore(root[0])
        self._walk(root[0], restore)

    def _well_name(self) -> str:
        parser = self.model.las_parser
        if parser is not None:
            name = (getattr(parser, "well_info", None) or {}).get("well_name")
            if name and name != "Unknown":
                return str(name)
        if self.model.las_filename:
            return os.path.splitext(os.path.basename(str(self.model.las_filename)))[0]
        return "Well"

    def _build_root(self, data):
        depth_info = ""
        if "DEPTH" in data.columns and len(data):
            depth_info = f"{data['DEPTH'].min():,.1f}–{data['DEPTH'].max():,.1f} ft"
        root = self._row(self._well_name(), depth_info, "well", group=True)
        well = root[0]

        # LAS files
        n = len(self._sources)
        if self._pending:
            las_info, las_dot = f"{n} files · not merged", "warning"
        elif self._merged:
            las_info, las_dot = f"{n} files merged", "success"
        else:
            las_info, las_dot = (f"{n} file" + ("" if n == 1 else "s")), "success"
        las = self._row("LAS files", las_info, "lasgrp", "file-text", dot=las_dot, group=True)
        if self._merged:
            las[0].appendRow(self._row(
                f"Merged ({n} files)", f"{len(data):,} rows", "las", "file-text"))
        for name, rows in self._sources:
            las[0].appendRow(self._row(
                name, f"{rows:,} rows", "las", "file-text", muted=self._merged))
        well.appendRow(las)

        # Curves
        parser = self.model.las_parser
        info = getattr(parser, "curve_info", None) or {}
        roles = {}
        for role, mnemonic in (self.model.curve_mapping or {}).items():
            if mnemonic and mnemonic != "None":
                roles.setdefault(mnemonic, []).append(role)
        curves = self._row("Curves", f"{len(data.columns)}", "curves", "activity", group=True)
        for mnemonic in data.columns:
            unit = (info.get(mnemonic) or {}).get("unit", "")
            tag = "/".join(roles.get(mnemonic, []))
            text = " · ".join(part for part in (tag, unit) if part)
            curves[0].appendRow(self._row(
                str(mnemonic), text, "curve",
                tooltip=(info.get(mnemonic) or {}).get("description") or None))
        well.appendRow(curves)

        # Formation tops
        tops = self.model.formation_tops
        formations = getattr(tops, "formations", None) if tops is not None else None
        if formations:
            grp = self._row("Formation tops", f"{len(formations)}", "tops", "layers",
                            dot="success", group=True)
            for fm in formations:
                grp[0].appendRow(self._row(
                    fm.name, f"{fm.top_depth:,.1f}–{fm.bottom_depth:,.1f}", "top"))
        else:
            grp = self._row("Formation tops", "Not loaded", "tops", "layers",
                            muted=True, group=True)
        well.appendRow(grp)

        # Core data
        core = self.model.core_data
        summary = core.get_summary() if core is not None else {}
        if summary:
            row = self._row("Core data",
                            f"{summary['n_samples']} samples · {summary.get('depth_unit', 'FT')}",
                            "core", "database", dot="success", group=True)
        else:
            row = self._row("Core data", "Not loaded", "core", "database",
                            muted=True, group=True)
        well.appendRow(row)

        # Results
        results = self.model.results
        if results is not None:
            res = self._row("Results", "", "results", "sigma", group=True)
            for col in results.columns:
                if col not in data.columns:
                    res[0].appendRow(self._row(str(col), "", "result"))
            self._style_results_info(res[1])
            well.appendRow(res)
        return root

    # ---- interaction ----
    def _show_context_menu(self, pos):
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        kind = index.sibling(index.row(), 0).data(_KIND_ROLE)
        keys = _CONTEXT_ACTIONS.get(kind, ())
        menu = QMenu(self)
        for key in keys:
            action = self._actions.get(key)
            if action is not None:
                menu.addAction(action)
        if not menu.isEmpty():
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_double_clicked(self, index):
        name_index = index.sibling(index.row(), 0)
        kind = name_index.data(_KIND_ROLE)
        info = index.sibling(index.row(), 1).data(Qt.ItemDataRole.DisplayRole)
        if kind == "tops" and info == "Not loaded":
            self.action_requested.emit("open_tops")
        elif kind == "core" and info == "Not loaded":
            self.action_requested.emit("open_core")
        elif kind == "curve":
            self.action_requested.emit("page_curves")
