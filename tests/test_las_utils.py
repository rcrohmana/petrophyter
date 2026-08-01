"""
Tests for the shared LAS utility module (modules/las_utils.py).

las_utils holds the constants and null-replacement helper that las_parser and
las_handler used to duplicate. These tests pin the shared behaviour directly
and verify that both consumers re-export the same COMMON_NULL_VALUES so the
single-load and merge paths can never drift apart again.
"""

import numpy as np
import pandas as pd
import pytest

from modules import las_utils
from modules.las_utils import (
    COMMON_NULL_VALUES,
    DEPTH_COLUMN_CANDIDATES,
    NULL_REPLACE_DTYPES,
    find_depth_column,
    replace_null_values,
)
from modules.las_parser import COMMON_NULL_VALUES as PARSER_NULLS
from modules.las_handler import COMMON_NULL_VALUES as HANDLER_NULLS


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
def test_common_null_values_has_no_positive_999():
    assert 999.25 not in COMMON_NULL_VALUES
    assert -999.25 in COMMON_NULL_VALUES


def test_both_modules_reexport_the_shared_list():
    # Same object, so they can never drift.
    assert PARSER_NULLS is COMMON_NULL_VALUES
    assert HANDLER_NULLS is COMMON_NULL_VALUES


def test_int64_is_included_in_replace_dtypes():
    # Deliberate decision: integer-coded discrete curves get sentinels cleaned.
    assert 'int64' in NULL_REPLACE_DTYPES


# --------------------------------------------------------------------------- #
# find_depth_column
# --------------------------------------------------------------------------- #
def test_find_depth_column_priority_order():
    # DEPT wins over DEPTH when both present (candidate order).
    assert find_depth_column(['DEPT', 'DEPTH', 'GR']) == 'DEPT'
    assert find_depth_column(['GR', 'DEPTH']) == 'DEPTH'
    assert find_depth_column(['MD', 'GR']) == 'MD'


def test_find_depth_column_returns_none_when_absent():
    assert find_depth_column(['GR', 'RHOB', 'NPHI']) is None


def test_depth_candidates_expected_set():
    assert DEPTH_COLUMN_CANDIDATES == ['DEPT', 'DEPTH', 'MD', 'TVD', 'TDEP']


# --------------------------------------------------------------------------- #
# replace_null_values
# --------------------------------------------------------------------------- #
def test_replace_floats_and_preserves_valid_lookalike():
    df = pd.DataFrame({
        'DEPTH': [100.0, 101.0, 102.0],
        'GR': [999.25, -999.25, 70.0],  # valid 999.25 kept, -999.25 nulled
    })
    out = replace_null_values(df)
    assert out['GR'].isna().sum() == 1
    assert np.isclose(out['GR'].dropna().to_numpy(), 999.25, atol=1e-3).any()
    assert 70.0 in out['GR'].dropna().to_numpy()


def test_replace_int64_sentinels():
    df = pd.DataFrame({
        'DEPTH': [100.0, 101.0, 102.0],
        'FACIES': pd.Series([1, -999, 3], dtype='int64'),
    })
    out = replace_null_values(df)
    assert out['FACIES'].isna().sum() == 1


def test_replace_nullable_integer_sentinels():
    # Pandas nullable integer columns are numeric too; a sentinel must not
    # survive merely because its dtype is ``Int64`` rather than ``int64``.
    df = pd.DataFrame({
        'DEPTH': [100.0, 101.0],
        'FACIES': pd.Series([1, -999], dtype='Int64'),
    })
    out = replace_null_values(df)
    assert out['FACIES'].isna().sum() == 1


def test_depth_column_is_never_modified():
    # A depth value equal to a sentinel must survive (depth is excluded).
    df = pd.DataFrame({'DEPTH': [-999.25, 100.0], 'GR': [50.0, 60.0]})
    out = replace_null_values(df)
    assert out['DEPTH'].isna().sum() == 0
    assert out['DEPTH'].iloc[0] == pytest.approx(-999.25)


def test_non_numeric_columns_untouched():
    df = pd.DataFrame({
        'DEPTH': [100.0, 101.0],
        'LITH': ['SAND', 'SHALE'],  # object dtype, must be left alone
        'GR': [-999.25, 60.0],
    })
    out = replace_null_values(df)
    assert list(out['LITH']) == ['SAND', 'SHALE']
    assert out['GR'].isna().sum() == 1


def test_custom_null_values_list():
    df = pd.DataFrame({'DEPTH': [1.0, 2.0, 3.0], 'X': [1.0, 2.0, 3.0]})
    out = replace_null_values(df, null_values=[2.0])
    assert out['X'].isna().sum() == 1
    assert out['X'].iloc[1] != out['X'].iloc[1]  # NaN at the matched value


def test_modifies_in_place_and_returns_same_object():
    df = pd.DataFrame({'DEPTH': [1.0], 'GR': [-999.25]})
    out = replace_null_values(df)
    assert out is df
    assert df['GR'].isna().all()
