"""
Unit tests for Adaptive Shale Selection Modes (v2.1)
Tests fixed_threshold, quantile, and stability_sweep modes.
"""

import pytest
import pandas as pd
import numpy as np


def create_bimodal_test_data():
    """Create synthetic bimodal data (clean sand + shale zones)."""
    np.random.seed(42)
    n = 200
    
    # Create depth
    depth = np.linspace(1000, 1100, n)
    
    # Bimodal GR distribution
    is_shale = depth > 1050  # Upper half is shale
    gr = np.where(is_shale,
                  np.random.normal(120, 15, n),  # Shale GR
                  np.random.normal(30, 8, n))    # Sand GR
    
    # Logs correlated with lithology
    rhob = np.where(is_shale,
                    np.random.normal(2.55, 0.06, n),
                    np.random.normal(2.25, 0.05, n))
    nphi = np.where(is_shale,
                    np.random.normal(0.38, 0.04, n),
                    np.random.normal(0.18, 0.03, n))
    dt = np.where(is_shale,
                  np.random.normal(95, 8, n),
                  np.random.normal(75, 6, n))
    
    # Add some NaNs
    gr[5] = np.nan
    rhob[10] = np.nan
    nphi[15] = np.nan
    
    return pd.DataFrame({
        'DEPTH': depth,
        'GR': gr,
        'RHOB': rhob,
        'NPHI': nphi,
        'DT': dt
    })


def calculate_vsh_linear(gr, gr_min, gr_max):
    """Simple linear VSH."""
    vsh = (gr - gr_min) / (gr_max - gr_min)
    return np.clip(vsh, 0, 1)


# ============================================================================
# Test Helpers (mimic analysis_service logic)
# ============================================================================

def build_shale_mask(vsh_ref, threshold):
    """Build shale mask from VSH and threshold."""
    mask = (vsh_ref >= threshold) & pd.notna(vsh_ref)
    return mask, int(mask.sum())


def apply_gates(data, mask, rhob_col='RHOB', nphi_col='NPHI', dt_col='DT'):
    """Apply log gating."""
    filtered = mask.copy()
    if rhob_col in data.columns:
        filtered &= data[rhob_col].between(2.2, 2.7)
    if nphi_col in data.columns:
        filtered &= data[nphi_col].between(0.15, 0.5)
    if dt_col in data.columns:
        filtered &= data[dt_col].between(70, 150)
    return filtered, int(filtered.sum())


def robust_median(series, use_iqr=True):
    """Calculate median with optional IQR filter."""
    s = series.dropna()
    if len(s) == 0:
        return np.nan
    if use_iqr and len(s) >= 5:
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        s = s[(s >= q1 - 1.5 * iqr) & (s <= q3 + 1.5 * iqr)]
    return float(s.median()) if len(s) > 0 else np.nan


def stability_sweep(data, vsh_ref, tmin, tmax, step, min_points):
    """Sweep thresholds and find most stable."""
    thresholds = np.arange(tmin, tmax + step/2, step)
    sweep_results = []
    
    for t in thresholds:
        mask, _ = build_shale_mask(vsh_ref, t)
        filtered, n_points = apply_gates(data, mask)
        
        if n_points >= min_points:
            rho = robust_median(data.loc[filtered, 'RHOB'])
            nphi = robust_median(data.loc[filtered, 'NPHI'])
            dt = robust_median(data.loc[filtered, 'DT'])
            sweep_results.append({
                'threshold': float(t),
                'n_points': n_points,
                'rho': rho,
                'nphi': nphi,
                'dt': dt
            })
    
    if not sweep_results:
        return 0.80, []
    
    # Calculate stability scores
    for i, r in enumerate(sweep_results):
        score = 0.0
        count = 0
        for key in ['rho', 'nphi', 'dt']:
            vals = [sr[key] for sr in sweep_results if not np.isnan(sr[key])]
            if len(vals) < 2:
                continue
            vrange = max(vals) - min(vals)
            if vrange < 1e-6:
                continue
            
            if 0 < i < len(sweep_results) - 1:
                diff = abs(r[key] - sweep_results[i-1][key]) + abs(sweep_results[i+1][key] - r[key])
            elif i == 0 and len(sweep_results) > 1:
                diff = abs(sweep_results[1][key] - r[key])
            elif i == len(sweep_results) - 1 and len(sweep_results) > 1:
                diff = abs(r[key] - sweep_results[-2][key])
            else:
                diff = 0
            
            score += diff / vrange
            count += 1
        
        r['score'] = score / max(count, 1)
    
    best = min(sweep_results, key=lambda x: x['score'])
    return best['threshold'], sweep_results


# ============================================================================
# TEST CASES
# ============================================================================

class TestFixedThreshold:
    """Test fixed threshold mode (backward compatible)."""
    
    def test_fixed_threshold_produces_valid_mask(self):
        """Fixed threshold should produce a valid shale mask."""
        data = create_bimodal_test_data()
        gr_min, gr_max = 20.0, 140.0
        vsh = calculate_vsh_linear(data['GR'], gr_min, gr_max)
        
        threshold = 0.80
        mask, n_points = build_shale_mask(pd.Series(vsh), threshold)
        
        assert isinstance(mask, pd.Series)
        assert n_points > 0, "Should find shale points at 0.80 threshold"
        assert n_points < len(data), "Should not select all points as shale"
    
    def test_fixed_threshold_gating_reduces_points(self):
        """Gating should reduce the number of shale points."""
        data = create_bimodal_test_data()
        vsh = calculate_vsh_linear(data['GR'], 20.0, 140.0)
        
        mask, before = build_shale_mask(pd.Series(vsh), 0.75)
        _, after = apply_gates(data, mask)
        
        assert after <= before, "Gating should not increase points"


class TestQuantileMode:
    """Test quantile-based threshold selection."""
    
    def test_quantile_computes_threshold(self):
        """Quantile mode should compute threshold from VSH distribution."""
        data = create_bimodal_test_data()
        vsh = pd.Series(calculate_vsh_linear(data['GR'], 20.0, 140.0))
        
        quantile = 0.90
        threshold = np.nanquantile(vsh, quantile)
        
        assert 0 < threshold < 1, "Threshold should be valid"
        assert (vsh >= threshold).sum() > 0, "Should find some shale points"
    
    def test_quantile_adapts_to_data(self):
        """Different quantiles should produce different thresholds."""
        data = create_bimodal_test_data()
        vsh = pd.Series(calculate_vsh_linear(data['GR'], 20.0, 140.0))
        
        t_80 = np.nanquantile(vsh, 0.80)
        t_95 = np.nanquantile(vsh, 0.95)
        
        assert t_95 > t_80, "Higher quantile should give higher threshold"


class TestStabilitySweep:
    """Test stability sweep mode."""
    
    def test_sweep_finds_valid_threshold(self):
        """Sweep should find a valid threshold."""
        data = create_bimodal_test_data()
        vsh = pd.Series(calculate_vsh_linear(data['GR'], 20.0, 140.0))
        
        threshold, results = stability_sweep(data, vsh, 0.65, 0.95, 0.02, min_points=10)
        
        assert 0.65 <= threshold <= 0.95, f"Threshold should be in range: {threshold}"
        assert len(results) > 0, "Should have some valid candidates"
    
    def test_sweep_assigns_scores(self):
        """Each candidate should have a stability score."""
        data = create_bimodal_test_data()
        vsh = pd.Series(calculate_vsh_linear(data['GR'], 20.0, 140.0))
        
        _, results = stability_sweep(data, vsh, 0.65, 0.95, 0.05, min_points=5)
        
        for r in results:
            assert 'score' in r, "Each result should have a score"
            assert r['score'] >= 0, "Score should be non-negative"


class TestFallbackScenarios:
    """Test fallback when data is insufficient."""
    
    def test_fallback_when_no_shale_points(self):
        """Should fallback when min_points not met."""
        # Create data with no shale
        data = pd.DataFrame({
            'DEPTH': np.linspace(1000, 1050, 50),
            'GR': np.random.normal(30, 5, 50),
            'RHOB': np.random.normal(2.25, 0.03, 50),
            'NPHI': np.random.normal(0.18, 0.02, 50),
            'DT': np.random.normal(75, 4, 50)
        })
        vsh = pd.Series(calculate_vsh_linear(data['GR'], 20.0, 140.0))
        
        # High threshold = no points
        threshold, results = stability_sweep(data, vsh, 0.95, 0.99, 0.01, min_points=20)
        
        # Should fallback to 0.80
        assert threshold == 0.80, "Should fallback to default threshold"


class TestNaNHandling:
    """Test handling of NaN values."""
    
    def test_nan_in_vsh_handled(self):
        """NaN in VSH should be excluded from mask."""
        data = create_bimodal_test_data()
        vsh = pd.Series(calculate_vsh_linear(data['GR'], 20.0, 140.0))
        vsh[0:10] = np.nan  # Add more NaNs
        
        mask, n_points = build_shale_mask(vsh, 0.80)
        
        # Should not crash
        assert mask is not None
        # NaN points should be excluded
        assert mask[0:10].sum() == 0, "NaN points should be excluded"
    
    def test_nan_quantile_fallback(self):
        """NaN quantile should fallback gracefully."""
        vsh = pd.Series([np.nan, np.nan, np.nan])
        t = np.nanquantile(vsh, 0.90)
        
        # Should return nan
        assert np.isnan(t)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
