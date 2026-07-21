"""
Unit tests for Shale Parameter Calculation (v2.0)
Tests Per-Formation filter and threshold effect on shale parameter estimation.

Per-Formation filtering and linear Vshale are exercised through the production
classes (FormationTops, PetrophysicsCalculator) instead of reimplementations,
so a regression in those modules would now fail these tests. The robust-median
helper below still mirrors AnalysisWorker._robust_median, which lives in the
Qt-coupled services layer and cannot be imported in this headless test
environment - see the test-suite audit in the task report.
"""

import pytest
import pandas as pd
import numpy as np

from modules.formation_tops import FormationTops, Formation
from modules.petrophysics import PetrophysicsCalculator


def create_test_data_two_zones():
    """Create test data with two distinct zones (clean sand + shale)."""
    np.random.seed(42)
    
    # Zone 1: 1000-1050 ft - Clean Sand (low GR, low RHOB, low NPHI)
    n1 = 50
    zone1 = pd.DataFrame({
        'DEPTH': np.linspace(1000, 1050, n1),
        'GR': np.random.normal(30, 5, n1),      # Clean sand GR
        'RHOB': np.random.normal(2.30, 0.05, n1),  # Clean sand RHOB
        'NPHI': np.random.normal(0.20, 0.02, n1),  # Clean sand NPHI
        'DT': np.random.normal(80, 5, n1),       # Clean sand DT
    })
    
    # Zone 2: 1050-1100 ft - Shale (high GR, high RHOB, high NPHI)
    n2 = 50
    zone2 = pd.DataFrame({
        'DEPTH': np.linspace(1050, 1100, n2),
        'GR': np.random.normal(110, 10, n2),      # Shale GR
        'RHOB': np.random.normal(2.50, 0.05, n2), # Shale RHOB
        'NPHI': np.random.normal(0.38, 0.03, n2), # Shale NPHI
        'DT': np.random.normal(95, 5, n2),        # Shale DT
    })
    
    return pd.concat([zone1, zone2], ignore_index=True)


def robust_median(series, use_iqr_filter=True):
    """Calculate median with optional IQR outlier filtering."""
    s = series.dropna()
    if len(s) == 0:
        return np.nan
    if use_iqr_filter and len(s) >= 5:
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        s = s[(s >= lower) & (s <= upper)]
    return float(s.median()) if len(s) > 0 else np.nan


class TestShaleThresholdEffect:
    """Test that changing VSH threshold affects shale point count."""
    
    def test_lower_threshold_more_shale_points(self):
        """Lower threshold should identify more shale points."""
        data = create_test_data_two_zones()
        
        # Calculate VSH
        gr_min, gr_max = 25.0, 120.0
        vsh = PetrophysicsCalculator(data).calculate_vshale_linear(
            'GR', gr_min=gr_min, gr_max=gr_max
        )
        
        # Count shale points at different thresholds
        n_shale_06 = (vsh > 0.6).sum()
        n_shale_08 = (vsh > 0.8).sum()
        n_shale_09 = (vsh > 0.9).sum()
        
        # Lower threshold should give more points
        assert n_shale_06 >= n_shale_08, "Lower threshold should identify more shale points"
        assert n_shale_08 >= n_shale_09, "Mid threshold should identify more than high threshold"
        
        # With our test data, threshold 0.8 should capture zone 2
        assert n_shale_08 > 0, "Should find some shale points at 0.8 threshold"
    
    def test_threshold_affects_median_shale_params(self):
        """Different thresholds may produce different median values."""
        data = create_test_data_two_zones()
        
        # Calculate VSH
        gr_min, gr_max = 25.0, 120.0
        vsh = PetrophysicsCalculator(data).calculate_vshale_linear(
            'GR', gr_min=gr_min, gr_max=gr_max
        )
        
        # Get shale RHOB at different thresholds
        mask_06 = vsh > 0.6
        mask_09 = vsh > 0.9
        
        rhob_06 = data.loc[mask_06, 'RHOB'].median() if mask_06.sum() > 0 else np.nan
        rhob_09 = data.loc[mask_09, 'RHOB'].median() if mask_09.sum() > 0 else np.nan
        
        # Both should be in reasonable shale range if data found
        if not np.isnan(rhob_06):
            assert 2.2 <= rhob_06 <= 2.7, f"RHOB at 0.6 threshold should be in shale range: {rhob_06}"
        if not np.isnan(rhob_09):
            assert 2.2 <= rhob_09 <= 2.7, f"RHOB at 0.9 threshold should be in shale range: {rhob_09}"


class TestPerFormationFilter:
    """Test that Per-Formation mode correctly filters data."""
    
    def test_formation_filter_restricts_data(self):
        """Per-Formation mode should only use data from selected formations."""
        data = create_test_data_two_zones()
        
        # Create formation tops (Zone1 = "Sand", Zone2 = "Shale")
        tops = FormationTops()
        tops.formations = [
            Formation('Sand', 1000.0, 1050.0, 50.0),
            Formation('Shale', 1050.0, 1100.0, 50.0),
        ]
        
        # Filter for Sand only
        filtered = tops.filter_by_formations(data, ['Sand'], 'DEPTH')
        
        # Should only have Zone 1 data
        assert len(filtered) < len(data), "Filtered data should be smaller"
        assert filtered['DEPTH'].min() >= 1000, "Should start at Sand zone"
        assert filtered['DEPTH'].max() <= 1050, "Should end at Sand zone"
        
        # GR should be low (clean sand)
        assert filtered['GR'].mean() < 50, "Sand zone should have low GR"
    
    def test_formation_filter_changes_shale_params(self):
        """Different formation selections should yield different shale params."""
        data = create_test_data_two_zones()
        
        tops = FormationTops()
        tops.formations = [
            Formation('Sand', 1000.0, 1050.0, 50.0),
            Formation('Shale', 1050.0, 1100.0, 50.0),
        ]
        
        # Get median NPHI from "Shale" zone only
        shale_data = tops.filter_by_formations(data, ['Shale'], 'DEPTH')
        nphi_shale_zone = shale_data['NPHI'].median()
        
        # Get median NPHI from "Sand" zone only
        sand_data = tops.filter_by_formations(data, ['Sand'], 'DEPTH')
        nphi_sand_zone = sand_data['NPHI'].median()
        
        # Shale zone should have higher NPHI
        assert nphi_shale_zone > nphi_sand_zone, "Shale zone should have higher NPHI"


class TestRobustFiltering:
    """Test IQR outlier filtering."""
    
    def test_iqr_filter_removes_outliers(self):
        """IQR filter should remove extreme values."""
        # Create data with outliers
        np.random.seed(42)
        values = np.random.normal(2.50, 0.05, 100)
        # Add outliers
        values[0] = 1.8  # Low outlier
        values[1] = 3.2  # High outlier
        
        s = pd.Series(values)
        
        # Calculate median with and without IQR filter
        median_raw = s.median()
        median_filtered = robust_median(s, use_iqr_filter=True)
        
        # Both should be close to 2.50
        assert abs(median_filtered - 2.50) < 0.1, f"Filtered median should be close to 2.50: {median_filtered}"
    
    def test_iqr_filter_preserves_data_when_no_outliers(self):
        """IQR filter shouldn't drastically change median for normal data."""
        np.random.seed(42)
        values = np.random.normal(2.50, 0.05, 100)  # No outliers
        
        s = pd.Series(values)
        
        median_raw = s.median()
        median_filtered = robust_median(s, use_iqr_filter=True)
        
        # Should be very similar
        assert abs(median_raw - median_filtered) < 0.01, "Median shouldn't change much without outliers"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
