"""
Unit Tests for Petrophysics Calculator
"""

import pytest
import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.petrophysics import PetrophysicsCalculator


class TestVShaleCalculations:
    """Test Vshale calculation methods."""
    
    def test_vshale_linear_basic(self, sample_log_data):
        """Test linear Vshale calculation."""
        calc = PetrophysicsCalculator(sample_log_data)
        vsh = calc.calculate_vshale_linear('GR', gr_min=20, gr_max=120)
        
        assert len(vsh) == len(sample_log_data)
        assert vsh.min() >= 0
        assert vsh.max() <= 1
        assert 'VSH' in calc.results.columns
    
    def test_vshale_linear_auto_baseline(self, sample_log_data):
        """Test auto-calculated GR baselines."""
        calc = PetrophysicsCalculator(sample_log_data)
        vsh = calc.calculate_vshale_linear('GR')
        
        assert vsh.notna().any()
        assert vsh.min() >= 0
        assert vsh.max() <= 1
    
    def test_vshale_larionov_tertiary(self, sample_log_data):
        """Test Larionov Tertiary method."""
        calc = PetrophysicsCalculator(sample_log_data)
        igr = calc.calculate_vshale_linear('GR')
        vsh = calc.calculate_vshale_larionov_tertiary(igr)
        
        assert len(vsh) == len(sample_log_data)
        assert vsh.min() >= 0
        assert vsh.max() <= 1
    
    def test_vshale_larionov_older(self, sample_log_data):
        """Test Larionov Older rocks method."""
        calc = PetrophysicsCalculator(sample_log_data)
        igr = calc.calculate_vshale_linear('GR')
        vsh = calc.calculate_vshale_larionov_older(igr)
        
        assert len(vsh) == len(sample_log_data)
        assert vsh.min() >= 0
        assert vsh.max() <= 1
    
    def test_calculate_all_vshale(self, sample_log_data):
        """Test all Vshale methods together."""
        calc = PetrophysicsCalculator(sample_log_data)
        results = calc.calculate_all_vshale('GR')
        
        assert 'VSH_LINEAR' in results
        assert 'VSH_LARIO_TERT' in results
        assert 'VSH_LARIO_OLD' in results
    
    def test_clean_sand_low_vsh(self, clean_sand_data):
        """Clean sand should have low Vshale."""
        calc = PetrophysicsCalculator(clean_sand_data)
        vsh = calc.calculate_vshale_linear('GR', gr_min=15, gr_max=120)
        
        assert vsh.mean() < 0.3  # Clean sand should have low Vsh
    
    def test_shaly_high_vsh(self, shaly_data):
        """Shaly formation should have high Vshale."""
        calc = PetrophysicsCalculator(shaly_data)
        vsh = calc.calculate_vshale_linear('GR', gr_min=15, gr_max=120)
        
        assert vsh.mean() > 0.7  # Shale should have high Vsh


class TestPorosityCalculations:
    """Test porosity calculation methods."""
    
    def test_porosity_density(self, sample_log_data):
        """Test density porosity calculation."""
        calc = PetrophysicsCalculator(sample_log_data)
        phid = calc.calculate_porosity_density('RHOB', rho_matrix=2.65, rho_fluid=1.0)
        
        assert len(phid) == len(sample_log_data)
        assert 'PHID' in calc.results.columns
    
    def test_porosity_neutron(self, sample_log_data):
        """Test neutron porosity."""
        calc = PetrophysicsCalculator(sample_log_data)
        phin = calc.calculate_porosity_neutron('NPHI')
        
        assert len(phin) == len(sample_log_data)
        assert 'PHIN' in calc.results.columns
    
    def test_porosity_sonic(self, sample_log_data):
        """Test sonic porosity."""
        calc = PetrophysicsCalculator(sample_log_data)
        phis = calc.calculate_porosity_sonic('DT')
        
        assert len(phis) == len(sample_log_data)
        assert 'PHIS' in calc.results.columns
    
    def test_phit_neutron_density(self, sample_log_data):
        """Test total porosity from N-D."""
        calc = PetrophysicsCalculator(sample_log_data)
        calc.calculate_porosity_density('RHOB')
        calc.calculate_porosity_neutron('NPHI')
        phit = calc.calculate_phit_neutron_density()
        
        assert len(phit) == len(sample_log_data)
        assert 'PHIT' in calc.results.columns
        assert phit.max() <= 0.45


class TestEffectivePorosityCalculations:
    """Test effective porosity methods."""
    
    def test_phie_from_phit(self, sample_log_data):
        """Test PHIE from total porosity."""
        calc = PetrophysicsCalculator(sample_log_data)
        vsh = calc.calculate_vshale_linear('GR', gr_min=20, gr_max=120)
        calc.calculate_porosity_density('RHOB')
        calc.calculate_porosity_neutron('NPHI')
        calc.calculate_phit_neutron_density()
        phie = calc.calculate_phie()
        
        assert len(phie) == len(sample_log_data)
        assert 'PHIE' in calc.results.columns
    
    def test_phie_density(self, sample_log_data):
        """Test PHIE from density."""
        calc = PetrophysicsCalculator(sample_log_data)
        vsh = calc.calculate_vshale_linear('GR')
        calc.calculate_porosity_density('RHOB')
        phie_d = calc.calculate_phie_density(vsh)
        
        assert 'PHIE_D' in calc.results.columns
    
    def test_phie_neutron(self, sample_log_data):
        """Test PHIE from neutron."""
        calc = PetrophysicsCalculator(sample_log_data)
        vsh = calc.calculate_vshale_linear('GR')
        calc.calculate_porosity_neutron('NPHI')
        phie_n = calc.calculate_phie_neutron(vsh)
        
        assert 'PHIE_N' in calc.results.columns
    
    def test_calculate_all_phie(self, sample_log_data):
        """Test all PHIE methods."""
        calc = PetrophysicsCalculator(sample_log_data)
        vsh = calc.calculate_vshale_linear('GR')
        calc.calculate_porosity_density('RHOB')
        calc.calculate_porosity_neutron('NPHI')
        calc.calculate_porosity_sonic('DT')
        
        results = calc.calculate_all_phie(vsh=vsh)
        
        assert 'PHIE_D' in results
        assert 'PHIE_N' in results
        assert 'PHIE_DN' in results


class TestGasCorrectedPorosity:
    """Test gas-corrected porosity (v1.2 feature)."""
    
    def test_gas_correction_basic(self, sample_log_data):
        """Test gas correction method."""
        calc = PetrophysicsCalculator(sample_log_data)
        vsh = calc.calculate_vshale_linear('GR')
        calc.calculate_porosity_density('RHOB')
        calc.calculate_porosity_neutron('NPHI')
        
        phie_gas = calc.calculate_phie_gas_corrected(vsh)
        
        assert 'PHIE_GAS' in calc.results.columns
        assert 'GAS_FLAG' in calc.results.columns
    
    def test_gas_correction_in_gas_zone(self, gas_zone_data):
        """Gas zone should show correction effect."""
        calc = PetrophysicsCalculator(gas_zone_data)
        vsh = calc.calculate_vshale_linear('GR', gr_min=15, gr_max=120)
        calc.calculate_porosity_density('RHOB')
        calc.calculate_porosity_neutron('NPHI')
        
        phie_gas = calc.calculate_phie_gas_corrected(vsh)
        phie_dn = calc.calculate_phie_density_neutron(vsh)
        
        # Gas corrected should be higher in gas zones
        gas_flag = calc.results['GAS_FLAG']
        assert gas_flag.sum() > 0  # Should detect gas zones
    
    def test_gas_correction_toggle(self, sample_log_data):
        """Test gas correction enable/disable."""
        calc = PetrophysicsCalculator(sample_log_data)
        vsh = calc.calculate_vshale_linear('GR')
        calc.calculate_porosity_density('RHOB')
        calc.calculate_porosity_neutron('NPHI')
        calc.calculate_porosity_sonic('DT')
        
        # Without gas correction
        results_no_gas = calc.calculate_all_phie(vsh=vsh, gas_correction=False)
        assert 'PHIE_GAS' not in results_no_gas
        
        # With gas correction
        results_with_gas = calc.calculate_all_phie(vsh=vsh, gas_correction=True)
        assert 'PHIE_GAS' in results_with_gas


class TestWaterSaturationCalculations:
    """Test water saturation methods."""
    
    def test_sw_archie(self, sample_log_data):
        """Test Archie Sw calculation."""
        calc = PetrophysicsCalculator(sample_log_data)
        calc.calculate_porosity_density('RHOB')
        calc.calculate_porosity_neutron('NPHI')
        calc.calculate_phit_neutron_density()
        calc.calculate_phie()
        
        sw = calc.calculate_sw_archie('RT', rw=0.05)
        
        assert len(sw) == len(sample_log_data)
        assert 'SW_ARCHIE' in calc.results.columns
        assert sw.min() >= 0
        assert sw.max() <= 1
    
    def test_sw_indonesian(self, sample_log_data):
        """Test Indonesian Sw equation."""
        calc = PetrophysicsCalculator(sample_log_data)
        vsh = calc.calculate_vshale_linear('GR')
        calc.calculate_porosity_density('RHOB')
        calc.calculate_porosity_neutron('NPHI')
        calc.calculate_phit_neutron_density()
        calc.calculate_phie()
        
        sw = calc.calculate_sw_indonesian('RT', rw=0.05, rsh=5.0)
        
        assert len(sw) == len(sample_log_data)
        assert 'SW_INDO' in calc.results.columns
    
    def test_sw_simandoux(self, sample_log_data):
        """Test Simandoux Sw equation."""
        calc = PetrophysicsCalculator(sample_log_data)
        vsh = calc.calculate_vshale_linear('GR')
        calc.calculate_porosity_density('RHOB')
        calc.calculate_porosity_neutron('NPHI')
        calc.calculate_phit_neutron_density()
        calc.calculate_phie()
        
        sw = calc.calculate_sw_simandoux('RT', rw=0.05, rsh=5.0)
        
        assert len(sw) == len(sample_log_data)
        assert 'SW_SIMAN' in calc.results.columns


class TestMissingCurveHandling:
    """Test handling of missing curves."""
    
    def test_missing_gr_curve(self, sample_log_data):
        """Test Vshale with missing GR."""
        data = sample_log_data.drop(columns=['GR'])
        calc = PetrophysicsCalculator(data)
        
        vsh = calc.calculate_vshale_linear('GR')
        
        # Should return NaN series
        assert vsh.isna().all()
    
    def test_missing_rhob_curve(self, sample_log_data):
        """Test porosity with missing RHOB."""
        data = sample_log_data.drop(columns=['RHOB'])
        calc = PetrophysicsCalculator(data)
        
        phid = calc.calculate_porosity_density('RHOB')
        
        assert phid.isna().all()
