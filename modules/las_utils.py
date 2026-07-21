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

    For every column except ``depth_col`` whose dtype is in
    NULL_REPLACE_DTYPES, any value within ``tolerance`` of any sentinel in
    ``null_values`` is set to NaN. When ``null_values`` is None the module-level
    COMMON_NULL_VALUES list is used.

    The DataFrame is modified in place and also returned for convenience.
    """
    if null_values is None:
        null_values = COMMON_NULL_VALUES

    for col in df.columns:
        if col == depth_col:
            continue
        if df[col].dtype in NULL_REPLACE_DTYPES:
            for null in null_values:
                mask = np.abs(df[col] - null) < tolerance
                df.loc[mask, col] = np.nan
    return df
