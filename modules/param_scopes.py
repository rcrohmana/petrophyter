"""
Parameter scopes: project, project · zone, well, well · zone.

Spec docs/specs/2026-10-10-multi-well-audit-design.md §4. Pure Python, no Qt.

Storage
-------
* **Project** values are the flat analysis parameters (``PARAM_DEFAULTS`` keys)
  held by ``AppModel``. Modes at this scope come from the existing flat keys
  (``rw_mode``, ``rsh_mode``, ``vsh_baseline_method``).
* **Project · zone**, **well** and **well · zone** values are *entries*
  ``{"mode": "auto"|"manual", "value": ..., "source": ...}`` keyed by a
  parameter name from :data:`SPECS`. No entry (or mode ``inherit``) falls
  through to the next scope.

Resolution for a sample in zone *Z* of well *W* (§4.4)::

    well · zone  >  project · zone  >  well  >  project

A parameter that is not zone-overridable skips the zone scopes, and a
project-only parameter ignores every entry.
"""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

AUTO, MANUAL, INHERIT = "auto", "manual", "inherit"

# Shale-point parameters, estimated together from one shale selection. Flat
# parameters list those in AUTO mode under ``flat["shale_auto"]`` (absent when
# none is, so project-only parameters are unchanged).
SHALE_PARAMS = ("rho_shale", "dt_shale", "nphi_shale")
SHALE_AUTO_KEY = "shale_auto"
UNZONED = "(unzoned)"

PROJECT, PROJECT_ZONE, WELL, WELL_ZONE = "project", "project·zone", "well", "well·zone"

# Lithology preset -> Archie constants. A named preset at a scope supplies a, m
# and n there (see ``_preset_supply``); "Custom" supplies nothing.
LITHOLOGY_CUSTOM = "Custom"
LITHOLOGY_PRESETS: Dict[str, Dict[str, float]] = {
    "Sandstone (Humble)": {"a": 0.62, "m": 2.15, "n": 2.0},
    "Carbonate": {"a": 1.0, "m": 2.0, "n": 2.0},
}
ARCHIE_KEYS = ("a", "m", "n")
PRESET_SOURCE_SUFFIX = " (lithology preset)"

# Specificity of a scope (§4.4): well·zone > project·zone > well > project.
_SCOPE_RANK = {PROJECT: 0, WELL: 1, PROJECT_ZONE: 2, WELL_ZONE: 3}

GR_AUTO = "Statistically (Auto)"
GR_MANUAL = "Custom (Manual)"


@dataclass(frozen=True)
class ParamSpec:
    name: str
    label: str
    keys: Tuple[str, ...]
    well: bool = True
    zone: bool = True
    auto: bool = False


def _spec(name, label, keys=None, well=True, zone=True, auto=False):
    return ParamSpec(name, label, tuple(keys or (name,)), well, zone, auto)


# Scoped parameters (§4.5). Everything else in PARAM_DEFAULTS is project-only.
SPECS: Dict[str, ParamSpec] = {s.name: s for s in (
    _spec("a", "a"),
    _spec("m", "m"),
    _spec("n", "n"),
    _spec("lithology_preset", "Lithology"),
    _spec("rho_matrix", "ρ matrix"),
    _spec("dt_matrix", "Δt matrix"),
    _spec("nphi_matrix", "NPHI matrix"),
    _spec("gas_correction_enabled", "Gas correction"),
    _spec("gr_baseline", "GR clean/shale",
          ("vsh_baseline_method", "gr_min_manual", "gr_max_manual"), auto=True),
    _spec("rho_shale", "ρ shale", auto=True),
    _spec("dt_shale", "Δt shale", auto=True),
    _spec("nphi_shale", "NPHI shale", auto=True),
    _spec("rw", "Rw", ("rw", "rw_mode"), auto=True),
    _spec("rsh", "Rsh", ("rsh", "rsh_mode"), auto=True),
    _spec("ws_qv", "WS Qv"),
    _spec("ws_b", "WS B"),
    _spec("dw_swb", "DW Swb"),
    _spec("dw_rwb", "DW Rwb"),
    _spec("perm_C", "Perm C"),
    _spec("perm_P", "Perm P"),
    _spec("perm_Q", "Perm Q"),
    _spec("k_buckles", "k Buckles"),
    _spec("vsh_cutoff", "Vsh cutoff"),
    _spec("phi_cutoff", "Phi cutoff"),
    _spec("sw_cutoff", "Sw cutoff"),
    # Well-only properties.
    _spec("rho_fluid", "ρ fluid", zone=False),
    _spec("dt_fluid", "Δt fluid", zone=False),
    _spec("temp_correction", "Temperature correction", zone=False),
    _spec("surface_temp", "Surface temperature", zone=False),
    _spec("temp_gradient", "Temperature gradient", zone=False, auto=True),
    _spec("rw_ref_temp", "Rw reference temperature", zone=False),
    _spec("temp_datum_depth", "Temperature datum depth", zone=False),
    # Zone-capable like Rsh itself: a zone's calibrated Rsh keeps its temperature.
    _spec("rsh_ref_temp", "Rsh reference temperature"),
    _spec("ws_b_auto", "WS B from temperature", zone=False),
)}

# Well-only parameters that are left out of the sources tables while they hold
# their inactive value, so a run without them reports exactly what it did before.
OPTIONAL_SOURCE_PARAMS: Dict[str, tuple] = {
    "temp_datum_depth": (None, 0, 0.0),
    "rsh_ref_temp": (None,),
    "ws_b_auto": (None, False),
}

ZONE_PARAMS: Tuple[str, ...] = tuple(n for n, s in SPECS.items() if s.zone)
WELL_PARAMS: Tuple[str, ...] = tuple(n for n, s in SPECS.items() if s.well)
AUTO_PARAMS: Tuple[str, ...] = tuple(n for n, s in SPECS.items() if s.auto)

# Flat key -> scoped parameter name.
KEY_TO_PARAM: Dict[str, str] = {k: s.name for s in SPECS.values() for k in s.keys}

# Zone AUTO estimates need at least this much data (§4.4), else fall back.
ZONE_AUTO_MIN_SAMPLES = 30
ZONE_AUTO_MIN_FT = 15.0

# Plausibility ranges for per-scope validation (§4.7 rule 5).
VALID_RANGES = {
    "m": (1.3, 3.0),
    "n": (1.5, 3.0),
    "a": (0.3, 2.0),
    "rw": (0.005, 10.0),
    "rsh": (0.1, 1000.0),
    "rho_matrix": (2.5, 3.0),
    "vsh_cutoff": (0.0, 1.0),
    "phi_cutoff": (0.0, 0.5),
    "sw_cutoff": (0.0, 1.0),
}


def normalize_zone(name) -> str:
    """Formation name used as a zone key: stripped, upper-case, single spaces."""
    return re.sub(r"\s+", " ", str(name or "")).strip().upper()


def is_project_only(key: str) -> bool:
    return key not in KEY_TO_PARAM


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------
def make_entry(mode: str, value=None, source: Optional[str] = None) -> Dict:
    entry = {"mode": mode, "value": value}
    if source:
        entry["source"] = source
    return entry


def _active(entry) -> bool:
    return isinstance(entry, dict) and entry.get("mode") in (AUTO, MANUAL)


def project_entry(name: str, global_params: Dict) -> Dict:
    """The project-scope entry of a scoped parameter, read from the flat keys."""
    if name == "gr_baseline":
        mode = MANUAL if global_params.get("vsh_baseline_method") == GR_MANUAL else AUTO
        return make_entry(mode, [global_params.get("gr_min_manual"),
                                 global_params.get("gr_max_manual")])
    if name in ("rw", "rsh"):
        mode = AUTO if global_params.get(f"{name}_mode") == AUTO else MANUAL
        return make_entry(mode, global_params.get(name))
    return make_entry(MANUAL, global_params.get(name))


def apply_entry(flat: Dict, name: str, entry: Dict) -> None:
    """Write a resolved entry into flat pipeline parameters."""
    mode, value = entry.get("mode"), entry.get("value")
    if name == "gr_baseline":
        flat["vsh_baseline_method"] = GR_AUTO if mode == AUTO else GR_MANUAL
        if mode == MANUAL and isinstance(value, (list, tuple)) and len(value) == 2:
            flat["gr_min_manual"], flat["gr_max_manual"] = float(value[0]), float(value[1])
    elif name in ("rw", "rsh"):
        flat[f"{name}_mode"] = AUTO if mode == AUTO else MANUAL
        if mode == MANUAL and value is not None:
            flat[name] = value
    elif name in SHALE_PARAMS:
        auto = set(flat.get(SHALE_AUTO_KEY) or ())
        if mode == AUTO:
            auto.add(name)
        else:
            auto.discard(name)
            if mode == MANUAL:
                flat[name] = value
        if auto:
            flat[SHALE_AUTO_KEY] = sorted(auto)
        else:
            flat.pop(SHALE_AUTO_KEY, None)
    elif mode == MANUAL:
        flat[name] = value
    # AUTO for other parameters (temperature gradient) is resolved by the caller.


def flat_value(name: str, flat: Dict):
    """The value of a scoped parameter in flat parameters (gr_baseline → [min, max])."""
    if name == "gr_baseline":
        return [flat.get("gr_min_manual"), flat.get("gr_max_manual")]
    return flat.get(name)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def winning_entry(name: str, global_params: Dict, overrides: Optional[Dict] = None,
                  zone_params: Optional[Dict] = None,
                  zone_overrides: Optional[Dict] = None,
                  zone: Optional[str] = None) -> Tuple[Dict, str]:
    """``(entry, scope)`` of the most specific non-inherit entry (§4.4)."""
    spec = SPECS[name]
    z = normalize_zone(zone) if zone and zone != UNZONED else None
    candidates = []
    if spec.zone and z:
        candidates.append(((zone_overrides or {}).get(z, {}).get(name), WELL_ZONE))
        candidates.append(((zone_params or {}).get(z, {}).get(name), PROJECT_ZONE))
    if spec.well:
        candidates.append(((overrides or {}).get(name), WELL))
    for entry, scope in candidates:
        if _active(entry):
            return entry, scope
    return project_entry(name, global_params), PROJECT


def source_label(entry: Dict, scope: str) -> str:
    """Provenance shown to the user: ``well``, ``auto``, ``calibrated`` …"""
    if entry.get("mode") == AUTO:
        return "auto" if scope in (PROJECT, WELL) else f"auto ({scope})"
    if entry.get("source") == "calibrated":
        return "calibrated"
    return scope


def resolve(global_params: Dict, overrides: Optional[Dict] = None,
            zone_params: Optional[Dict] = None, zone_overrides: Optional[Dict] = None,
            zone: Optional[str] = None, header: Optional[Dict] = None
            ) -> Tuple[Dict, Dict[str, Dict]]:
    """Effective flat parameters for one well (and optionally one zone).

    Returns ``(flat, info)``. ``info[name] = {"scope", "mode", "source"}`` for
    every scoped parameter. ``header`` (the well's LAS header) feeds the
    temperature-gradient AUTO estimate; it may carry ``_td_tvd_ft`` (TD on the
    well's TVD source, see :func:`header_with_tvd_td`).
    """
    flat = dict(global_params)
    info: Dict[str, Dict] = {}
    for name in SPECS:
        entry, scope = winning_entry(name, global_params, overrides, zone_params,
                                     zone_overrides, zone)
        apply_entry(flat, name, entry)
        info[name] = {"scope": scope, "mode": entry.get("mode"),
                      "source": source_label(entry, scope)}
    _apply_preset_supply(flat, info, global_params, overrides, zone_params,
                         zone_overrides, zone)
    if info["temp_gradient"]["mode"] == AUTO:
        gradient = gradient_from_header(header, flat.get("surface_temp"),
                                        flat.get("temp_datum_depth"))
        if gradient is None:
            info["temp_gradient"]["source"] = "auto unavailable (project)"
        else:
            flat["temp_gradient"] = gradient
            info["temp_gradient"]["source"] = "auto (LAS header)"
    return flat, info


def _preset_supply(name: str, entry: Dict, scope: str) -> Optional[Dict[str, float]]:
    """The a/m/n table a winning lithology-preset entry supplies, or None."""
    if name != "lithology_preset" or scope == PROJECT or entry.get("mode") != MANUAL:
        return None
    return LITHOLOGY_PRESETS.get(entry.get("value"))


def _apply_preset_supply(flat: Dict, info: Dict, global_params: Dict, overrides,
                         zone_params, zone_overrides, zone) -> None:
    """A named preset at scope S supplies a, m, n unless one has an explicit entry
    at S or at a more specific scope. At the flat project scope nothing changes
    (the project preset UI writes the flat a/m/n itself)."""
    entry, scope = winning_entry("lithology_preset", global_params, overrides,
                                 zone_params, zone_overrides, zone)
    table = _preset_supply("lithology_preset", entry, scope)
    if table is None:
        return
    for key in ARCHIE_KEYS:
        if _SCOPE_RANK[info[key]["scope"]] >= _SCOPE_RANK[scope]:
            continue
        flat[key] = table[key]
        info[key] = {"scope": scope, "mode": MANUAL,
                     "source": scope + PRESET_SOURCE_SUFFIX, "preset": True}


def collapse_preset_entries(store: Optional[Dict]) -> bool:
    """D10: drop explicit a/m/n entries equal to the preset values at the same scope.

    ``store`` is one entries dict (a well's overrides or one zone's entries). The
    preset entry stays; entries that differ stay explicit. Returns True when
    anything was removed.
    """
    if not isinstance(store, dict):
        return False
    preset = store.get("lithology_preset")
    if not (_active(preset) and preset.get("mode") == MANUAL):
        return False
    table = LITHOLOGY_PRESETS.get(preset.get("value"))
    if table is None:
        return False
    entries = [store.get(k) for k in ARCHIE_KEYS]
    if not all(_active(e) and e.get("mode") == MANUAL for e in entries):
        return False
    try:
        equal = all(math.isclose(float(e.get("value")), table[k], rel_tol=1e-9, abs_tol=1e-9)
                    for k, e in zip(ARCHIE_KEYS, entries))
    except (TypeError, ValueError):
        return False
    if not equal:
        return False
    for k in ARCHIE_KEYS:
        del store[k]
    return True


def collapse_preset_stores(*stores: Optional[Dict]) -> bool:
    """Apply :func:`collapse_preset_entries` to entry stores and zone maps.

    Each argument is either a single entries dict or a ``{zone: entries}`` map
    (told apart by whether its values are dicts of entries).
    """
    changed = False
    for store in stores:
        if not isinstance(store, dict):
            continue
        if any(k in SPECS for k in store):
            changed |= collapse_preset_entries(store)
        else:
            for entries in store.values():
                changed |= collapse_preset_entries(entries)
    return changed


def zone_plan(global_params: Dict, overrides: Optional[Dict], zone_params: Optional[Dict],
              zone_overrides: Optional[Dict], zones: Iterable[str],
              header: Optional[Dict] = None) -> Dict[str, Dict]:
    """Per-zone parameters for the zones whose resolution differs from the well.

    Returns ``{ZONE: {"params": flat, "info": info, "zone_keys": [...],
    "zone_auto": [...]}}`` where ``zone_keys`` lists the scoped parameters won
    by a zone scope and ``zone_auto`` those among them in AUTO mode (estimated
    on the zone's samples, with fallback). Zones that resolve exactly like the
    well are omitted, so a project without zone entries yields ``{}``.
    """
    plan = {}
    for zone in zones:
        z = normalize_zone(zone)
        if not z or z == UNZONED:
            continue
        flat, info = resolve(global_params, overrides, zone_params, zone_overrides, z, header)
        zone_keys = [n for n, i in info.items() if i["scope"] in (WELL_ZONE, PROJECT_ZONE)]
        if not zone_keys:
            continue
        zone_auto = [n for n in zone_keys if info[n]["mode"] == AUTO]
        plan[z] = {
            "params": flat,
            "info": info,
            "zone_keys": zone_keys,
            "zone_auto": zone_auto,
            "fallback": {n: _auto_fallback(n, info[n]["scope"], zone_params, z)
                         for n in zone_auto},
        }
    return plan


def _auto_fallback(name: str, scope: str, zone_params: Optional[Dict], zone: str) -> Dict:
    """Where a zone AUTO estimate falls back to when the zone has too little data.

    A well · zone AUTO falls back to a MANUAL project · zone entry when there is
    one; otherwise (and for a project · zone AUTO) to the well's resolved value.
    """
    if scope == WELL_ZONE:
        entry = (zone_params or {}).get(zone, {}).get(name)
        if isinstance(entry, dict) and entry.get("mode") == MANUAL:
            return {"scope": PROJECT_ZONE, "value": entry.get("value")}
    return {"scope": WELL}


def default_well_overrides(header: Optional[Dict] = None) -> Dict[str, Dict]:
    """Well-scope entries for a newly loaded well (§4.3).

    AUTO where an estimator exists (Rw, Rsh, GR baseline; temperature gradient
    when the header has BHT and TD); everything else inherits.
    """
    entries = {name: make_entry(AUTO) for name in ("rw", "rsh", "gr_baseline")}
    if gradient_from_header(header, 80.0) is not None:
        entries["temp_gradient"] = make_entry(AUTO)
    return entries


def legacy_well_overrides(global_params: Dict) -> Dict[str, Dict]:
    """Well entries that reproduce a v1.x single-well session (§4.9).

    Values that were effectively manual become well MANUAL entries; values
    that were auto become well AUTO entries, so the project defaults stay
    untouched and the results match what the user saw before.
    """
    entries = {}
    for name in ("rw", "rsh", "gr_baseline"):
        entry = project_entry(name, global_params)
        entries[name] = entry if entry["mode"] == MANUAL else make_entry(AUTO)
    return entries


# ---------------------------------------------------------------------------
# Temperature (P3)
# ---------------------------------------------------------------------------
def _to_degf(value, unit: str) -> float:
    unit = str(unit or "").upper().replace("°", "").replace("DEG", "").strip()
    return value * 9.0 / 5.0 + 32.0 if unit in ("C", "DEGC", "CELSIUS") else value


def _to_ft(value, unit: str) -> float:
    unit = str(unit or "").upper().strip()
    return value * 3.28084 if unit in ("M", "METER", "METERS", "METRE", "METRES") else value


def gradient_from_header(header: Optional[Dict], surface_temp_f,
                         datum_ft=None) -> Optional[float]:
    """Geothermal gradient (°F/100 ft) from BHT at TD, or None.

    ``g = (BHT - Ts) / (TVD_TD - d0) * 100`` on the temperature datum ``d0``
    (``datum_ft``, default 0). ``TVD_TD`` is ``header["_td_tvd_ft"]`` when the
    well has a TVD curve, else the header TD itself (MD, assumed vertical).
    Units: BHT in °C/°F (``bht_unit``), TD in m/ft (``td_unit``); unitless
    values are taken as °F and ft.
    """
    header = header or {}
    bht, td = header.get("bht"), header.get("td")
    if not isinstance(bht, (int, float)) or not isinstance(td, (int, float)):
        return None
    if surface_temp_f is None:
        return None
    bht_f = _to_degf(float(bht), header.get("bht_unit"))
    td_ft = header.get("_td_tvd_ft")
    td_ft = _to_ft(float(td), header.get("td_unit")) if td_ft is None else float(td_ft)
    height = td_ft - float(datum_ft or 0.0)
    if height <= 0 or bht_f <= float(surface_temp_f):
        return None
    return round((bht_f - float(surface_temp_f)) / height * 100.0, 4)


ARPS_OFFSET_F = 6.77


def formation_temperature(depth_ft, surface_temp_f: float, gradient_f_per_100ft: float,
                          datum_ft: float = 0.0):
    """T(z) = Ts + g (z - d0) / 100 in °F (scalars and arrays).

    ``depth_ft`` is TVD on the same datum as ``datum_ft`` (the depth at which
    ``surface_temp_f`` applies); with the default datum 0 and MD it is the
    vertical-well form.
    """
    return surface_temp_f + gradient_f_per_100ft * (depth_ft - datum_ft) / 100.0


def arps_factor(temp_f, ref_temp_f: float):
    """Multiplier taking a resistivity at ``ref_temp_f`` to ``temp_f`` (Arps, °F)."""
    return (ref_temp_f + ARPS_OFFSET_F) / (temp_f + ARPS_OFFSET_F)


# Floor of the Juhasz correlation's temperature (°C): it is a fit to roughly
# 25-200 °C data and its numerator turns negative below about 6 °C.
JUHASZ_MIN_TEMP_C = 25.0


def juhasz_b(temp_f, rw_at_temp):
    """Waxman-Smits B (mho cm²/meq) from temperature and Rw (Juhasz, 1981).

    ``B = (-1.28 + 0.225 T - 0.0004059 T²) / (1 + Rw^1.23 (0.045 T - 0.27))``
    with ``T`` in °C and ``Rw`` the brine resistivity AT that temperature. ``T``
    is floored at :data:`JUHASZ_MIN_TEMP_C`. Works on scalars and arrays.
    """
    t_c = np.maximum((np.asarray(temp_f, dtype=float) - 32.0) * 5.0 / 9.0, JUHASZ_MIN_TEMP_C)
    rw = np.asarray(rw_at_temp, dtype=float)
    return (-1.28 + 0.225 * t_c - 0.0004059 * t_c ** 2) / (
        1.0 + np.power(rw, 1.23) * (0.045 * t_c - 0.27)
    )


# ---------------------------------------------------------------------------
# True vertical depth for formation temperature (C)
# ---------------------------------------------------------------------------
TVD_MNEMONICS = ("TVD", "TVDKB", "TVDRKB", "TVDRT", "TVDBRT")
TVD_MONOTONIC_TOL_FT = 0.01     # numerical noise allowed when checking dTVD/dMD >= 0
TVD_OVER_MD_TOL_FT = 1.0        # TVD may exceed MD by at most this much


def is_tvd_like(name) -> bool:
    """True for the mnemonics auto-mapped to the TVD curve type."""
    return str(name or "").upper() in TVD_MNEMONICS


@dataclass
class TvdSource:
    """TVD (ft) as a function of MD (ft) for one well, with its provenance.

    ``kind`` is ``"curve"`` (a mapped TVD curve), ``"index"`` (the depth index
    is TVD) or ``"md"`` (measured depth, assumed vertical). ``label`` is the
    text recorded as the source of the temperatures; ``notes`` are warnings
    (a rejected curve, an unmapped TVD-like curve, header deviation).
    """

    kind: str
    label: str
    notes: List[str]
    extrapolated: float = 0.0
    _md: Optional[np.ndarray] = None
    _tvd: Optional[np.ndarray] = None
    _slope_lo: float = 1.0
    _slope_hi: float = 1.0

    def at(self, md):
        """TVD at measured depth(s); outside a curve's coverage the edge slope applies."""
        md = np.asarray(md, dtype=float)
        if self.kind != "curve":
            return md
        out = np.interp(md, self._md, self._tvd)
        out = np.where(md < self._md[0], self._tvd[0] + self._slope_lo * (md - self._md[0]), out)
        return np.where(md > self._md[-1], self._tvd[-1] + self._slope_hi * (md - self._md[-1]), out)


def _curve_tvd_source(md, tvd, name, notes) -> Optional[TvdSource]:
    """A :class:`TvdSource` from a mapped curve, or None (reason appended to ``notes``)."""
    ok = np.isfinite(md) & np.isfinite(tvd)
    order = np.argsort(md[ok], kind="stable")
    m, t = md[ok][order], tvd[ok][order]
    m, first = np.unique(m, return_index=True)
    t = t[first]
    if len(m) < 2:
        notes.append(f"TVD curve {name} has fewer than two valid samples; MD was used.")
        return None
    if np.any(np.diff(t) < -TVD_MONOTONIC_TOL_FT):
        notes.append(f"TVD curve {name} is not non-decreasing with MD (wrong curve or TVDSS?); "
                     "MD was used.")
        return None
    if np.any(t > m + TVD_OVER_MD_TOL_FT):
        notes.append(f"TVD curve {name} exceeds MD by more than {TVD_OVER_MD_TOL_FT:g} ft "
                     "(wrong curve or units?); MD was used.")
        return None

    def edge_slope(dm, dt):
        # dTVD/dMD cannot lie outside [0, 1] for a real wellbore.
        return float(np.clip(dt / dm, 0.0, 1.0))

    finite_md = md[np.isfinite(md)]
    outside = float(np.mean((finite_md < m[0]) | (finite_md > m[-1]))) if len(finite_md) else 0.0
    label = f"TVD curve {name}"
    if outside > 0:
        label += f", {outside * 100:.0f}% of samples extrapolated"
    return TvdSource("curve", label, notes, outside, m, t,
                     edge_slope(m[1] - m[0], t[1] - t[0]),
                     edge_slope(m[-1] - m[-2], t[-1] - t[-2]))


def header_deviation_hint(header: Optional[Dict]) -> bool:
    """True when the header has an inclination / deviation entry."""
    return any(("incl" in str(k).lower() or "devi" in str(k).lower()) for k in (header or {}))


def resolve_tvd(data, tvd_curve=None, depth_reference=None,
                deviation_hint: bool = False) -> TvdSource:
    """TVD source for a well: mapped curve, then TVD depth index, then MD (§5.1).

    ``data`` has the ``DEPTH`` column (MD, or TVD when ``depth_reference`` is
    ``"TVD"``). A mapped curve that is not monotonic with MD, or that exceeds
    MD by more than 1 ft, is rejected with a note and the next source is used.
    Gaps inside a curve are interpolated linearly. The depth index itself is
    never taken as a TVD curve.
    """
    md = np.asarray(data["DEPTH"], dtype=float)
    notes: List[str] = []
    name = tvd_curve if tvd_curve and tvd_curve not in ("None", "DEPTH") else None
    if name is not None:
        if name not in data.columns:
            notes.append(f"TVD curve {name} is not in the data; MD was used.")
        else:
            tvd = pd.to_numeric(data[name], errors="coerce").to_numpy(dtype=float)
            source = _curve_tvd_source(md, tvd, name, notes)
            if source is not None:
                return source
    if str(depth_reference or "").upper() == "TVD":
        return TvdSource("index", "depth index (TVD)", notes)
    like = [c for c in data.columns if c != "DEPTH" and is_tvd_like(c)]
    if name is None and like:
        notes.append(f"Curve {like[0]} looks like TVD but is not mapped; temperatures "
                     "assume a vertical well. Map it in Curve Mapping.")
    elif name is None and deviation_hint:
        notes.append("The header has an inclination/deviation entry but no TVD curve is "
                     "mapped; temperatures assume a vertical well.")
    return TvdSource("md", "MD (assumed vertical)", notes)


def header_with_tvd_td(header: Optional[Dict], data, tvd_curve, depth_reference) -> Dict:
    """Copy of the header carrying ``_td_tvd_ft`` when a TVD curve maps TD to TVD.

    Only a mapped, valid TVD curve changes anything: with the depth index in TVD
    the header TD is taken as given, and without a TVD source TD stays MD.
    """
    header = dict(header or {})
    td = header.get("td")
    if data is None or "DEPTH" not in getattr(data, "columns", ()) or not isinstance(td, (int, float)):
        return header
    if not tvd_curve or tvd_curve == "None":
        return header
    source = resolve_tvd(data, tvd_curve, depth_reference)
    if source.kind == "curve":
        header["_td_tvd_ft"] = float(source.at(_to_ft(float(td), header.get("td_unit"))))
    return header


def temperature_readout(data, tvd_curve, depth_reference, header, flat) -> List[str]:
    """Lines for the Temperature section: T at log top/bottom and the header gradient.

    ``flat`` supplies ``surface_temp``, ``temp_gradient`` and ``temp_datum_depth``.
    """
    lines: List[str] = []
    header = dict(header or {})
    surface = float(flat.get("surface_temp") or 0.0)
    gradient_now = float(flat.get("temp_gradient") or 0.0)
    datum = float(flat.get("temp_datum_depth") or 0.0)
    if data is not None and "DEPTH" in getattr(data, "columns", ()) and len(data):
        source = resolve_tvd(data, tvd_curve, depth_reference, header_deviation_hint(header))
        t_top, t_bottom = (
            float(formation_temperature(source.at(d), surface, gradient_now, datum))
            for d in (float(data["DEPTH"].min()), float(data["DEPTH"].max()))
        )
        lines.append(f"T at log top / bottom: {t_top:.0f} / {t_bottom:.0f} °F ({source.label})")
    bht, td = header.get("bht"), header.get("td")
    if isinstance(bht, (int, float)) and isinstance(td, (int, float)):
        header = header_with_tvd_td(header, data, tvd_curve, depth_reference)
        gradient = gradient_from_header(header, surface, datum)
        if gradient is not None:
            td_ft = _to_ft(float(td), header.get("td_unit"))
            where = "MD" if "_td_tvd_ft" not in header else f"MD, TVD {header['_td_tvd_ft']:,.0f} ft"
            lines.append(
                f"header: {_to_degf(float(bht), header.get('bht_unit')):.0f} °F at TD "
                f"{td_ft:,.0f} ft ({where}) → gradient {gradient:.2f} °F/100 ft"
            )
    return lines


# ---------------------------------------------------------------------------
# Validation, copying, hashing
# ---------------------------------------------------------------------------
def validate_entry(name: str, value) -> Optional[str]:
    """A warning for an implausible value, or None."""
    from modules.statistics_utils import MIN_GR_SEPARATION

    if value is None:
        return None
    if name == "gr_baseline":
        try:
            lo, hi = float(value[0]), float(value[1])
        except (TypeError, ValueError, IndexError):
            return "GR baseline needs a clean and a shale value."
        if hi - lo < MIN_GR_SEPARATION:
            return (f"GR clean/shale separation {hi - lo:g} API is below "
                    f"{MIN_GR_SEPARATION:g} API.")
        return None
    bounds = VALID_RANGES.get(name)
    if bounds is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    lo, hi = bounds
    if not lo <= v <= hi:
        return f"{SPECS[name].label} = {v:g} is outside {lo:g}–{hi:g}."
    return None


def zones_with_entries(*zone_maps: Optional[Dict]) -> List[str]:
    """Zone names that hold at least one active entry, in first-seen order."""
    seen: List[str] = []
    for zone_map in zone_maps:
        for zone, entries in (zone_map or {}).items():
            if any(_active(e) for e in (entries or {}).values()) and zone not in seen:
                seen.append(zone)
    return seen


def params_hash(params: Dict) -> str:
    """Stable hash of effective parameters, for per-well stale tracking (§5.5)."""
    payload = json.dumps(params, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()
