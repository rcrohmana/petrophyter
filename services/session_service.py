"""
Session Service for Petrophyter PyQt
Manages saving and loading of analysis sessions.
"""

import copy
import json
import logging
import os
import tempfile
from typing import Callable, Dict, Any, List, Optional
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal


logger = logging.getLogger(__name__)

_SESSION_DEFAULTS = {
    "analysis_mode": "Whole Well",
    "selected_formations": [],
    "curve_mapping": {"GR": "None", "RHOB": "None", "NPHI": "None", "DT": "None", "RT": "None"},
    "vsh_baseline_method": "Statistically (Auto)",
    "gr_min_manual": 20.0,
    "gr_max_manual": 120.0,
    "vsh_methods": ["Linear"],
    "rho_matrix": 2.65,
    "dt_matrix": 55.5,
    # Optional explicit matrix neutron response; absent/None preserves the
    # lithology-derived default used by older sessions.
    "nphi_matrix": None,
    "rho_fluid": 1.0,
    "dt_fluid": 189.0,
    "shale_approach": "Custom (Manual)",
    "rho_shale": 2.45,
    "dt_shale": 100.0,
    "nphi_shale": 0.35,
    "shale_vsh_threshold": 0.80,
    "shale_gate_logs": True,
    "shale_iqr_filter": True,
    "shale_selection_mode": "fixed_threshold",
    "shale_vsh_quantile": 0.90,
    "shale_min_points": 50,
    "shale_sweep_tmin": 0.65,
    "shale_sweep_tmax": 0.95,
    "shale_sweep_step": 0.02,
    "primary_phie_method": "PHIE_DN",
    "lithology_preset": "Sandstone (Humble)",
    "a": 0.62,
    "m": 2.15,
    "n": 2.0,
    "rw": 0.05,
    "rsh": 5.0,
    "rw_mode": "manual",
    "rsh_mode": "auto",
    "perm_C": 8581.0,
    "perm_P": 4.4,
    "perm_Q": 2.0,
    "swirr_method": "Hierarchical (Recommended)",
    "buckles_preset": "Sandstone (Clean)",
    "k_buckles": 0.02,
    "vsh_cutoff": 0.4,
    "phi_cutoff": 0.08,
    "sw_cutoff": 0.6,
    "sw_methods": ["Simandoux"],
    "sw_primary_method": "Simandoux",
    "ws_qv": 0.2,
    "ws_b": 1.0,
    "dw_swb": 0.1,
    "dw_rwb": 0.2,
    "merge_step": 0.5,
    "merge_gap_limit": 5.0,
    "core_depth_unit": "Auto",
    "core_max_dist": 2.0,
    "gas_correction_enabled": False,
    "gas_nphi_factor": 0.30,
    "gas_rhob_factor": 0.15,
    "temp_correction": False,
    "surface_temp": 80.0,
    "temp_gradient": 1.5,
    "rw_ref_temp": 75.0,
}

# Per-well settings that live in each ``wells`` entry in v2.0 sessions, not in
# ``global_params``.
_PER_WELL_FIELDS = ("analysis_mode", "selected_formations", "curve_mapping")


def _json_safe(value):
    """Recursively convert numpy / tuple / set values to plain JSON types."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and value != value:
        return None
    return value


def is_v2_session(session_data: Dict) -> bool:
    """True for a v2.x session (a whole project: wells, scopes, tops and core)."""
    return str(session_data.get("_session_version", "1.0")).split(".")[0] == "2"


_is_v2 = is_v2_session


def attach_tops(well, path: str) -> List[str]:
    """Read a tops file for ``well`` and attach it; returns notes (empty when fine).

    A file with a well column contributes only the rows that match ``well``.
    Sets ``well.formation_tops`` and ``well.tops_path`` on success.
    """
    from modules.formation_tops import FormationTops
    from modules.well_matching import assign_to_wells

    tops = FormationTops()
    try:
        with open(path, "rb") as handle:
            ok = tops.read_tops_from_buffer(handle)
    except OSError as exc:
        return [f"Formation tops file could not be read ({os.path.basename(path)}): {exc.strerror or exc}"]
    if not ok:
        return [f"Formation tops file could not be parsed: {os.path.basename(path)}"]
    tops.convert_to_feet()
    notes = []
    if tops.well_names():
        matches, _ = assign_to_wells(
            tops.split_by_well(), [(well.key, well.well_info)], tops.well_kind
        )
        if well.key not in matches:
            return [f"{os.path.basename(path)} has no tops for well {well.display_name}"]
        tops = matches[well.key]
    well.formation_tops = tops
    well.tops_path = path
    return notes


def attach_core(well, path: str, depth_unit: str = "Auto") -> List[str]:
    """Read a core file for ``well`` and attach it; returns notes (empty when fine).

    A file with a well column contributes only the rows that match ``well``.
    Sets ``well.core_data``, ``well.core_path`` and ``well.core_depth_unit``.
    """
    from modules.core_handler import CoreDataHandler
    from modules.well_matching import assign_to_wells

    handler = CoreDataHandler()
    try:
        with open(path, "rb") as handle:
            ok = handler.read_core_from_buffer(handle, depth_unit=depth_unit)
    except OSError as exc:
        return [f"Core file could not be read ({os.path.basename(path)}): {exc.strerror or exc}"]
    if not ok:
        return [f"Core file could not be parsed: {os.path.basename(path)}"]
    if handler.well_names():
        matches, _ = assign_to_wells(
            handler.split_by_well(), [(well.key, well.well_info)], handler.well_kind
        )
        if well.key not in matches:
            return [f"{os.path.basename(path)} has no core data for well {well.display_name}"]
        handler = matches[well.key]
    well.core_data = handler
    well.core_path = path
    well.core_depth_unit = depth_unit
    return []


class SessionService(QObject):
    """
    Service for saving and loading analysis sessions.
    
    Saves all parameter values to JSON file so users don't need
    to re-enter parameters when reopening the application.
    """
    
    session_saved = pyqtSignal(str)  # file path
    session_loaded = pyqtSignal(dict)  # parameters
    error = pyqtSignal(str)
    
    # Session file version for compatibility
    SESSION_VERSION = "2.0"
    SESSION_FIELDS = tuple(_SESSION_DEFAULTS)
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def save_session(self, model, file_path: str) -> bool:
        """
        Save current session parameters to JSON file.
        
        Args:
            model: AppModel instance with all parameters
            file_path: Path to save the session file
            
        Returns:
            True if successful, False otherwise
        """
        temporary_path = None
        try:
            session_data = self._model_to_session_v2(model)

            directory = os.path.dirname(os.path.abspath(file_path)) or "."
            fd, temporary_path = tempfile.mkstemp(
                prefix=f".{os.path.basename(file_path)}.",
                suffix=".tmp",
                dir=directory,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(session_data, handle, indent=2, ensure_ascii=False)
            os.replace(temporary_path, file_path)
            temporary_path = None

            self.session_saved.emit(file_path)
            return True

        except Exception as e:
            logger.exception("Failed to save session")
            self.error.emit(f"Failed to save session: {str(e)}")
            return False
        finally:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass
    
    def load_session(self, file_path: str) -> Optional[Dict]:
        """
        Load session parameters from JSON file.
        
        Args:
            file_path: Path to the session file
            
        Returns:
            Dictionary with session parameters, or None if failed
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
            
            # Check version compatibility while keeping older parameter-only
            # sessions loadable; unknown fields are simply ignored below.
            version = session_data.get("_session_version", "1.0")
            if not (_is_v2(session_data) or str(version).startswith("1.")):
                logger.warning(
                    "Session version %s differs from current version %s; "
                    "loading compatible fields",
                    version,
                    self.SESSION_VERSION,
                )
            
            if not _is_v2(session_data):
                self._upgrade_legacy(session_data)
            self.session_loaded.emit(session_data)
            return session_data
            
        except Exception as e:
            logger.exception("Failed to load session")
            self.error.emit(f"Failed to load session: {str(e)}")
            return None
    
    def apply_session_to_model(self, model, session_data: Dict) -> bool:
        """
        Apply loaded session data to AppModel.
        
        Args:
            model: AppModel instance
            session_data: Dictionary from load_session
            
        Returns:
            True if successful
        """
        try:
            if _is_v2(session_data):
                flat = {
                    k: v for k, v in (session_data.get("global_params") or {}).items()
                    if k not in _PER_WELL_FIELDS
                }
                self._upgrade_legacy(flat)
                self._apply_flat(model, flat)
                if hasattr(model, "project"):
                    model.project.zone_params = copy.deepcopy(
                        session_data.get("zone_params") or {}
                    )
                return True

            self._upgrade_legacy(session_data)
            self._apply_flat(model, session_data)
            if "_las_filename" in session_data and hasattr(model, "las_filename"):
                model.las_filename = session_data["_las_filename"]

            # A v1.x session describes one well: values that were manual
            # there become that well's entries, so they win over the well's
            # AUTO defaults and the results match what the user saw (§4.9).
            active = getattr(model, "active_well", None)
            if active is not None and hasattr(model, "project_params"):
                from modules.param_scopes import legacy_well_overrides

                active.overrides.update(legacy_well_overrides(model.project_params()))

            return True

        except Exception as e:
            logger.exception("Failed to apply session")
            self.error.emit(f"Failed to apply session: {str(e)}")
            return False

    def _apply_flat(self, model, session_data: Dict) -> None:
        """Set the flat project parameters present in ``session_data`` on ``model``."""
        # Analysis mode
        if 'analysis_mode' in session_data:
            model.analysis_mode = session_data['analysis_mode']
        if 'selected_formations' in session_data:
            model.selected_formations = session_data['selected_formations']
        
        # VShale parameters
        if 'vsh_baseline_method' in session_data:
            model.vsh_baseline_method = session_data['vsh_baseline_method']
        if 'gr_min_manual' in session_data:
            model.gr_min_manual = session_data['gr_min_manual']
        if 'gr_max_manual' in session_data:
            model.gr_max_manual = session_data['gr_max_manual']
        if 'vsh_methods' in session_data:
            model.vsh_methods = session_data['vsh_methods']
        
        # Matrix parameters
        if 'rho_matrix' in session_data:
            model.rho_matrix = session_data['rho_matrix']
        if 'dt_matrix' in session_data:
            model.dt_matrix = session_data['dt_matrix']
        if 'nphi_matrix' in session_data:
            model.nphi_matrix = session_data['nphi_matrix']
        
        # Fluid parameters
        if 'rho_fluid' in session_data:
            model.rho_fluid = session_data['rho_fluid']
        if 'dt_fluid' in session_data:
            model.dt_fluid = session_data['dt_fluid']
        
        # Shale parameters
        if 'shale_approach' in session_data:
            model.shale_approach = session_data['shale_approach']
        if 'rho_shale' in session_data:
            model.rho_shale = session_data['rho_shale']
        if 'dt_shale' in session_data:
            model.dt_shale = session_data['dt_shale']
        if 'nphi_shale' in session_data:
            model.nphi_shale = session_data['nphi_shale']
        
        # Archie parameters
        if 'lithology_preset' in session_data:
            model.lithology_preset = session_data['lithology_preset']
        if 'a' in session_data:
            model.a = session_data['a']
        if 'm' in session_data:
            model.m = session_data['m']
        if 'n' in session_data:
            model.n = session_data['n']
        
        # Resistivity parameters
        if 'rw' in session_data:
            model.rw = session_data['rw']
        if 'rsh' in session_data:
            model.rsh = session_data['rsh']
        if 'rw_mode' in session_data:
            model.rw_mode = session_data['rw_mode']
        if 'rsh_mode' in session_data:
            model.rsh_mode = session_data['rsh_mode']
        
        # Permeability parameters
        if 'perm_C' in session_data:
            model.perm_C = session_data['perm_C']
        if 'perm_P' in session_data:
            model.perm_P = session_data['perm_P']
        if 'perm_Q' in session_data:
            model.perm_Q = session_data['perm_Q']
        
        # Swirr parameters
        if 'swirr_method' in session_data:
            model.swirr_method = session_data['swirr_method']
        if 'buckles_preset' in session_data:
            model.buckles_preset = session_data['buckles_preset']
        if 'k_buckles' in session_data:
            model.k_buckles = session_data['k_buckles']
        
        # Cutoff parameters
        if 'vsh_cutoff' in session_data:
            model.vsh_cutoff = session_data['vsh_cutoff']
        if 'phi_cutoff' in session_data:
            model.phi_cutoff = session_data['phi_cutoff']
        if 'sw_cutoff' in session_data:
            model.sw_cutoff = session_data['sw_cutoff']
        
        # Sw Parameters
        if 'sw_methods' in session_data: model.sw_methods = session_data['sw_methods']
        if 'sw_primary_method' in session_data: model.sw_primary_method = session_data['sw_primary_method']
        if 'ws_qv' in session_data: model.ws_qv = session_data['ws_qv']
        if 'ws_b' in session_data: model.ws_b = session_data['ws_b']
        if 'dw_swb' in session_data: model.dw_swb = session_data['dw_swb']
        if 'dw_rwb' in session_data: model.dw_rwb = session_data['dw_rwb']
        
        # Merge settings
        if 'merge_step' in session_data:
            model.merge_step = session_data['merge_step']
        if 'merge_gap_limit' in session_data:
            model.merge_gap_limit = session_data['merge_gap_limit']
        
        # Core settings
        if 'core_depth_unit' in session_data:
            model.core_depth_unit = session_data['core_depth_unit']
        if 'core_max_dist' in session_data:
            model.core_max_dist = session_data['core_max_dist']
        
        # Gas correction (v1.2)
        if 'gas_correction_enabled' in session_data:
            model.gas_correction_enabled = session_data['gas_correction_enabled']
        if 'gas_nphi_factor' in session_data:
            model.gas_nphi_factor = session_data['gas_nphi_factor']
        if 'gas_rhob_factor' in session_data:
            model.gas_rhob_factor = session_data['gas_rhob_factor']

        # Fields introduced after the original 1.2 schema.
        for field in (
            "curve_mapping",
            "primary_phie_method",
            "shale_vsh_threshold",
            "shale_gate_logs",
            "shale_iqr_filter",
            "shale_selection_mode",
            "shale_vsh_quantile",
            "shale_min_points",
            "shale_sweep_tmin",
            "shale_sweep_tmax",
            "shale_sweep_step",
            "temp_correction",
            "surface_temp",
            "temp_gradient",
            "rw_ref_temp",
        ):
            if field in session_data:
                setattr(model, field, session_data[field])

    def restore_wells(self, model, session_data: Dict,
                      progress: Optional[Callable[[str, int], None]] = None) -> List[str]:
        """Re-open the wells of a v2.0 session (synchronously); returns notes.

        For each well entry the source LAS files are parsed again (merged with
        the saved step/gap when there are several), then key, name, curve
        mapping, mode, zones, overrides, tops and core are restored. Results are
        not stored, so every restored well needs a run. Wells whose files are
        missing or unreadable are skipped with a note. Finally the saved active
        well is activated. Existing wells with the same key are replaced; call
        ``model.reset()`` first to start from an empty project. Call
        ``apply_session_to_model`` first (it sets the project parameters and
        project zone parameters). ``progress(message, percent)`` is optional.

        A v1.x session has no LAS paths: nothing is restored and, when no well
        is loaded, the note says the LAS file must be opened manually.
        """
        notes: List[str] = []
        if not _is_v2(session_data):
            if getattr(model, "active_well", None) is None:
                name = session_data.get("_las_filename") or ""
                name = os.path.basename(str(name)) if name else ""
                notes.append(
                    "This session was saved by an older version and does not store its "
                    "LAS files. Open the LAS file manually"
                    + (f" ({name})" if name else "") + " to apply the saved parameters."
                )
            return notes

        from modules.las_handler import LASHandler
        from services.load_service import build_well, parse_file

        entries = session_data.get("wells") or []
        step = session_data.get("merge_step", getattr(model, "merge_step", 0.5))
        gap = session_data.get("merge_gap_limit", getattr(model, "merge_gap_limit", 5.0))
        restored = 0
        for index, entry in enumerate(entries):
            label = entry.get("display_name") or entry.get("key") or f"well {index + 1}"
            if progress:
                progress(f"Restoring {label}...", int(100 * index / max(len(entries), 1)))
            try:
                well = self._restore_one_well(entry, step, gap, notes, parse_file,
                                              build_well, LASHandler)
            except Exception as exc:
                logger.exception("Could not restore well %s", label)
                notes.append(f"{label}: could not be restored ({exc}); skipped.")
                continue
            if well is None:
                continue
            model.add_well(well, activate=False)
            restored += 1

        active_key = session_data.get("active_key")
        if active_key and active_key in model.project:
            model.set_active_well(active_key)
        elif restored and active_key:
            notes.append("The previously active well could not be restored; showing the first well.")
        if progress:
            progress("Session restored", 100)
        return notes

    @staticmethod
    def _restore_one_well(entry, step, gap, notes, parse_file, build_well, LASHandler):
        label = entry.get("display_name") or entry.get("key") or "well"
        paths = [str(p) for p in entry.get("sources") or []]
        if not paths:
            notes.append(f"{label}: the session lists no source files; skipped.")
            return None
        missing = [p for p in paths if not os.path.isfile(p)]
        if missing:
            notes.append(
                f"{label}: source file not found ({', '.join(os.path.basename(p) for p in missing)}); skipped."
            )
            return None
        files = [parse_file(p) for p in paths]
        bad = [f for f in files if not f.ok]
        if bad:
            notes.append(f"{label}: could not read {bad[0].name} ({bad[0].error}); skipped.")
            return None
        merge_result = None
        if len(files) > 1:
            merge_result = LASHandler().merge_las_files(
                [f.parser for f in files], file_identifiers=[f.name for f in files],
                step_ft=entry.get("merge_step", step),
                gap_limit_ft=entry.get("merge_gap_limit", gap),
            )
        ds = build_well(files, merge_result)
        if entry.get("key"):
            ds.key = entry["key"]
        if entry.get("display_name"):
            ds.display_name = entry["display_name"]

        columns = set(ds.las_data.columns)
        for ctype, curve in (entry.get("curve_mapping") or {}).items():
            if curve == "None" or curve in columns:
                ds.curve_mapping[ctype] = curve
            else:
                notes.append(f"{label}: curve {curve} ({ctype}) is no longer in the data; kept {ds.curve_mapping.get(ctype, 'None')}.")
        if entry.get("analysis_mode"):
            ds.analysis_mode = entry["analysis_mode"]
        ds.selected_formations = list(entry.get("selected_formations") or [])
        if "overrides" in entry:
            ds.overrides = copy.deepcopy(entry["overrides"] or {})
        ds.zone_overrides = copy.deepcopy(entry.get("zone_overrides") or {})

        if entry.get("tops_path"):
            path = entry["tops_path"]
            if os.path.isfile(path):
                notes.extend(f"{label}: {n}" for n in attach_tops(ds, path))
            else:
                notes.append(f"{label}: formation tops file not found ({os.path.basename(path)}).")
        if entry.get("core_path"):
            path = entry["core_path"]
            if os.path.isfile(path):
                notes.extend(f"{label}: {n}" for n in attach_core(
                    ds, path, entry.get("core_depth_unit") or "Auto"))
            else:
                notes.append(f"{label}: core file not found ({os.path.basename(path)}).")
        ds.calculated = False
        return ds

    
    @staticmethod
    def _upgrade_legacy(session_data: Dict) -> None:
        """Fill rw_mode/rsh_mode for sessions saved before version 1.4.

        Older pipelines treated ``rw <= 0.01`` as "estimate automatically" and
        always estimated Rsh when the value was not usable.
        """
        if "rw_mode" not in session_data:
            try:
                rw = float(session_data.get("rw", _SESSION_DEFAULTS["rw"]))
            except (TypeError, ValueError):
                rw = _SESSION_DEFAULTS["rw"]
            session_data["rw_mode"] = "auto" if rw <= 0.01 else "manual"
        if "rsh_mode" not in session_data:
            session_data["rsh_mode"] = "auto"

    def _model_to_dict(self, model) -> Dict[str, Any]:
        """Convert known model parameters, tolerating older/minimal models."""
        return {
            field: copy.deepcopy(getattr(model, field, default))
            for field, default in _SESSION_DEFAULTS.items()
        }

    def _model_to_session_v2(self, model) -> Dict[str, Any]:
        """Build the v2.0 session document (parameters + wells; no results)."""
        global_params = {
            k: v for k, v in self._model_to_dict(model).items()
            if k not in _PER_WELL_FIELDS
        }
        project = getattr(model, "project", None)
        wells = []
        for ds in (list(project) if project is not None else []):
            paths = [s_.get("path") for s_ in ds.sources if s_.get("path")]
            if not paths and ds.las_filename and os.path.isfile(str(ds.las_filename)):
                paths = [ds.las_filename]
            wells.append({
                "key": ds.key,
                "display_name": ds.display_name,
                "sources": paths,
                "merged": bool(ds.merged),
                "merge_step": getattr(model, "merge_step", 0.5),
                "merge_gap_limit": getattr(model, "merge_gap_limit", 5.0),
                "curve_mapping": dict(ds.curve_mapping),
                "analysis_mode": ds.analysis_mode,
                "selected_formations": list(ds.selected_formations),
                "overrides": ds.overrides,
                "zone_overrides": ds.zone_overrides,
                "tops_path": getattr(ds, "tops_path", None),
                "core_path": getattr(ds, "core_path", None),
                "core_depth_unit": getattr(ds, "core_depth_unit", None)
                or getattr(model, "core_depth_unit", "Auto"),
            })
        data = {
            "_session_version": self.SESSION_VERSION,
            "global_params": global_params,
            "zone_params": getattr(project, "zone_params", {}) if project is not None else {},
            "wells": wells,
            "active_key": getattr(project, "active_key", None) if project is not None else None,
            "merge_step": getattr(model, "merge_step", 0.5),
            "merge_gap_limit": getattr(model, "merge_gap_limit", 5.0),
        }
        return _json_safe(data)
