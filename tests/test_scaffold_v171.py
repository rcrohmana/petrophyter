"""Shared helpers introduced for v1.7.1 (P0 I1/I2/I10, P0-Hardening H1, P0-UI/UX U3)."""
import numpy as np
import pandas as pd

from models.project import WellDataset
from modules.las_handler import MERGE_POLICY
from modules.las_utils import mask_nonpositive
from version import version_tuple


def test_version_tuple_compares_numerically():
    assert version_tuple("1.10.0") > version_tuple("1.9.0")
    assert version_tuple("1.7.0") == version_tuple("1.7")
    assert version_tuple("1.7.2") > version_tuple("1.7.1")
    assert version_tuple("2rc1") == (2,)
    assert version_tuple(None) == (0,)


def test_mask_nonpositive_counts_and_masks_only_numeric_columns():
    df = pd.DataFrame({"RT": [1.0, 0.0, -5.0, np.nan], "NAME": ["a", "b", "c", "d"]})
    counts = mask_nonpositive(df, ["RT", "NAME", "ABSENT"])
    assert counts == {"RT": 2}
    assert df["RT"].isna().tolist() == [False, True, True, True]
    assert df["NAME"].tolist() == ["a", "b", "c", "d"]


def test_well_dataset_has_recipe_and_run_time():
    ds = WellDataset("k")
    assert ds.merge_recipe is None
    assert ds.run_time is None
    ds.run_time = "2026-10-11T00:00:00Z"
    ds.clear_derived()
    assert ds.run_time is None
    assert "run_time" in WellDataset.DERIVED_FIELDS
    assert isinstance(MERGE_POLICY, int) and MERGE_POLICY >= 1
