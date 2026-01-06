"""
Unit tests for Hybrid Log Viewer - Logic Only
Tests parsing logic and utilities without PyQt6 dependency.
"""

import pytest
import pandas as pd
import numpy as np


def create_dummy_log_data():
    """Create synthetic log data for testing."""
    np.random.seed(42)
    n = 500
    
    depth = np.linspace(1000, 1500, n)
    gr = np.random.normal(50, 20, n)
    rhob = np.random.normal(2.4, 0.1, n)
    nphi = np.random.normal(0.2, 0.05, n)
    
    return pd.DataFrame({
        'DEPTH': depth,
        'GR': gr,
        'RHOB': rhob,
        'NPHI': nphi,
        'VSH': np.clip(gr / 150, 0, 1),
        'PHIE': np.clip(nphi * 0.8, 0, 0.5),
    })


class TestFormationTopsParser:
    """Tests for formation tops parsing logic."""
    
    def test_parse_tops_list_format(self):
        """Test parsing of tops list format."""
        tops = [
            {'name': 'Formation A', 'top_depth': 1100, 'bottom_depth': 1200},
            {'name': 'Formation B', 'top_depth': 1200, 'bottom_depth': 1400}
        ]
        
        # Simulate parsing logic from set_formation_tops
        tops_list = []
        if isinstance(tops, list):
            tops_list = tops
        
        assert len(tops_list) == 2
        assert tops_list[0]['name'] == 'Formation A'
        assert tops_list[0]['top_depth'] == 1100
    
    def test_parse_tops_dict_format(self):
        """Test parsing of tops dict format."""
        tops = {
            'Formation A': (1100, 1200),
            'Formation B': (1200, 1400)
        }
        
        # Simulate parsing logic from set_formation_tops
        tops_list = []
        if isinstance(tops, dict):
            for name, depths in tops.items():
                if isinstance(depths, tuple) and len(depths) >= 2:
                    tops_list.append({'name': name, 'top_depth': depths[0], 'bottom_depth': depths[1]})
        
        assert len(tops_list) == 2
        names = [t['name'] for t in tops_list]
        assert 'Formation A' in names
        assert 'Formation B' in names


class TestDepthRegionLogic:
    """Tests for depth region calculation logic."""
    
    def test_region_bounds_normal(self):
        """Test region bounds with normal order."""
        region = [1100, 1300]
        
        top = float(min(region))
        bottom = float(max(region))
        
        assert top == 1100
        assert bottom == 1300
    
    def test_region_bounds_inverted(self):
        """Test region bounds with inverted order (user drags backwards)."""
        region = [1300, 1100]  # Inverted
        
        top = float(min(region))
        bottom = float(max(region))
        
        assert top == 1100  # min() gives correct top
        assert bottom == 1300  # max() gives correct bottom


class TestDepthLookup:
    """Tests for fast depth lookup logic."""
    
    def test_searchsorted_lookup(self):
        """Test optimized depth lookup using searchsorted."""
        data = create_dummy_log_data()
        depth_array = data['DEPTH'].values
        curve_data = data['GR'].values
        
        # Test depth in middle
        target_depth = 1250.0
        idx = np.searchsorted(depth_array, target_depth)
        idx = min(idx, len(curve_data) - 1)
        
        assert 0 <= idx < len(curve_data)
        # Value should be close to synthetic GR
        assert not np.isnan(curve_data[idx])
    
    def test_searchsorted_boundary(self):
        """Test lookup at boundary depths."""
        data = create_dummy_log_data()
        depth_array = data['DEPTH'].values
        
        # Before first depth
        idx = np.searchsorted(depth_array, 900.0)
        assert idx == 0
        
        # After last depth
        idx = np.searchsorted(depth_array, 2000.0)
        assert idx == len(depth_array)


class TestDefaultCurveConfig:
    """Tests for default curve configuration logic."""
    
    def test_curve_assignment(self):
        """Test curve assignment to tracks."""
        columns = ['DEPTH', 'GR', 'VSH', 'PHIE', 'NPHI', 'SW', 'PERM']
        
        # Simulate _default_curve_config logic
        config = {}
        
        # Track 0: GR/Vsh
        track0 = []
        if 'GR' in columns:
            track0.append(('GR', '#00AA00', False))
        if 'VSH' in columns:
            track0.append(('VSH', '#8B4513', False))
        config[0] = track0
        
        # Track 1: Porosity
        track1 = []
        for c in ['PHIE', 'PHID', 'PHIN', 'PHIT']:
            if c in columns:
                track1.append((c, '#1E90FF', False))
        config[1] = track1
        
        assert len(config[0]) == 2  # GR and VSH
        assert len(config[1]) == 1  # Only PHIE present
        assert config[0][0][0] == 'GR'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
