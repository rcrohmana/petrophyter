"""
Unit Tests for Session Service
"""

import pytest
import json
import tempfile
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.session_service import SessionService


class MockModel:
    """Mock AppModel for testing."""
    
    def __init__(self):
        # Analysis mode
        self.analysis_mode = "Whole Well"
        self.selected_formations = []
        
        # VShale
        self.vsh_baseline_method = "Statistically (Auto)"
        self.gr_min_manual = 20.0
        self.gr_max_manual = 120.0
        self.vsh_methods = ["Linear"]
        
        # Matrix
        self.rho_matrix = 2.65
        self.dt_matrix = 55.5
        
        # Fluid
        self.rho_fluid = 1.0
        self.dt_fluid = 189.0
        
        # Shale
        self.shale_approach = "Custom (Manual)"
        self.rho_shale = 2.45
        self.dt_shale = 100.0
        self.nphi_shale = 0.35
        
        # Archie
        self.lithology_preset = "Sandstone (Humble)"
        self.a = 0.62
        self.m = 2.15
        self.n = 2.0
        
        # Resistivity
        self.rw = 0.05
        self.rsh = 5.0
        
        # Perm
        self.perm_C = 8581.0
        self.perm_P = 4.4
        self.perm_Q = 2.0
        
        # Swirr
        self.swirr_method = "Hierarchical (Recommended)"
        self.buckles_preset = "Sandstone (Clean)"
        self.k_buckles = 0.02
        
        # Cutoffs
        self.vsh_cutoff = 0.4
        self.phi_cutoff = 0.08
        self.sw_cutoff = 0.6
        
        # Merge
        self.merge_step = 0.5
        self.merge_gap_limit = 5.0
        
        # Core
        self.core_depth_unit = "Auto"
        self.core_max_dist = 2.0
        
        # Gas correction (v1.2)
        self.gas_correction_enabled = False
        self.gas_nphi_factor = 0.30
        self.gas_rhob_factor = 0.15
        
        # LAS filename
        self.las_filename = "test.las"


class TestSessionSaveLoad:
    """Test session save/load functionality."""
    
    def test_save_session(self):
        """Test saving session to file."""
        service = SessionService()
        model = MockModel()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            file_path = f.name
        
        try:
            result = service.save_session(model, file_path)
            assert result is True
            assert os.path.exists(file_path)
            
            # Verify JSON structure
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            assert '_session_version' in data
            assert data['rho_matrix'] == 2.65
            assert data['rw'] == 0.05
        finally:
            if os.path.exists(file_path):
                os.unlink(file_path)
    
    def test_load_session(self):
        """Test loading session from file."""
        service = SessionService()
        
        # Create test session file
        session_data = {
            '_session_version': '1.2',
            'rho_matrix': 2.71,
            'rw': 0.08,
            'gas_correction_enabled': True
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(session_data, f)
            file_path = f.name
        
        try:
            loaded = service.load_session(file_path)
            
            assert loaded is not None
            assert loaded['rho_matrix'] == 2.71
            assert loaded['rw'] == 0.08
            assert loaded['gas_correction_enabled'] is True
        finally:
            if os.path.exists(file_path):
                os.unlink(file_path)
    
    def test_apply_session_to_model(self):
        """Test applying loaded session to model."""
        service = SessionService()
        model = MockModel()
        
        session_data = {
            'rho_matrix': 2.71,
            'dt_matrix': 60.0,
            'rw': 0.08,
            'rsh': 10.0,
            'gas_correction_enabled': True,
            'gas_nphi_factor': 0.35
        }
        
        result = service.apply_session_to_model(model, session_data)
        
        assert result is True
        assert model.rho_matrix == 2.71
        assert model.dt_matrix == 60.0
        assert model.rw == 0.08
        assert model.gas_correction_enabled is True
        assert model.gas_nphi_factor == 0.35
    
    def test_round_trip(self):
        """Test full save-load-apply cycle."""
        service = SessionService()
        model1 = MockModel()
        
        # Modify some values
        model1.rho_matrix = 2.68
        model1.rw = 0.10
        model1.gas_correction_enabled = True
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            file_path = f.name
        
        try:
            # Save
            service.save_session(model1, file_path)
            
            # Load into new model
            model2 = MockModel()
            session_data = service.load_session(file_path)
            service.apply_session_to_model(model2, session_data)
            
            # Verify values match
            assert model2.rho_matrix == 2.68
            assert model2.rw == 0.10
            assert model2.gas_correction_enabled is True
        finally:
            if os.path.exists(file_path):
                os.unlink(file_path)
    
    def test_load_invalid_file(self):
        """Test loading invalid file."""
        service = SessionService()
        
        result = service.load_session("nonexistent_file.json")
        
        assert result is None
    
    def test_load_corrupted_json(self):
        """Test loading corrupted JSON."""
        service = SessionService()
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("{ invalid json }")
            file_path = f.name
        
        try:
            result = service.load_session(file_path)
            assert result is None
        finally:
            if os.path.exists(file_path):
                os.unlink(file_path)
