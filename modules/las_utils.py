"""
Shared LAS utilities for Petrophyter.

Single source of truth for the depth-column candidates and null-sentinel
replacement used by both ``las_parser.LASParser`` and
``las_handler.LASHandler``. These pieces were previously duplicated in each
module and had drifted apart, so the same file could be null-handled
differently depending on whether it was loaded on its own or through the merge
path. Keeping the constants and the helper here means there is exactly one
definition to keep correct.

dtype decision (historical int64 inconsistency)
-----------------------------------------------
Null replacement historically ran only on ``float64``/``float32`` columns in
``las_parser`` but also on ``int64`` columns in ``las_handler``. That meant a
discrete curve that ``lasio`` loaded as integers (LITH/FACIES/ZONE codes) kept
its sentinel nulls on the single-load path but had them cleaned on the merge
path. This module resolves the inconsistency deliberately in favour of the
more complete behaviour: ``int64`` IS included, so integer-coded curves get
their sentinels cleaned on every path. Setting NaN upcasts such a column to
float, which is the intended outcome for a curve that actually contained nulls.
"""

import re

import numpy as np
import pandas as pd
from typing import List, Optional, Sequence

# Common null sentinel values that may not be declared in the LAS header.
# Only negative sentinels belong here. A positive ``999.25`` used to live in
# this list (a typo for ``-999.25``) and silently destroyed valid high curve
# readings (e.g. extreme RT/GR); do not reintroduce it.
COMMON_NULL_VALUES: List[float] = [-999.25, -999, -9999, -999.0, -9999.0, -999999]

# Candidate depth-column mnemonics, in priority order. The first one present in
# a DataFrame is treated as the depth column and renamed to STANDARD_DEPTH_COL.
DEPTH_COLUMN_CANDIDATES: List[str] = ['DEPT', 'DEPTH', 'MD', 'TVD', 'TDEP']

# Canonical depth column name used throughout the app after normalization.
STANDARD_DEPTH_COL = 'DEPTH'

# dtypes eligible for null-sentinel replacement (see module docstring for why
# int64 is included).
NULL_REPLACE_DTYPES = ('float64', 'float32', 'int64')

# Tolerance for matching a value against a null sentinel (float-safe equality).
NULL_MATCH_TOLERANCE = 0.01


def find_depth_column(columns: Sequence[str]) -> Optional[str]:
    """
    Return the first depth-candidate mnemonic present in ``columns``.

    Candidates are checked in DEPTH_COLUMN_CANDIDATES priority order. Returns
    None when none of them are present.
    """
    cols = list(columns)
    for candidate in DEPTH_COLUMN_CANDIDATES:
        if candidate in cols:
            return candidate
    return None


def replace_null_values(df: pd.DataFrame,
                        null_values: Optional[Sequence[float]] = None,
                        depth_col: str = STANDARD_DEPTH_COL,
                        tolerance: float = NULL_MATCH_TOLERANCE) -> pd.DataFrame:
    """
    Replace null sentinels with NaN, in place, on numeric curve columns.

    For every numeric column except ``depth_col``, any value within
    ``tolerance`` of any sentinel in ``null_values`` is set to NaN. This uses
    pandas' numeric-dtype predicate so nullable integer/float dtypes (for
    example ``Int64``) receive the same handling as NumPy dtypes. When
    ``null_values`` is None the module-level COMMON_NULL_VALUES list is used.

    The DataFrame is modified in place and also returned for convenience.
    """
    if null_values is None:
        null_values = COMMON_NULL_VALUES

    nulls = np.asarray(list(null_values), dtype=float)
    if nulls.size == 0:
        return df
    for col in df.columns:
        if col == depth_col:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            vals = df[col].to_numpy(dtype=float, na_value=np.nan)
            with np.errstate(invalid='ignore'):
                mask = (np.abs(vals[:, None] - nulls[None, :]) < tolerance).any(axis=1)
            if mask.any():
                df.loc[mask, col] = np.nan
    return df


# ---------------------------------------------------------------------------
# Well identity
# ---------------------------------------------------------------------------
# Header values that mean "no name" rather than a real identifier.
_PLACEHOLDER_NAMES = {"", "UNKNOWN", "NONE", "NULL", "N/A", "NA", "-", "?"}

# Identity fields in priority order: a shared UWI beats a shared API number,
# which beats a shared well name.
WELL_IDENTITY_FIELDS = ("uwi", "api", "well_name")


def normalize_well_name(value) -> str:
    """Return a comparable form of a header identifier, or '' when it is blank.

    Strips and upper-cases, and treats any run of spaces, ``_`` and ``-`` as
    one separator, so "bks_01 ", "BKS-01" and "BKS 01" compare equal.
    Placeholder values such as "Unknown" become ''.
    """
    if value is None:
        return ""
    text = str(value).strip().upper()
    if text in _PLACEHOLDER_NAMES:
        return ""
    return re.sub(r"[\s_\-]+", "-", text).strip("-")


def well_key(well_info: dict) -> tuple:
    """Return ``(key, identified)`` for a parser's ``well_info`` dict.

    ``key`` is ``"<FIELD>:<value>"`` for the highest-priority identity field
    that is present (UWI, then API, then WELL). ``identified`` is False when
    none is present, in which case ``key`` is ``""``.
    """
    info = well_info or {}
    labels = {"uwi": "UWI", "api": "API", "well_name": "WELL"}
    for field in WELL_IDENTITY_FIELDS:
        value = normalize_well_name(info.get(field))
        if value:
            return f"{labels[field]}:{value}", True
    return "", False


def same_well(info_a: dict, info_b: dict) -> Optional[bool]:
    """Decide whether two ``well_info`` dicts describe the same well.

    Compares the highest-priority identity field that BOTH carry. Returns True
    or False when such a field exists, and None when it cannot be decided
    (at least one side has no usable identifier, or they share no field).
    """
    a, b = info_a or {}, info_b or {}
    for field in WELL_IDENTITY_FIELDS:
        va, vb = normalize_well_name(a.get(field)), normalize_well_name(b.get(field))
        if va and vb:
            return va == vb
    return None


# ---------------------------------------------------------------------------
# Curve unit normalisation
# ---------------------------------------------------------------------------
# Working units: neutron V/V, bulk density G/C3, sonic US/F.
_PERCENT_UNITS = {"%", "PU", "P.U.", "PERCENT", "PU(%)", "%PU", "PCT"}
_FRACTION_UNITS = {"V/V", "VOL/VOL", "M3/M3", "CC/CC", "FRAC", "DEC", "DECIMAL", "FRACTION", "UNITLESS"}
_KG_M3_UNITS = {"KG/M3", "KGM3", "KG/CUM", "KG/M^3", "KG/CBM"}
_US_PER_M_UNITS = {"US/M", "USEC/M", "USEC/METER", "MICROSEC/M", "USM"}
_CONDUCTIVITY_UNITS = {"MMHO/M", "MS/M", "MMHO", "S/M", "MHO/M"}

_M_TO_FT = 0.3048
_TVD_MNEMONICS = {"TVD", "TVDKB", "TVDRKB", "TVDRT", "TVDBRT"}
_METRE_UNITS = {"M", "METER", "METERS", "METRE", "METRES"}
_FT_PER_M = 3.28084
_NEUTRON_PERCENT_MEDIAN = 1.0
_DENSITY_KGM3_MEDIAN = 100.0
_SONIC_US_M_MEDIAN = 300.0


def _unit_token(unit) -> str:
    """Upper-case a unit with spaces removed and micro/superscript variants folded."""
    text = "" if unit is None else str(unit)
    for src, dst in (("µ", "U"), ("μ", "U"), ("³", "3")):
        text = text.replace(src, dst)
    return "".join(text.split()).upper()


# Spellings of one physical unit, folded to a single token for comparison.
_UNIT_SYNONYMS = {
    "V/V": _FRACTION_UNITS,
    "%": _PERCENT_UNITS,
    "G/C3": {"G/C3", "G/CC", "G/CM3", "GM/CC", "GR/CC", "G/CM^3", "GRAM/CC"},
    "KG/M3": _KG_M3_UNITS,
    "US/F": {"US/F", "US/FT", "USEC/F", "USEC/FT", "MICROSEC/FT", "USFT"},
    "US/M": _US_PER_M_UNITS,
    "OHMM": {"OHMM", "OHM.M", "OHM-M", "OHM*M", "OHM/M", "OHMS", "OHM"},
    "GAPI": {"GAPI", "API", "GAPI.", "API-GR"},
}


def canonical_unit(unit) -> str:
    """Fold spelling variants of a unit (G/CC vs G/C3, US/FT vs US/F) to one token.

    Unknown units are returned upper-cased with spaces removed, so two files
    are only treated as disagreeing when their units really differ.
    """
    token = _unit_token(unit)
    for canonical, spellings in _UNIT_SYNONYMS.items():
        if token in spellings:
            return canonical
    return token


def _curve_type_for(mnemonic: str) -> Optional[str]:
    """Map a mnemonic to NPHI/RHOB/DT/RT/RM/RS via the parser's alias table."""
    from .las_parser import LASParser  # deferred: las_parser imports this module

    upper = str(mnemonic).upper()
    for curve_type in ("NPHI", "RHOB", "DT", "RT", "RM", "RS"):
        if upper in (alias.upper() for alias in LASParser.CURVE_ALIASES[curve_type]):
            return curve_type
    return None


def normalize_curve_units(df: pd.DataFrame, curve_info: dict) -> tuple:
    """Convert neutron, density and sonic curves to the app's working units.

    Returns ``(df, curve_info, warnings)``. Neutron percent becomes V/V,
    kg/m3 density becomes G/C3 and us/m slowness becomes US/F. When the unit
    is empty or unrecognised the median of the valid values decides, and the
    warning says the unit was inferred. Resistivity that looks like
    conductivity is only flagged, never converted. A converted curve is marked
    with ``unit_converted_from`` in ``curve_info`` so it is never converted
    twice. ``df`` is modified in place; ``curve_info`` is copied.
    """
    info = {name: dict(entry) for name, entry in (curve_info or {}).items()}
    warnings: List[str] = []

    for col in list(df.columns):
        if col == STANDARD_DEPTH_COL or not pd.api.types.is_numeric_dtype(df[col]):
            continue
        if str(col).upper() in _TVD_MNEMONICS:
            # A TVD curve in metres joins the feet depth axis (declared unit only).
            entry = info.setdefault(col, {"unit": "", "description": ""})
            if entry.get("unit_converted_from") is None and _unit_token(entry.get("unit")) in _METRE_UNITS:
                df[col] = df[col] * _FT_PER_M
                entry["unit_converted_from"] = entry.get("unit")
                entry["unit"] = "FT"
                warnings.append(f"{col} converted to FT (from {entry['unit_converted_from']}).")
            continue
        curve_type = _curve_type_for(col)
        if curve_type is None:
            continue
        entry = info.setdefault(col, {"unit": "", "description": ""})
        if entry.get("unit_converted_from") is not None:
            continue
        raw_unit = entry.get("unit", "") or ""
        unit = _unit_token(raw_unit)
        values = df[col].dropna()
        median = float(values.median()) if len(values) else None

        factor, new_unit, inferred = None, None, False
        if curve_type == "NPHI":
            if unit in _PERCENT_UNITS:
                factor, new_unit = 0.01, "V/V"
            elif unit not in _FRACTION_UNITS and median is not None and median > _NEUTRON_PERCENT_MEDIAN:
                factor, new_unit, inferred = 0.01, "V/V", True
        elif curve_type == "RHOB":
            if unit in _KG_M3_UNITS:
                factor, new_unit = 0.001, "G/C3"
            elif not unit and median is not None and median > _DENSITY_KGM3_MEDIAN:
                factor, new_unit, inferred = 0.001, "G/C3", True
        elif curve_type == "DT":
            if unit in _US_PER_M_UNITS:
                factor, new_unit = _M_TO_FT, "US/F"
            elif not unit and median is not None and median > _SONIC_US_M_MEDIAN:
                factor, new_unit, inferred = _M_TO_FT, "US/F", True
        elif unit in _CONDUCTIVITY_UNITS:
            warnings.append(
                f"{col} has conductivity units ({raw_unit}); it was not converted "
                "to resistivity. Convert it before using it as a resistivity curve."
            )

        if factor is None:
            continue
        df[col] = df[col] * factor
        entry["unit_converted_from"] = raw_unit
        entry["unit"] = new_unit
        reason = (
            f"unit inferred from the value range, median {median:.4g}" if inferred
            else f"from {raw_unit}"
        )
        warnings.append(f"{col} converted to {new_unit} ({reason}).")

    return df, info, warnings
