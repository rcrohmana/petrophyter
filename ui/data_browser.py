"""Read-only Data Browser tree (spec §2.4, §6.13): one root per well of the project."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QHeaderView, QLabel, QMenu, QStackedWidget, QTreeView,
    QVBoxLayout, QWidget,
)

from modules.param_scopes import normalize_zone
from themes.colors import get_color
from themes.icon_loader import get_icon
from themes.tokens import METRICS
from ui.widgets.status_dot import dot_pixmap

_KIND_ROLE = Qt.ItemDataRole.UserRole + 1
_WELL_ROLE = Qt.ItemDataRole.UserRole + 2
_ZONE_ROLE = Qt.ItemDataRole.UserRole + 3
_ROLES = ("GR", "RHOB", "NPHI", "DT", "RT")
_DEFAULT_EXPANDED = {"lasgrp", "tops", "results"}
_STATUS_DOTS = {
    "empty": "off", "loaded": "off", "run_ok": "success",
    "stale": "warning", "error": "error",
}
_CONTEXT_ACTIONS = {
    "well": ("open_las", "merge_las", "open_tops_multi", "open_core_multi"),
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
    well_selected = pyqtSignal(str)
    remove_well_requested = pyqtSignal(str)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self._actions = {}
        self._sources = []
        self._merged = False
        self._pending = False
        self._last_active = None
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
        self.tree.clicked.connect(self._on_clicked)
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

        project = self.model.project
        project.wells_changed.connect(self.rebuild)
        project.active_well_changed.connect(lambda _key: self.rebuild())
        project.well_updated.connect(lambda _key: self.rebuild())
        self.rebuild()

    # ---- public API ----
    def set_actions(self, actions: dict):
        self._actions = actions

    def set_las_sources(self, files: list, merged: bool = False, pending: bool = False):
        """Kept for compatibility; sources now come from each well's dataset."""
        self._sources = list(files)
        self._merged = merged
        self._pending = pending

    def set_results_stale(self, stale: bool = False):
        """Refresh the active well's Results row (the flag lives on the dataset)."""
        project = self.model.project
        ds = project.active
        root = self._root_item(project.active_key)
        if ds is None or root is None:
            return
        group = self._find_group(root, "results")
        if group is not None:
            self._style_results_info(root.child(group.row(), 1), ds)

    def refresh_theme(self):
        self.rebuild()

    # ---- building ----
    def _path(self, item) -> str:
        parts = []
        while item is not None:
            parts.append(str(item.data(_WELL_ROLE)) if item.parent() is None else item.text())
            item = item.parent()
        return "/".join(reversed(parts))

    def _walk(self, item, visit):
        for row in range(item.rowCount()):
            child = item.child(row, 0)
            visit(child)
            self._walk(child, visit)

    def _root_item(self, key):
        for row in range(self.tree_model.rowCount()):
            item = self.tree_model.item(row, 0)
            if item.data(_WELL_ROLE) == key:
                return item
        return None

    @staticmethod
    def _find_group(root, kind):
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

    @staticmethod
    def _style_results_info(info_item, ds):
        results, data = ds.results, ds.las_data
        k = 0
        if results is not None and data is not None:
            k = len([c for c in results.columns if c not in data.columns])
        info_item.setText("out of date" if ds.stale else f"{k} curves")
        info_item.setData(
            dot_pixmap("warning" if ds.stale else "success"),
            Qt.ItemDataRole.DecorationRole,
        )

    def rebuild(self):
        old_known, old_expanded = set(), set()

        def collect(item):
            path = self._path(item)
            old_known.add(path)
            if self.tree.isExpanded(item.index()):
                old_expanded.add(path)

        for row in range(self.tree_model.rowCount()):
            root_old = self.tree_model.item(row, 0)
            collect(root_old)
            self._walk(root_old, collect)

        self.tree_model.removeRows(0, self.tree_model.rowCount())
        project = self.model.project
        wells = project.wells
        if not wells:
            self.stack.setCurrentWidget(self.empty_label)
            return
        self.stack.setCurrentWidget(self.tree)

        newly_active = project.active_key != self._last_active
        self._last_active = project.active_key
        for ds in wells:
            active = ds.key == project.active_key
            root = self._build_root(ds, active)
            self.tree_model.appendRow(root)

            def restore(item, active=active):
                path = self._path(item)
                if item.parent() is None and active and newly_active:
                    expand = True      # switching wells reveals the new active well
                elif path in old_known:
                    expand = path in old_expanded
                elif item.parent() is None:
                    expand = active
                else:
                    expand = active and item.data(_KIND_ROLE) in _DEFAULT_EXPANDED
                self.tree.setExpanded(item.index(), expand)

            restore(root[0])
            self._walk(root[0], restore)

    def _zone_param_names(self, ds) -> dict:
        """{NORMALIZED ZONE: set of parameter names} overridden for this well or project-wide."""
        names = {}
        stores = [ds.zone_overrides or {}, getattr(self.model.project, "zone_params", None) or {}]
        for store in stores:
            for zone, params in store.items():
                if params:
                    names.setdefault(normalize_zone(zone), set()).update(map(str, params))
        return names

    @staticmethod
    def _tag_well(item, key):
        """Remember the owning well on an item, its info cell and all descendants."""
        item.setData(key, _WELL_ROLE)
        for row in range(item.rowCount()):
            for col in range(item.columnCount()):
                child = item.child(row, col)
                if child is not None:
                    DataBrowserPanel._tag_well(child, key)

    def _build_root(self, ds, active):
        data = ds.las_data
        depth_info = ""
        if data is not None and "DEPTH" in data.columns and len(data):
            depth_info = f"{data['DEPTH'].min():,.1f}–{data['DEPTH'].max():,.1f} ft"
        root = self._row(ds.display_name or ds.key, depth_info, "well",
                         "crosshair" if active else "cylinder",
                         tooltip="Active well" if active else ds.key,
                         dot=_STATUS_DOTS.get(ds.status, "off"))
        font = QFont()
        font.setBold(active)
        root[0].setFont(font)
        well = root[0]

        # LAS files
        sources = ds.sources
        n = len(sources)
        if ds.merged:
            las_info = f"{n} files merged"
        else:
            las_info = f"{n} file" + ("" if n == 1 else "s")
        las = self._row("LAS files", las_info, "lasgrp", "file-text", dot="success", group=True)
        if ds.merged:
            rows = len(data) if data is not None else 0
            las[0].appendRow(self._row(
                f"Merged ({n} files)", f"{rows:,} rows", "las", "file-text"))
        for src in sources:
            las[0].appendRow(self._row(
                str(src.get("name", "")), f"{int(src.get('rows') or 0):,} rows",
                "las", "file-text", muted=ds.merged))
        well.appendRow(las)

        # Curves
        info = getattr(ds.las_parser, "curve_info", None) or {}
        roles = {}
        for role, mnemonic in (ds.curve_mapping or {}).items():
            if mnemonic and mnemonic != "None":
                roles.setdefault(mnemonic, []).append(role)
        columns = list(data.columns) if data is not None else []
        curves = self._row("Curves", f"{len(columns)}", "curves", "activity", group=True)
        for mnemonic in columns:
            unit = (info.get(mnemonic) or {}).get("unit", "")
            tag = "/".join(roles.get(mnemonic, []))
            text = " · ".join(part for part in (tag, unit) if part)
            curves[0].appendRow(self._row(
                str(mnemonic), text, "curve",
                tooltip=(info.get(mnemonic) or {}).get("description") or None))
        well.appendRow(curves)

        # Formation tops
        tops = ds.formation_tops
        formations = getattr(tops, "formations", None) if tops is not None else None
        if formations:
            grp = self._row("Formation tops", f"{len(formations)}", "tops", "layers",
                            dot="success", group=True)
            zone_names = self._zone_param_names(ds)
            for fm in formations:
                zone = normalize_zone(fm.name)
                names = zone_names.get(zone)
                depths = f"{fm.top_depth:,.1f}–{fm.bottom_depth:,.1f}"
                if names:
                    tip = ("Zone parameters: " + ", ".join(sorted(names))
                           + "\nDouble-click to edit")
                    row = self._row(fm.name, depths, "top", "sliders-horizontal",
                                    tooltip=tip)
                    row[0].setData(zone, _ZONE_ROLE)
                else:
                    row = self._row(fm.name, depths, "top")
                grp[0].appendRow(row)
        else:
            grp = self._row("Formation tops", "Not loaded", "tops", "layers",
                            muted=True, group=True)
        well.appendRow(grp)

        # Core data
        core = ds.core_data
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
        results = ds.results
        if results is not None:
            res = self._row("Results", "", "results", "sigma", group=True)
            for col in results.columns:
                if data is None or col not in data.columns:
                    res[0].appendRow(self._row(str(col), "", "result"))
            self._style_results_info(res[1], ds)
            well.appendRow(res)

        for cell in root:
            self._tag_well(cell, ds.key)
        return root

    # ---- interaction ----
    @staticmethod
    def _well_key_of(index):
        return index.sibling(index.row(), 0).data(_WELL_ROLE)

    def _on_clicked(self, index):
        key = self._well_key_of(index)
        if key:
            self.well_selected.emit(key)

    def _request_set_active(self, key):
        self.well_selected.emit(key)

    def _request_remove(self, key):
        self.remove_well_requested.emit(key)

    def _build_menu(self, index):
        kind = index.sibling(index.row(), 0).data(_KIND_ROLE)
        key = self._well_key_of(index)
        menu = QMenu(self)
        if kind == "well" and key:
            activate = QAction(get_icon("crosshair"), "Set as Active Well", menu)
            activate.triggered.connect(lambda _=False, k=key: self._request_set_active(k))
            menu.addAction(activate)
            remove = QAction(get_icon("x"), "Remove Well", menu)
            remove.triggered.connect(lambda _=False, k=key: self._request_remove(k))
            menu.addAction(remove)
            menu.addSeparator()
        for action_key in _CONTEXT_ACTIONS.get(kind, ()):
            action = self._actions.get(action_key)
            if action is not None:
                menu.addAction(action)
        return menu

    def _show_context_menu(self, pos):
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return
        menu = self._build_menu(index)
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
        elif kind == "top" and name_index.data(_ZONE_ROLE):
            self.action_requested.emit(f"edit_zone:{name_index.data(_ZONE_ROLE)}")
