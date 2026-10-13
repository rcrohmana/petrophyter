"""
Rock Typing Service for Petrophyter PyQt
Background fit of rock-type definitions from core, plus the apply and staleness helpers.

The worker works on a snapshot taken on the GUI thread and only returns a proposal; it never
writes the model. ``apply_definitions`` is the single place that stores a proposal in
``Project.rock_types`` (P1 rock-typing spec, sections 3, 5.2 and 5.3).
"""

import copy
import hashlib
import json
import logging
import traceback
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from modules import rock_typing as rt

logger = logging.getLogger(__name__)

PROPOSAL_VERSION = 1
POOLED_KEY = "*"
FIT_SCOPES = ("project", "well", "zone")
DISPLAY_KEY = "_display"
DEFAULT_N_RT = 3
# Settings that change a fit; display toggles (lorenz, margin_min, ...) do not make it stale.
FIT_SETTING_KEYS = ("seed", "restarts", "min_samples", "min_per_rt", "ob_phi_factor",
                    "ob_k_factor", "core_phi_min", "core_phi_max")


class _Cancelled(Exception):
    """Raised inside the worker when cancel was requested."""


# ---------------------------------------------------------------------------
# Plain data and fingerprints
# ---------------------------------------------------------------------------
def _plain(value):
    """Recursively convert to plain JSON types (no numpy, no tuples, NaN and inf become None)."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_plain(v) for v in value.tolist()]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        v = float(value)
        return v if np.isfinite(v) else None
    if value is None or isinstance(value, str):
        return value
    return str(value)


def _short_digest(payload: bytes) -> str:
    return hashlib.sha1(payload).hexdigest()[:6]


def _settings_digest(settings: Optional[dict]) -> str:
    merged = dict(rt.DEFAULT_SETTINGS)
    merged.update(settings or {})
    fit = {k: merged[k] for k in FIT_SETTING_KEYS}
    return _short_digest(json.dumps(_plain(fit), sort_keys=True).encode("utf-8"))


def fingerprint_from_inputs(inputs, settings=None, table: Optional[pd.DataFrame] = None) -> dict:
    """``{"core": {well_key: {rows, valid, digest}}, "settings": digest}`` of a core snapshot.

    ``digest`` covers the valid (depth, porosity, permeability) values of the well after the
    overburden factors, so any edit that changes what the fit sees changes it. Pass ``table``
    (from :func:`modules.rock_typing.build_core_table`) to avoid building it twice.
    """
    if table is None:
        table, _ = rt.build_core_table(inputs, settings)
    core: Dict[str, dict] = {}
    for ci in inputs:
        sub = table[table["well_key"] == ci.well_key]
        ok = sub[sub["status"] == rt.STATUS_OK]
        vals = np.round(ok[["depth", "phi", "k"]].to_numpy(dtype=float), 9)
        core[str(ci.well_key)] = {"rows": int(len(sub)), "valid": int(len(ok)),
                                  "digest": _short_digest(np.ascontiguousarray(vals).tobytes())}
    return {"core": core, "settings": _settings_digest(settings)}


def core_fingerprint(model, settings=None) -> dict:
    """Fingerprint of the model's current core (GUI thread)."""
    return fingerprint_from_inputs(rt.core_inputs(model), settings)


def fingerprint_is_stale(defs: Optional[dict], model) -> bool:
    """True when the core or the fit settings changed since ``defs`` was fitted.

    Uses the settings stored in ``defs`` so a later change of unrelated display options does
    not matter. No definitions means nothing is stale.
    """
    if not defs:
        return False
    stored = defs.get("fingerprint")
    if not stored:
        return True
    return core_fingerprint(model, defs.get("settings")) != stored


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
class RockTypingSignals(QObject):
    """Signals for the rock typing worker."""
    started = pyqtSignal()
    progress = pyqtSignal(str, int)   # (message, percentage)
    completed = pyqtSignal(dict)      # the proposal (see RockTypingWorker)
    error = pyqtSignal(str)
    cancelled = pyqtSignal()


class RockTypingWorker(QRunnable):
    """Fit rock-type definitions from a core snapshot on a pool thread.

    ``inputs`` is ``modules.rock_typing.core_inputs(model)`` taken on the GUI thread (see
    :meth:`from_model`). The worker never touches the model; ``completed`` carries the
    proposal dict (section 5.3 shape: version, method, feature, fit_scope, sets, settings,
    fingerprint, fit_report) plus ``_display`` (core table, report, suggestion, fallbacks),
    which :func:`apply_definitions` strips. A refusal (too few rows, a class below the minimum)
    arrives through ``error`` with the message of :class:`RockTypingError`.
    """

    def __init__(self, inputs, settings=None, method: str = "fzi", n_rt: Optional[int] = None,
                 fit_scope: str = "project"):
        super().__init__()
        self.inputs = list(inputs)
        self.settings = dict(settings or {})
        self.method = method
        self.n_rt = n_rt
        self.fit_scope = fit_scope
        self.signals = RockTypingSignals()
        self._cancelled = False

    @classmethod
    def from_model(cls, model, settings=None, method="fzi", n_rt=None, fit_scope="project"):
        """Snapshot the model's core on the calling (GUI) thread."""
        return cls(rt.core_inputs(model), settings, method, n_rt, fit_scope)

    def cancel(self):
        """Ask the worker to stop at its next checkpoint; ``cancelled`` is emitted."""
        self._cancelled = True

    def _check(self):
        if self._cancelled:
            raise _Cancelled()

    def _step(self, message: str, percent: int):
        self._check()
        self.signals.progress.emit(message, percent)

    def run(self):
        try:
            self.signals.started.emit()
            proposal = self._fit()
            self._check()
            self.signals.completed.emit(proposal)
        except _Cancelled:
            self.signals.cancelled.emit()
        except rt.RockTypingError as e:
            self.signals.error.emit(str(e))
        except Exception as e:
            logger.exception("Rock typing fit failed")
            self.signals.error.emit(f"Rock typing failed: {e}\n{traceback.format_exc()}")

    # -- the fit ---------------------------------------------------------------------
    def _fit(self) -> dict:
        if self.method not in ("fzi", "r35"):
            raise rt.RockTypingError(f"Unknown rock typing method '{self.method}'.")
        if self.fit_scope not in FIT_SCOPES:
            raise rt.RockTypingError(f"Unknown fit scope '{self.fit_scope}'.")
        s = dict(rt.DEFAULT_SETTINGS)
        s.update(self.settings)

        self._step("Building core table...", 5)
        table, report = rt.build_core_table(self.inputs, s)
        valid = table[table["status"] == rt.STATUS_OK].copy()
        if self.method == "r35":
            valid["feature"] = np.log10(rt.winland_r35(valid["k"].to_numpy(float),
                                                       valid["phi"].to_numpy(float)))
            feature_name = "log10_r35"
        else:
            valid["feature"] = valid["log_fzi"]
            feature_name = "log10_fzi"
        valid = valid[np.isfinite(valid["feature"].to_numpy(dtype=float))]
        fingerprint = fingerprint_from_inputs(self.inputs, s, table)

        self._step("Suggesting rock type count...", 20)
        suggested, sug_info = rt.suggest_n_rt(valid["feature"].to_numpy(float),
                                              min_per_rt=int(s["min_per_rt"]))
        if self.method == "r35":
            n_rt = len(rt.R35_CLASSES)
        else:
            n_rt = int(self.n_rt or suggested or DEFAULT_N_RT)

        self._step("Fitting the pooled set...", 40)
        n_wells = int(valid["well_key"].nunique())
        sets = {POOLED_KEY: self._fit_set(valid, n_rt, s,
                                          f"pooled, {n_wells} wells, {len(valid)} samples")}

        fallback: Dict[str, str] = {}
        if self.fit_scope != "project":
            groups = self._groups(valid)
            for i, (key, sub) in enumerate(groups):
                self._step(f"Fitting {self.fit_scope} {key}...", 50 + int(40 * i / max(len(groups), 1)))
                if len(sub) < int(s["min_samples"]):
                    fallback[key] = f"{len(sub)} valid samples (minimum {s['min_samples']})"
                    continue
                n_w = int(sub["well_key"].nunique())
                basis = (f"well {key}, {len(sub)} samples" if self.fit_scope == "well"
                         else f"zone {key}, {n_w} wells, {len(sub)} samples")
                try:
                    sets[key] = self._fit_set(sub, n_rt, s, basis)
                except rt.RockTypingError as e:
                    fallback[key] = str(e)
            if self.fit_scope == "well":
                # A well with no valid rows at all also uses the pooled set.
                for ci in self.inputs:
                    wk = str(ci.well_key)
                    if wk not in sets and wk not in fallback:
                        fallback[wk] = "0 valid samples"
        self._step("Done", 100)

        fit_report = {"rows": report["rows"], "valid": report["valid"],
                      "excluded": dict(report["excluded"]),
                      "fallback": dict(fallback)}
        proposal = {
            "version": PROPOSAL_VERSION, "method": self.method, "feature": feature_name,
            "fit_scope": self.fit_scope, "sets": sets,
            "settings": {k: s[k] for k in s}, "fingerprint": fingerprint,
            "fit_report": fit_report,
        }
        proposal = _plain(proposal)
        proposal[DISPLAY_KEY] = {
            "table": table, "report": report, "n_rt": n_rt,
            "suggestion": {"n_rt": suggested, **sug_info}, "fallback": dict(fallback),
        }
        return proposal

    def _groups(self, valid: pd.DataFrame) -> List[tuple]:
        if self.fit_scope == "well":
            keys = [str(ci.well_key) for ci in self.inputs]
            return [(k, valid[valid["well_key"] == k]) for k in keys
                    if (valid["well_key"] == k).any()]
        from modules.param_scopes import UNZONED
        zones = sorted({z for z in valid["zone"].tolist() if z != UNZONED})
        return [(z, valid[valid["zone"] == z]) for z in zones]

    def _fit_set(self, sub: pd.DataFrame, n_rt: int, s: dict, basis: str) -> dict:
        return rt.fit_rock_types(
            sub["feature"].to_numpy(float), n_rt, method=self.method, settings=s,
            phi=sub["phi"].to_numpy(float), k=sub["k"].to_numpy(float),
            log_fzi=sub["log_fzi"].to_numpy(float), basis=basis)


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------
def apply_definitions(model, defs: dict) -> dict:
    """Store ``defs`` in ``model.project.rock_types`` and tell the app it changed.

    Display extras (``_display``) are stripped and the result is converted to plain JSON types
    so the parameter hash is identical after a session save and load. Emits
    ``model.parameters_changed`` (every run well is re-checked for staleness by hash) and marks
    the session dirty. Returns the stored dict.
    """
    stored = copy.deepcopy({k: v for k, v in defs.items() if k != DISPLAY_KEY})
    stored = json.loads(json.dumps(_plain(stored), allow_nan=False))
    model.project.rock_types = stored
    model.mark_dirty()
    model.parameters_changed.emit()
    return stored
