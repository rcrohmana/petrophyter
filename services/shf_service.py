"""
Saturation-Height Service for Petrophyter PyQt
Background fit of saturation-height curves from core Pc or from the logs, plus the explicit
writes (stored fits, fluid contacts) and the free-water-level estimate.

The snapshot is taken on the GUI thread (``collect_core_curves``, ``collect_log_samples``);
the worker only fits and returns a proposal, it never writes the model. ``store_fits`` and
``store_contacts`` are the only places that change the project.
"""

import copy
import logging
import traceback
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from modules.param_scopes import UNZONED, normalize_zone
from modules.shf import (
    ALL, BASIS_CORE, BASIS_LOG, FWL_INSUFFICIENT, FwlEstimate, PcCurve, ShfFit, ZoneFluids,
    estimate_fwl, fit_core_pc, fit_log_sw)
from modules.shf_stage import WATER_DENSITY_RANGE, fits_in_use

logger = logging.getLogger(__name__)

MODE_CORE = "core"
MODE_LOG = "log"
ROCK_TYPE_SOURCES = ("auto", "file", "definitions", "all")
FLUIDS = ("oil", "gas")
DATUMS = ("TVD", "TVDSS")
ZONE_SCOPE_NOTE = ("Rock types are fitted per zone; one saturation-height fit is used for all "
                   "types.")
NO_ROCK_TYPING_NOTE = "Rock typing is off; one fit (All) is used for every sample."


class _Cancelled(Exception):
    """Raised inside the worker when cancel was requested."""


# ---------------------------------------------------------------------------
# Rock-type basis
# ---------------------------------------------------------------------------
def all_only_for(model, ds) -> Tuple[bool, str]:
    """``(all_only, note)``: whether one ``"All"`` fit serves the well, and why.

    True while rock typing is not available for the well, or when the definitions were fitted
    per zone (the ids are then not comparable between zones).
    """
    from modules.pipeline import _shf_all_only
    from modules.rock_typing import rock_types_zone_scoped

    p = model.params_for_well(ds)
    if rock_types_zone_scoped(p.get("rock_types")):
        return True, ZONE_SCOPE_NOTE
    if _shf_all_only(p):
        return True, NO_ROCK_TYPING_NOTE
    return False, ""


def _norm_label(text) -> Optional[str]:
    """A rock-type label from a file as the text of its integer id when it is one."""
    t = str(text if text is not None else "").strip()
    if not t or t.lower() in ("nan", "none"):
        return None
    try:
        v = float(t)
        if np.isfinite(v) and v == int(v):
            return str(int(v))
    except ValueError:
        pass
    return t


def _label_for(source: str, all_only: bool, file_text, phi, k, rt) -> Optional[str]:
    """Rock type of one Pc sample, or None when it ends without a type (excluded)."""
    if all_only or source == "all":
        return ALL
    from modules.rock_typing import classify_pairs

    def from_file():
        return _norm_label(file_text)

    def from_defs():
        if not rt:
            return None
        labels, _ = classify_pairs([phi], [k], rt)
        n = int(labels[0])
        return str(n) if n > 0 else None

    if source == "file":
        return from_file()
    if source == "definitions":
        return from_defs()
    found = from_file()
    if found:
        return found
    return from_defs() if rt else ALL


def _first_finite(series) -> float:
    vals = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    vals = vals[np.isfinite(vals)]
    return float(vals[0]) if len(vals) else float("nan")


# ---------------------------------------------------------------------------
# Snapshots (GUI thread)
# ---------------------------------------------------------------------------
def collect_core_curves(model) -> Tuple[Dict[str, List[PcCurve]], dict]:
    """Pc curves of every well grouped by rock type, and a report of what was used.

    ``report``: ``samples`` (curves seen), ``used``, ``excluded`` (``{reason: n}``),
    ``per_type`` (samples per rock type), ``wells``, ``all_only`` and ``note``.
    """
    shf = model.project.shf
    source = str(shf.get("rock_type_source") or "auto")
    sigma_tbl = shf.get("sigma_cos") or {}
    groups: Dict[str, List[PcCurve]] = {}
    report = {"samples": 0, "used": 0, "excluded": {}, "per_type": {}, "wells": [],
              "all_only": False, "note": ""}
    for ds in model.project.wells:
        pc = getattr(ds, "pc_data", None)
        data = getattr(pc, "data", None)
        if pc is None or data is None or len(data) == 0:
            continue
        p = model.params_for_well(ds)
        all_only, note = all_only_for(model, ds)
        report["all_only"] = report["all_only"] or all_only
        report["note"] = report["note"] or note
        rt = p.get("rock_types")
        for name, frame in pc.curves().items():
            report["samples"] += 1
            k, phi = _first_finite(frame["K"]), _first_finite(frame["PHI"])
            if not (np.isfinite(k) and k > 0 and np.isfinite(phi) and phi > 0):
                report["excluded"]["no permeability or porosity"] = (
                    report["excluded"].get("no permeability or porosity", 0) + 1)
                continue
            system = str(frame["SYSTEM"].iloc[0] or "") if "SYSTEM" in frame else ""
            sigma = sigma_tbl.get(system)
            if sigma is None:
                sigma = _first_finite(frame["SIGMA_COS_LAB"])
            file_text = frame["ROCK_TYPE"].iloc[0] if "ROCK_TYPE" in frame else ""
            label = _label_for(source, all_only, file_text, phi, k, rt)
            if label is None:
                report["excluded"]["no rock type"] = report["excluded"].get("no rock type", 0) + 1
                continue
            curve = PcCurve(pc_psi=frame["PC_PSI"].to_numpy(dtype=float),
                            sw=frame["SW"].to_numpy(dtype=float), k_md=k, phi=phi,
                            sigma_cos_lab=float(sigma), well=str(ds.display_name or ds.key),
                            sample=str(name))
            groups.setdefault(label, []).append(curve)
            report["used"] += 1
            report["per_type"][label] = report["per_type"].get(label, 0) + 1
            if curve.well not in report["wells"]:
                report["wells"].append(curve.well)
    return groups, report


def collect_log_samples(model) -> Tuple[Dict[str, dict], dict]:
    """Net-reservoir samples above the contact of every run well, grouped by rock type.

    Each sample carries ``h_eq = height * delta_rho / sigma_cos_res``, which is all the
    Leverett J of the logs depends on besides k and porosity, so zones with different fluids
    pool into one fit (it is fitted with unit density contrast and unit tension).
    """
    shf = model.project.shf
    sigma_tbl = shf.get("sigma_cos") or {}
    sigma_of = {"oil": sigma_tbl.get("oil-water"), "gas": sigma_tbl.get("gas-water")}
    groups: Dict[str, dict] = {}
    report = {"wells": [], "samples": 0, "note": "", "skipped": []}
    for ds in model.project.wells:
        res, summary = getattr(ds, "results", None), getattr(ds, "summary", None)
        info = (summary or {}).get("shf") if isinstance(summary, dict) else None
        if res is None or not info or "HAFWL" not in res.columns:
            continue
        perm, phie = info.get("perm_source"), info.get("phie_source")
        if perm not in res.columns or phie not in res.columns or "SW" not in res.columns:
            report["skipped"].append(str(ds.display_name or ds.key))
            continue
        h = pd.to_numeric(res["HAFWL"], errors="coerce").to_numpy(dtype=float)
        k = pd.to_numeric(res[perm], errors="coerce").to_numpy(dtype=float)
        phi = pd.to_numeric(res[phie], errors="coerce").to_numpy(dtype=float)
        sw = pd.to_numeric(res["SW"], errors="coerce").to_numpy(dtype=float)
        if "ZONE" in res.columns:
            zl = np.asarray([normalize_zone(z) or UNZONED if isinstance(z, str) else UNZONED
                             for z in res["ZONE"]], dtype=object)
        else:
            zl = np.full(len(res), UNZONED, dtype=object)
        factor = np.full(len(res), np.nan)
        for z, f in (info.get("fluids") or {}).items():
            sig = sigma_of.get(str(f.get("fluid")))
            if sig and np.isfinite(float(sig)) and float(sig) > 0:
                factor[zl == z] = float(f["delta_rho"]) / float(sig)
        ok = (np.isfinite(h) & (h > 0) & np.isfinite(factor) & np.isfinite(k) & (k > 0)
              & np.isfinite(phi) & (phi > 0) & np.isfinite(sw) & (sw > 0) & (sw < 1.0))
        if "NET_RES_FLAG" in res.columns:
            ok &= pd.to_numeric(res["NET_RES_FLAG"], errors="coerce").to_numpy(dtype=float) == 1
        if info.get("rock_type_basis") == "All" or "ROCK_TYPE" not in res.columns:
            types = np.full(len(res), ALL, dtype=object)
        else:
            rt = np.nan_to_num(pd.to_numeric(res["ROCK_TYPE"], errors="coerce")
                               .to_numpy(dtype=float), nan=0.0).astype(int)
            ok &= rt > 0
            types = rt.astype(str).astype(object)
        if not ok.any():
            continue
        name = str(ds.display_name or ds.key)
        report["wells"].append(name)
        for key in dict.fromkeys(types[ok].tolist()):
            m = ok & (types == key)
            g = groups.setdefault(key, {"h_eq": [], "k": [], "phi": [], "sw": [], "wells": []})
            g["h_eq"].append(h[m] * factor[m])
            g["k"].append(k[m])
            g["phi"].append(phi[m])
            g["sw"].append(sw[m])
            if name not in g["wells"]:
                g["wells"].append(name)
            report["samples"] += int(m.sum())
    for g in groups.values():
        for key in ("h_eq", "k", "phi", "sw"):
            g[key] = np.concatenate(g[key])
    return groups, report


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
class ShfSignals(QObject):
    """Signals for the saturation-height fit worker."""
    started = pyqtSignal()
    progress = pyqtSignal(str, int)
    completed = pyqtSignal(dict)      # {"mode", "fits": {key: ShfFit}, "report": dict}
    error = pyqtSignal(str)
    cancelled = pyqtSignal()


class ShfWorker(QRunnable):
    """Fit one curve per rock type on a pool thread from a snapshot taken on the GUI thread."""

    def __init__(self, mode: str, groups: dict, report: dict, model_name: str = "power",
                 weight_by: str = "sample", min_pc_psi: float = 0.0):
        super().__init__()
        self.mode = mode
        self.groups = groups
        self.report = report
        self.model_name = model_name
        self.weight_by = weight_by
        self.min_pc_psi = float(min_pc_psi)
        self.signals = ShfSignals()
        self._cancelled = False

    @classmethod
    def from_model(cls, model, mode: str, model_name: str = "power"):
        """Snapshot the model on the calling (GUI) thread."""
        shf = model.project.shf
        if mode == MODE_LOG:
            groups, report = collect_log_samples(model)
        else:
            groups, report = collect_core_curves(model)
        return cls(mode, groups, report, model_name, str(shf.get("weight_by") or "sample"),
                   float(shf.get("min_pc_psi") or 0.0))

    def cancel(self):
        self._cancelled = True

    def _step(self, message: str, percent: int):
        if self._cancelled:
            raise _Cancelled()
        self.signals.progress.emit(message, percent)

    def run(self):
        try:
            self.signals.started.emit()
            fits = self._fit()
            if self._cancelled:
                raise _Cancelled()
            self.signals.completed.emit({"mode": self.mode, "fits": fits, "report": self.report,
                                         "model": self.model_name})
        except _Cancelled:
            self.signals.cancelled.emit()
        except Exception as e:
            logger.exception("Saturation-height fit failed")
            self.signals.error.emit(f"Saturation-height fit failed: {e}\n{traceback.format_exc()}")

    def _fit(self) -> Dict[str, ShfFit]:
        fits: Dict[str, ShfFit] = {}
        keys = sorted(self.groups, key=lambda s: (len(s), s))
        for i, key in enumerate(keys):
            self._step(f"Fitting rock type {key}...", int(100 * i / max(len(keys), 1)))
            g = self.groups[key]
            if self.mode == MODE_LOG:
                fits[key] = fit_log_sw(g["h_eq"], g["k"], g["phi"], g["sw"], key, self.model_name,
                                       1.0, 1.0, wells=g["wells"])
            else:
                fits[key] = fit_core_pc(g, key, self.model_name, self.weight_by, self.min_pc_psi)
        self._step("Done", 100)
        return fits


# ---------------------------------------------------------------------------
# Explicit writes
# ---------------------------------------------------------------------------
def store_fits(model, fits: Dict[str, ShfFit]) -> dict:
    """Write the usable fits to ``Project.shf["fits"]`` (replacing the stored ones).

    The single write of Apply fit. Marks the session dirty; the caller asks for the stale
    recompute. Returns the stored dict.
    """
    stored = {str(k): f.to_dict() for k, f in fits.items() if f.ok}
    model.project.shf["fits"] = stored
    model.mark_dirty()
    return stored


def parse_contacts(rows: List[dict], datum: str, kb_text: str) -> Tuple[Optional[dict], str]:
    """Contacts dict from table rows, or ``(None, message)`` when a row is refused.

    ``rows``: ``{"zone": None for Default | zone name, "fwl": text, "fluid": str, "water": text}``.
    A blank FWL leaves the row out. Water density must be blank (project value) or within
    :data:`WATER_DENSITY_RANGE`.
    """
    kb = None
    if str(kb_text or "").strip():
        try:
            kb = float(str(kb_text).replace(",", "."))
        except ValueError:
            return None, "KB must be a number (ft)."
        if not np.isfinite(kb):
            return None, "KB must be a number (ft)."
    if datum == "TVDSS" and kb is None:
        return None, "KB required for TVDSS."
    out = {"datum": datum, "kb_ft": kb, "zones": {}}
    for r in rows:
        label = "Default" if r["zone"] is None else f"Zone {r['zone']}"
        fwl_text = str(r.get("fwl") or "").strip()
        if not fwl_text:
            continue
        try:
            fwl = float(fwl_text.replace(",", "."))
        except ValueError:
            return None, f"{label}: the FWL must be a number (ft)."
        if not np.isfinite(fwl):
            return None, f"{label}: the FWL must be a number (ft)."
        water = None
        w_text = str(r.get("water") or "").strip()
        if w_text:
            try:
                water = float(w_text.replace(",", "."))
            except ValueError:
                return None, f"{label}: the water density must be a number (g/cc)."
            lo, hi = WATER_DENSITY_RANGE
            if not (np.isfinite(water) and lo <= water <= hi):
                return None, (f"{label}: water density {w_text} g/cc is outside "
                              f"{lo:g}-{hi:g} g/cc.")
        fluid = str(r.get("fluid") or "oil").lower()
        row = {"fwl": fwl, "fluid": fluid if fluid in FLUIDS else "oil", "water_density": water}
        if r["zone"] is None:
            out["default"] = row
        else:
            out["zones"][r["zone"]] = row
    return out, ""


def store_contacts(ds, contacts: dict) -> bool:
    """Write ``ds.shf_contacts``; True when it changed. The caller marks dirty and stale."""
    if copy.deepcopy(ds.shf_contacts or {}) == contacts:
        return False
    ds.shf_contacts = copy.deepcopy(contacts)
    return True


# ---------------------------------------------------------------------------
# Free water level estimate (GUI thread: one well, one scan)
# ---------------------------------------------------------------------------
def estimate_for_well(model, ds, zone: Optional[str], fluid: str,
                      water_density: Optional[float]) -> FwlEstimate:
    """:func:`modules.shf.estimate_fwl` on the well's last results and the applied fits.

    ``zone`` limits it to one zone (None = every net-reservoir sample). Needs a run with
    saturation height on (the stage names the permeability and porosity columns). The scan is
    on TVD, in ft.
    """
    from modules.pipeline import _tvd_source

    shf = model.project.shf
    res, summary = getattr(ds, "results", None), getattr(ds, "summary", None)
    info = (summary or {}).get("shf") if isinstance(summary, dict) else None
    if res is None or not info:
        return FwlEstimate(FWL_INSUFFICIENT, reason="Run this well with saturation height on first.")
    all_only = info.get("rock_type_basis") == "All"
    fits = fits_in_use(shf, all_only)
    if not fits:
        return FwlEstimate(FWL_INSUFFICIENT, reason="Apply a fit first.")
    perm, phie = info.get("perm_source"), info.get("phie_source")
    if perm not in res.columns or phie not in res.columns or "SW" not in res.columns:
        return FwlEstimate(FWL_INSUFFICIENT, reason="The run has no permeability or porosity column.")
    p = model.params_for_well(ds)
    src = _tvd_source(ds.las_data, p, ds.curve_mapping, noun="heights")
    depth = pd.to_numeric(res["DEPTH"], errors="coerce").to_numpy(dtype=float)
    tvd = np.asarray(src.at(depth), dtype=float)
    mask = np.ones(len(res), dtype=bool)
    if "NET_RES_FLAG" in res.columns:
        mask &= pd.to_numeric(res["NET_RES_FLAG"], errors="coerce").to_numpy(dtype=float) == 1
    if zone is not None and "ZONE" in res.columns:
        zl = np.asarray([normalize_zone(z) or UNZONED if isinstance(z, str) else UNZONED
                         for z in res["ZONE"]], dtype=object)
        mask &= zl == zone
    if all_only or "ROCK_TYPE" not in res.columns:
        types = np.full(len(res), ALL, dtype=object)
    else:
        rt = np.nan_to_num(pd.to_numeric(res["ROCK_TYPE"], errors="coerce")
                           .to_numpy(dtype=float), nan=0.0).astype(int)
        mask &= rt > 0
        types = rt.astype(str).astype(object)
    fluids = shf.get("fluids") or {}
    water = fluids.get("water") if water_density is None else water_density
    sigma = (shf.get("sigma_cos") or {}).get("gas-water" if fluid == "gas" else "oil-water")
    rho = fluids.get(fluid)
    if water is None or rho is None or sigma is None:
        return FwlEstimate(FWL_INSUFFICIENT, reason="A fluid density or interfacial tension is missing.")
    try:
        zf = ZoneFluids(float(water), float(rho))
        return estimate_fwl(
            tvd[mask], pd.to_numeric(res[perm], errors="coerce").to_numpy(dtype=float)[mask],
            pd.to_numeric(res[phie], errors="coerce").to_numpy(dtype=float)[mask],
            pd.to_numeric(res["SW"], errors="coerce").to_numpy(dtype=float)[mask],
            types[mask], fits, zf, float(sigma))
    except ValueError as exc:
        return FwlEstimate(FWL_INSUFFICIENT, reason=str(exc))
