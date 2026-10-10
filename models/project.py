"""
Multi-well project state (spec docs/specs/2026-10-10-multi-well-audit-design.md §5.1).

A :class:`Project` holds any number of :class:`WellDataset` objects keyed by a
stable well key, plus the key of the *active* well. ``AppModel`` keeps its old
single-well properties (``las_data``, ``results``, ...) as a facade over the
active well, so views that only ever show one well keep working unchanged.
"""

import os
from collections import OrderedDict
from typing import Dict, Iterator, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from modules.las_utils import normalize_well_name, well_key


def default_curve_mapping() -> Dict[str, str]:
    return {"GR": "None", "RHOB": "None", "NPHI": "None", "DT": "None", "RT": "None"}


class WellDataset:
    """Everything the app knows about one well."""

    # Data-dependent results; cleared whenever the well's data is replaced.
    DERIVED_FIELDS = (
        "qc_report", "results", "summary", "merge_report", "calculated",
        "calculated_shale", "shale_method_used", "calculated_rw",
        "calculated_rsh", "calculated_C", "calculated_P", "calculated_Q",
        "run_params_hash", "error",
    )

    def __init__(self, key: str = "", display_name: str = ""):
        self.key = key
        self.display_name = display_name
        self.identity: Dict = {}
        # One entry per source file: {"name", "path", "rows"}.
        self.sources: List[Dict] = []
        self.merged = False

        self.las_parser = None
        self.las_data = None
        self.las_filename = ""
        self.formation_tops = None
        self.core_data = None
        self.curve_mapping: Dict[str, str] = default_curve_mapping()
        self.analysis_mode = "Whole Well"
        self.selected_formations: List[str] = []

        # Parameter overrides (spec §4): {param: {"mode", "value", "source"}}
        # and {FORMATION: {param: entry}} for the well · zone scope.
        self.overrides: Dict[str, Dict] = {}
        self.zone_overrides: Dict[str, Dict[str, Dict]] = {}

        self.stale = False
        self.clear_derived()

    def clear_derived(self):
        """Forget results that were computed from the previous data."""
        self.qc_report = None
        self.results = None
        self.summary = None
        self.merge_report = None
        self.calculated = False
        self.calculated_shale = None
        self.shale_method_used = "custom"
        self.calculated_rw = None
        self.calculated_rsh = None
        self.calculated_C = None
        self.calculated_P = None
        self.calculated_Q = None
        self.run_params_hash = None
        self.error = None
        self.stale = False

    @property
    def status(self) -> str:
        """One of ``empty``, ``loaded``, ``run_ok``, ``stale``, ``error``."""
        if self.error:
            return "error"
        if self.las_data is None:
            return "empty"
        if self.calculated:
            return "stale" if self.stale else "run_ok"
        return "loaded"

    @property
    def well_info(self) -> Dict:
        return dict(getattr(self.las_parser, "well_info", None) or self.identity or {})

    def __repr__(self):
        return f"WellDataset(key={self.key!r}, rows={0 if self.las_data is None else len(self.las_data)})"


def make_well_key(well_info: Optional[Dict], fallback_name: str = "") -> str:
    """Stable key for a well: ``UWI:…``/``API:…``/``WELL:…`` or ``FILE:<stem>``.

    Files without a usable identifier get a key from their file name, so they
    are never grouped with another well automatically.
    """
    key, identified = well_key(well_info or {})
    if identified:
        return key
    stem = os.path.splitext(os.path.basename(str(fallback_name or "")))[0]
    return f"FILE:{normalize_well_name(stem) or 'UNNAMED'}"


def display_name_for(well_info: Optional[Dict], fallback_name: str = "") -> str:
    """Human-readable well name: the header WELL, else the file stem."""
    name = str((well_info or {}).get("well_name") or "").strip()
    if normalize_well_name(name):
        return name
    stem = os.path.splitext(os.path.basename(str(fallback_name or "")))[0]
    return stem or "Well"


class Project(QObject):
    """Ordered collection of wells with one active well."""

    wells_changed = pyqtSignal()
    active_well_changed = pyqtSignal(str)
    well_updated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._wells: "OrderedDict[str, WellDataset]" = OrderedDict()
        self._active_key: Optional[str] = None

    # ---- access ----
    def __len__(self) -> int:
        return len(self._wells)

    def __iter__(self) -> Iterator[WellDataset]:
        return iter(list(self._wells.values()))

    def __contains__(self, key) -> bool:
        return key in self._wells

    @property
    def wells(self) -> List[WellDataset]:
        return list(self._wells.values())

    def keys(self) -> List[str]:
        return list(self._wells.keys())

    def get(self, key: Optional[str]) -> Optional[WellDataset]:
        return self._wells.get(key) if key is not None else None

    @property
    def active_key(self) -> Optional[str]:
        return self._active_key

    @property
    def active(self) -> Optional[WellDataset]:
        return self.get(self._active_key)

    # ---- mutation ----
    def unique_key(self, key: str) -> str:
        """``key`` if free, else ``key#2``, ``key#3`` …"""
        if key not in self._wells:
            return key
        n = 2
        while f"{key}#{n}" in self._wells:
            n += 1
        return f"{key}#{n}"

    def add_well(self, dataset: WellDataset, activate: bool = True,
                 replace: bool = True) -> str:
        """Add ``dataset``; a dataset with an existing key replaces that well.

        With ``replace=False`` a clashing key gets a ``#n`` suffix instead.
        Returns the key the dataset is stored under.
        """
        if not dataset.key:
            dataset.key = make_well_key(dataset.well_info, dataset.las_filename)
        if dataset.key in self._wells and not replace:
            dataset.key = self.unique_key(dataset.key)
        self._wells[dataset.key] = dataset
        self.wells_changed.emit()
        if activate or self._active_key is None:
            self.set_active(dataset.key, force=True)
        return dataset.key

    def remove_well(self, key: str):
        if key not in self._wells:
            return
        del self._wells[key]
        self.wells_changed.emit()
        if key == self._active_key:
            self._active_key = None
            self.set_active(next(iter(self._wells), None), force=True)

    def rename_key(self, old: str, new: str) -> str:
        """Re-key a well (keeps its position); returns the key actually used."""
        if old not in self._wells or old == new:
            return old
        new = self.unique_key(new)
        items = [(new if k == old else k, v) for k, v in self._wells.items()]
        self._wells = OrderedDict(items)
        self._wells[new].key = new
        if self._active_key == old:
            self._active_key = new
        self.wells_changed.emit()
        return new

    def set_active(self, key: Optional[str], force: bool = False):
        if key is not None and key not in self._wells:
            raise KeyError(key)
        if key == self._active_key and not force:
            return
        self._active_key = key
        self.active_well_changed.emit(key or "")

    def clear(self):
        self._wells.clear()
        self._active_key = None
        self.wells_changed.emit()
        self.active_well_changed.emit("")
