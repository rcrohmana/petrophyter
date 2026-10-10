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
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

AUTO, MANUAL, INHERIT = "auto", "manual", "inherit"

# Shale-point parameters, estimated together from one shale selection. Flat
# parameters list those in AUTO mode under ``flat["shale_auto"]`` (absent when
# none is, so project-only parameters are unchanged).
SHALE_PARAMS = ("rho_shale", "dt_shale", "nphi_shale")
SHALE_AUTO_KEY = "shale_auto"
UNZONED = "(unzoned)"

PROJECT, PROJECT_ZONE, WELL, WELL_ZONE = "project", "project·zone", "well", "well·zone"

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
)}

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
    temperature-gradient AUTO estimate.
    """
    flat = dict(global_params)
    info: Dict[str, Dict] = {}
    for name in SPECS:
        entry, scope = winning_entry(name, global_params, overrides, zone_params,
                                     zone_overrides, zone)
        apply_entry(flat, name, entry)
        info[name] = {"scope": scope, "mode": entry.get("mode"),
                      "source": source_label(entry, scope)}
    if info["temp_gradient"]["mode"] == AUTO:
        gradient = gradient_from_header(header, flat.get("surface_temp"))
        if gradient is None:
            info["temp_gradient"]["source"] = "auto unavailable (project)"
        else:
            flat["temp_gradient"] = gradient
            info["temp_gradient"]["source"] = "auto (LAS header)"
    return flat, info


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


def gradient_from_header(header: Optional[Dict], surface_temp_f) -> Optional[float]:
    """Geothermal gradient (°F/100 ft) from BHT at TD, or None.

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
    td_ft = _to_ft(float(td), header.get("td_unit"))
    if td_ft <= 0 or bht_f <= float(surface_temp_f):
        return None
    return round((bht_f - float(surface_temp_f)) / td_ft * 100.0, 4)


ARPS_OFFSET_F = 6.77


def formation_temperature(depth_ft, surface_temp_f: float, gradient_f_per_100ft: float):
    """T(depth) in °F for a linear gradient (works on scalars and arrays)."""
    return surface_temp_f + gradient_f_per_100ft * depth_ft / 100.0


def arps_factor(temp_f, ref_temp_f: float):
    """Multiplier taking a resistivity at ``ref_temp_f`` to ``temp_f`` (Arps, °F)."""
    return (ref_temp_f + ARPS_OFFSET_F) / (temp_f + ARPS_OFFSET_F)


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
