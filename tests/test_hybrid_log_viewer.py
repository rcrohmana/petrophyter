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
    """The real InteractiveLogPlot default configuration (items, not pixels)."""

    @pytest.fixture
    def plot(self, qtbot):
        pytest.importorskip("pyqtgraph")
        from ui.widgets.interactive_log import InteractiveLogPlot

        widget = InteractiveLogPlot(n_tracks=6)
        qtbot.addWidget(widget)
        return widget

    def test_curve_assignment(self, plot):
        columns = ["DEPTH", "GR", "VSH", "PHIE", "NPHI", "SW", "PERM_WR"]
        config = plot._default_curve_config(columns)

        assert [c[0] for c in config[0]] == ["GR", "VSH"]
        assert [c[0] for c in config[1]] == ["PHIE"]
        assert [c[0] for c in config[2]] == ["SW"]
        assert [c[0] for c in config[3]] == ["PERM_WR"]

    def test_plotted_items_follow_config(self, plot):
        data = create_dummy_log_data()
        plot.plot_curves(data)

        assert set(plot.curve_items) == {"GR", "VSH", "PHIE"}
        assert plot.plot_widgets[0].getAxis("bottom").labelText == "GR (API)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
