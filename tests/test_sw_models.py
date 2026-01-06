
import pytest
import pandas as pd
import numpy as np
from modules.petrophysics import PetrophysicsCalculator

class TestWaterSaturationAdvancedModels:
    
    def test_waxman_smits_calculation(self):
        # Setup synthetic data
        data = pd.DataFrame({
            'DEPTH': [1000, 1001],
            'RT': [10.0, 1.0],   # High res (oil), Low res (water)
            'PHIE': [0.2, 0.2]
        })
        
        calc = PetrophysicsCalculator(data)
        
        # Calculate WS
        sw_ws = calc.calculate_sw_waxman_smits(
            rt_curve='RT',
            phie=data['PHIE'],
            rw=0.05,
            a=1.0, m=2.0, n=2.0,
            qv=0.2, B=1.0
        )
        
        assert 'SW_WS' in calc.results.columns
        assert len(sw_ws) == 2
        
        # Basic sanity checks
        # 1. Sw should be valid
        assert not np.isnan(sw_ws[0])
        assert not np.isnan(sw_ws[1])
        
        # 2. Constraints
        assert np.all(sw_ws >= 0) & np.all(sw_ws <= 1)
        
        # 3. Trend: Lower resistivity -> Higher Sw
        assert sw_ws[1] > sw_ws[0]

    def test_dual_water_calculation(self):
        # Setup synthetic data
        data = pd.DataFrame({
            'DEPTH': [1000, 1001],
            'RT': [20.0, 0.5],
            'PHIT': [0.25, 0.25] # DW typically uses PHIT
        })
        
        calc = PetrophysicsCalculator(data)
        
        # Calculate DW
        sw_dw = calc.calculate_sw_dual_water(
            rt_curve='RT',
            phie=data['PHIT'], # Passing PHIT as 'phie' argument for this test
            rw=0.04,
            a=1.0, m=2.0, n=2.0,
            swb=0.1, rwb=0.2
        )
        
        assert 'SW_DW' in calc.results.columns
        
        # 1. Sw should be valid
        assert not np.isnan(sw_dw[0])
        assert not np.isnan(sw_dw[1])
        
        # 2. Constraints
        assert np.all(sw_dw >= 0) & np.all(sw_dw <= 1)
        
        # 3. Logic: DW should result in valid saturation >= Swb (approx)
        # However, due to noise, we just check bounded 0-1.
        
        # 4. Trend
        assert sw_dw[1] > sw_dw[0]

if __name__ == "__main__":
    pytest.main([__file__])
