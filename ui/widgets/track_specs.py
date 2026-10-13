"""
Shared log-track definitions (U6).

Both log engines (Interactive and Classic) and the Petrophysics tab histograms
read these specs, so a track means the same thing everywhere: which curves it
shows, in which order, on which scale and range, and in which unit.

Pure module: no Qt, no plotting library, no colours.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

# Water-saturation columns the pipeline writes, keyed by method name.
SW_COLUMNS: Dict[str, str] = {
    "Archie": "SW_ARCHIE",
    "Indonesian": "SW_INDO",
    "Simandoux": "SW_SIMAN",
    "Waxman-Smits": "SW_WS",
    "Dual-Water": "SW_DW",
}
_SW_COLUMN_TO_METHOD = {col: name for name, col in SW_COLUMNS.items()}

PERM_LABELS = {"PERM_TIMUR": "Timur", "PERM_WR": "Wyllie-Rose"}


@dataclass(frozen=True)
class CurveSpec:
    """One curve of a track.

    ``lo``/``hi`` are the display range of the curve on its axis; ``lo > hi``
    means the axis is reversed (porosity, neutron). ``secondary`` curves use the
    track's second axis.
    """

    name: str
    unit: str
    lo: float
    hi: float
    scale: str = "linear"
    secondary: bool = False


@dataclass(frozen=True)
class TrackSpec:
    key: str
    title: str
    curves: Tuple[CurveSpec, ...]
    scale: str  # scale of the primary axis: "linear" | "log"
    lo: float
    hi: float
    unit: str
    axis_name: str  # short name used in the axis label, e.g. "GR", "RT"

    @property
    def curve_names(self) -> Tuple[str, ...]:
        return tuple(c.name for c in self.curves)

    @property
    def axis_label(self) -> str:
        return axis_label(self.axis_name, self.unit, self.scale)


TRACK_SPECS: Dict[str, TrackSpec] = {
    "gr_vsh": TrackSpec(
        key="gr_vsh",
        title="GR / Vsh",
        curves=(
            CurveSpec("GR", "API", 0.0, 150.0),
            CurveSpec("VSH", "v/v", 0.0, 1.0, secondary=True),
        ),
        scale="linear", lo=0.0, hi=150.0, unit="API", axis_name="GR",
    ),
    "resistivity": TrackSpec(
        key="resistivity",
        title="Resistivity",
        curves=(
            CurveSpec("RT", "ohm·m", 0.2, 2000.0, "log"),
            CurveSpec("RS", "ohm·m", 0.2, 2000.0, "log"),
        ),
        scale="log", lo=0.2, hi=2000.0, unit="ohm·m", axis_name="RT",
    ),
    "porosity": TrackSpec(
        key="porosity",
        title="Porosity",
        curves=(
            CurveSpec("PHIT", "v/v", 0.5, 0.0),
            CurveSpec("PHIE", "v/v", 0.5, 0.0),
            CurveSpec("PHID", "v/v", 0.5, 0.0),
            CurveSpec("PHIN", "v/v", 0.5, 0.0),
            CurveSpec("NPHI", "v/v", 0.5, 0.0),
            CurveSpec("RHOB", "g/cc", 1.95, 2.95, secondary=True),
        ),
        scale="linear", lo=0.5, hi=0.0, unit="v/v", axis_name="PHI",
    ),
    "sw": TrackSpec(
        key="sw",
        title="Sw",
        curves=(CurveSpec("SW", "v/v", 0.0, 1.0),),
        scale="linear", lo=0.0, hi=1.0, unit="v/v", axis_name="Sw",
    ),
    "permeability": TrackSpec(
        key="permeability",
        title="Permeability",
        curves=(
            CurveSpec("PERM_TIMUR", "mD", 0.01, 10000.0, "log"),
            CurveSpec("PERM_WR", "mD", 0.01, 10000.0, "log"),
        ),
        scale="log", lo=0.01, hi=10000.0, unit="mD", axis_name="K",
    ),
}


def _present(columns: Iterable[str]) -> set:
    return set(columns)


def pick_curve(track: str, columns: Iterable[str]) -> Optional[str]:
    """First curve of ``track`` (primary first) that is present in ``columns``."""
    present = _present(columns)
    for name in TRACK_SPECS[track].curve_names:
        if name in present:
            return name
    return None


def present_curves(track: str, columns: Iterable[str]) -> List[str]:
    """Every curve of ``track`` present in ``columns``, in spec order."""
    present = _present(columns)
    return [n for n in TRACK_SPECS[track].curve_names if n in present]


def porosity_plot_curves(columns: Iterable[str]) -> List[str]:
    """Porosity curves to draw for a results frame.

    The derived porosities (PHIT, PHIE, PHID, PHIN) are drawn when present; the
    raw NPHI / RHOB inputs only stand in when no derived porosity exists.
    """
    present = present_curves("porosity", columns)
    derived = [n for n in present if n not in ("NPHI", "RHOB")]
    return derived or present


def curve_spec(track: str, name: str) -> Optional[CurveSpec]:
    for c in TRACK_SPECS[track].curves:
        if c.name == name:
            return c
    return None


def sw_method_columns(columns: Iterable[str]) -> List[str]:
    """Every ``SW_*`` column present (known methods first, then any other)."""
    cols = list(columns)
    known = [c for c in SW_COLUMNS.values() if c in cols]
    other = [c for c in cols if c.startswith("SW_") and c not in known]
    return known + other


def swt_columns(columns: Iterable[str]) -> List[str]:
    return [c for c in columns if c.startswith("SWT_")]


def perm_columns(columns: Iterable[str]) -> List[str]:
    """Every ``PERM_*`` column present."""
    cols = list(columns)
    known = [c for c in ("PERM_TIMUR", "PERM_WR") if c in cols]
    other = [c for c in cols if c.startswith("PERM_") and c not in known]
    return known + other


def sw_method_name(column: str) -> str:
    """Method name for an ``SW_*`` column (``SW_SIMAN`` -> ``Simandoux``)."""
    return _SW_COLUMN_TO_METHOD.get(column, column.replace("SW_", "", 1))


def perm_method_name(column: str) -> str:
    return PERM_LABELS.get(column, column.replace("PERM_", "", 1))


def primary_sw_model(data, hint: Optional[str] = None) -> Optional[str]:
    """Name of the model the effective ``SW`` came from.

    The run does not store the primary model next to the results, so it is
    read from the data: the ``SW_*`` column that ``SW`` equals. ``hint`` (the
    configured primary method) breaks a tie between identical columns.
    """
    if data is None or "SW" not in data.columns:
        return None
    sw = np.asarray(data["SW"], dtype=float)
    matches = []
    for col in sw_method_columns(data.columns):
        other = np.asarray(data[col], dtype=float)
        if other.shape == sw.shape and np.allclose(sw, other, equal_nan=True):
            matches.append(sw_method_name(col))
    if not matches:
        return None
    if hint in matches:
        return hint
    return matches[0]


def sw_primary_label(model_name: Optional[str]) -> str:
    """Legend and title text for the effective Sw curve."""
    if model_name:
        return f"Sw — {model_name} (primary)"
    return "Sw (primary)"


def axis_label(name: str, unit: str, scale: str = "linear") -> str:
    """Axis label such as ``GR (API)`` or ``RT (ohm·m, log)``."""
    inner = f"{unit}, log" if scale == "log" else unit
    return f"{name} ({inner})"


def normalize(values, lo: float, hi: float, scale: str = "linear"):
    """Map real values to the 0-1 display range of an axis."""
    arr = np.asarray(values, dtype=float)
    if scale == "log":
        floor = min(lo, hi) / 10.0
        with np.errstate(invalid="ignore", divide="ignore"):
            arr = np.log10(np.where(arr > 0, np.maximum(arr, floor), np.nan))
        lo_t, hi_t = np.log10(lo), np.log10(hi)
        return (arr - lo_t) / (hi_t - lo_t)
    return (arr - lo) / (hi - lo)


def _fmt(value: float) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 1000 or abs(value) < 0.01:
        return f"{value:g}"
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text


def axis_ticks(lo: float, hi: float, scale: str = "linear") -> List[Tuple[float, str]]:
    """Ticks of a track axis as ``(normalised position, real-value label)``.

    Log axes tick on decades inside the range (0.1, 1, 10, 100, 1000 ...);
    linear axes on six evenly spaced values including both ends.
    """
    ticks: List[Tuple[float, str]] = []
    if scale == "log":
        low, high = min(lo, hi), max(lo, hi)
        first = int(np.ceil(np.log10(low) - 1e-9))
        last = int(np.floor(np.log10(high) + 1e-9))
        for exp in range(first, last + 1):
            value = 10.0 ** exp
            ticks.append((float(normalize(value, lo, hi, "log")), _fmt(value)))
        return ticks
    for value in np.linspace(lo, hi, 6):
        ticks.append((float(normalize(value, lo, hi)), _fmt(round(float(value), 6))))
    return ticks


def readout_text(values: Dict[str, float], units: Dict[str, str]) -> str:
    """Crosshair readout listing every curve with its unit, not truncated."""
    parts = []
    for name, value in values.items():
        if value is None or not np.isfinite(value):
            continue
        unit = units.get(name, "")
        parts.append(f"{name}: {value:.3f} {unit}".rstrip())
    return " | ".join(parts)


def rock_type_bands(depth, rock_type, margin=None, source=None, margin_min: float = 0.05):
    """Runs of the rock-type log as ``(top, base, rock_type, faded)`` tuples.

    Band edges sit halfway between samples; the first and last sample extend by half a
    step. ``rock_type`` 0 (or NaN) is unassigned. ``faded`` marks bands that are weak:
    ``margin`` below ``margin_min``, or ``source`` "log" (assigned from the log, not core).
    Runs break where the rock type or the faded flag changes.
    """
    depth = np.asarray(depth, dtype=float)
    n = len(depth)
    if n == 0:
        return []
    rt = np.nan_to_num(np.asarray(rock_type, dtype=float), nan=0.0).astype(int)
    faded = np.zeros(n, dtype=bool)
    if margin is not None:
        m = np.asarray(margin, dtype=float)
        faded |= np.isfinite(m) & (m < margin_min)
    if source is not None:
        faded |= np.asarray([str(v) == "log" for v in source])
    faded &= rt > 0
    if n == 1:
        edges = np.array([depth[0], depth[0]])
    else:
        mid = (depth[1:] + depth[:-1]) / 2.0
        edges = np.concatenate(([depth[0] - (mid[0] - depth[0])], mid,
                                [depth[-1] + (depth[-1] - mid[-1])]))
    bands = []
    start = 0
    for i in range(1, n + 1):
        if i == n or rt[i] != rt[start] or faded[i] != faded[start]:
            bands.append((float(edges[start]), float(edges[i]), int(rt[start]),
                          bool(faded[start])))
            start = i
    return bands


def rock_type_readout(values: Dict[str, float], source: Optional[str] = None) -> str:
    """Crosshair text for the Rock Type track: RT, FZI and where the type came from."""
    parts = []
    rt = values.get("ROCK_TYPE")
    if rt is not None and np.isfinite(rt):
        parts.append(f"RT: {int(rt)}" if rt >= 1 else "RT: none")
    fzi = values.get("FZI")
    if fzi is not None and np.isfinite(fzi):
        parts.append(f"FZI: {fzi:.3f}")
    if source:
        parts.append(f"source: {source}")
    return " | ".join(parts)
