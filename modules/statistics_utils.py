"""
Statistical Utilities Module for Petrophyter
Provides data-driven parameter estimation for petrophysics calculations
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional, List
from scipy import stats
from scipy.optimize import curve_fit


class StatisticsUtils:
    """
    Statistical utilities for data-driven parameter estimation.
    """
    
    def __init__(self, data: pd.DataFrame):
        """
        Initialize with log data.
        
        Args:
            data: DataFrame containing log data
        """
        self.data = data
        
    def estimate_gr_baseline(self, gr_curve: str = 'GR') -> Tuple[float, float]:
        """
        Estimate GR clean sand (GRmin) and shale (GRmax) baselines.
        
        Uses percentile method:
        - GRmin: P5 percentile (clean sand baseline)
        - GRmax: P95 percentile (shale baseline)
        
        Args:
            gr_curve: Name of GR curve
            
        Returns:
            Tuple of (GRmin, GRmax)
        """
        if gr_curve not in self.data.columns:
            raise ValueError(f"GR curve '{gr_curve}' not found in data")
            
        gr = self.data[gr_curve].dropna()
        
        if len(gr) == 0:
            return (0, 150)  # Default fallback
        
        gr_min = float(np.percentile(gr, 5))
        gr_max = float(np.percentile(gr, 95))
        
        # Ensure minimum separation
        if gr_max - gr_min < 20:
            gr_min = float(gr.min())
            gr_max = float(gr.max())
            
        return (gr_min, gr_max)
    
    def estimate_matrix_density(self, rhob_curve: str = 'RHOB',
                                 vsh_series: pd.Series = None) -> float:
        """
        Estimate matrix density from clean formations.
        
        Args:
            rhob_curve: Name of RHOB curve
            vsh_series: Vshale series to identify clean zones
            
        Returns:
            Estimated matrix density (g/cc)
        """
        if rhob_curve not in self.data.columns:
            return 2.65  # Default sandstone
            
        rhob = self.data[rhob_curve].dropna()
        
        if vsh_series is not None:
            # Use clean zones (Vsh < 0.2)
            clean_mask = vsh_series < 0.2
            rhob = self.data.loc[clean_mask, rhob_curve].dropna()
        
        if len(rhob) == 0:
            return 2.65
            
        # Matrix density is typically the high end of density readings
        rho_ma = float(np.percentile(rhob, 95))
        
        # Bound to reasonable range
        return np.clip(rho_ma, 2.60, 2.75)
    
    def estimate_fluid_density(self, depth_range: Tuple[float, float] = None,
                                temperature_gradient: float = 0.03,
                                surface_temp: float = 20) -> float:
        """
        Estimate formation fluid density based on depth/temperature.
        
        Args:
            depth_range: Depth range for analysis
            temperature_gradient: Temperature gradient (°C/m)
            surface_temp: Surface temperature (°C)
            
        Returns:
            Estimated fluid density (g/cc)
        """
        # For freshwater reservoirs: ~1.0 g/cc
        # For saline formations: up to 1.1 g/cc
        return 1.0  # Default to fresh water
    
    def estimate_rw_from_sp(self, sp_curve: str = 'SP', 
                            rmf: float = 0.5,
                            temp_f: float = 150) -> Optional[float]:
        """
        Estimate formation water resistivity (Rw) from SP curve.
        
        Uses SP equation:
        SP = -K * log10(Rmfe/Rwe)
        K = 61 + 0.133 * T(°F)
        
        Args:
            sp_curve: SP curve mnemonic
            rmf: Mud filtrate resistivity at formation temp
            temp_f: Formation temperature in Fahrenheit
            
        Returns:
            Estimated Rw in ohm.m
        """
        if sp_curve not in self.data.columns:
            return None
            
        sp = self.data[sp_curve].dropna()
        
        if len(sp) == 0:
            return None
        
        # Find the most negative SP (maximum deflection in water zone)
        ssp = float(sp.min())  # Static SP
        
        if ssp >= 0:  # No negative SP deflection
            return None
        
        # Calculate K factor
        k = 61 + 0.133 * temp_f
        
        # Convert Rmf to Rmfe (equivalent)
        rmfe = rmf * 0.85  # Approximation
        
        # Calculate Rwe from SP equation
        rwe = rmfe / (10 ** (-ssp / k))
        
        # Convert Rwe to Rw
        rw = rwe * 1.07  # Approximation
        
        return max(0.01, min(rw, 5.0))  # Bound to reasonable range
    
    def estimate_rw_from_rt_water_zone(self, rt_curve: str = 'RT',
                                        phi_curve: str = 'PHIT',
                                        porosity_threshold: float = 0.15,
                                        a: float = 0.62,
                                        m: float = 2.15) -> Optional[float]:
        """
        Estimate Rw from Rt in water-bearing zones.
        
        Assumes 100% water saturation in zones with:
        - High porosity
        - High resistivity relative to local minimum
        
        Args:
            rt_curve: Resistivity curve mnemonic
            phi_curve: Porosity curve mnemonic
            porosity_threshold: Minimum porosity for water zone
            a, m: Archie parameters
            
        Returns:
            Estimated Rw in ohm.m
        """
        if rt_curve not in self.data.columns:
            return None
            
        rt = self.data[rt_curve].dropna()
        
        if len(rt) == 0:
            return None
        
        if phi_curve in self.data.columns:
            phi = self.data[phi_curve]
            # Water zones: high porosity, low Rt
            water_mask = (phi > porosity_threshold) & (rt < np.percentile(rt, 25))
            if water_mask.sum() > 0:
                rt_water = rt[water_mask].median()
                phi_water = phi[water_mask].median()
                
                # Rw = Rt * phi^m / a (assuming Sw = 1)
                rw = rt_water * (phi_water ** m) / a
                return max(0.01, min(float(rw), 5.0))
        
        # Fallback: use minimum Rt with typical porosity
        rt_min = float(np.percentile(rt, 5))
        phi_assumed = 0.20
        rw = rt_min * (phi_assumed ** m) / a
        
        return max(0.01, min(rw, 5.0))
    
    def estimate_rsh(self, rt_curve: str = 'RT',
                      vsh_series: pd.Series = None,
                      gr_curve: str = 'GR') -> float:
        """
        Estimate shale resistivity (Rsh) from pure shale zones.
        
        Args:
            rt_curve: Resistivity curve mnemonic
            vsh_series: Vshale series
            gr_curve: GR curve mnemonic (fallback)
            
        Returns:
            Estimated Rsh in ohm.m
        """
        if rt_curve not in self.data.columns:
            return 5.0  # Default
            
        rt = self.data[rt_curve]
        
        # Identify shale zones
        if vsh_series is not None:
            shale_mask = vsh_series > 0.8
        elif gr_curve in self.data.columns:
            gr = self.data[gr_curve]
            gr_p90 = np.percentile(gr.dropna(), 90)
            shale_mask = gr > gr_p90
        else:
            # Use low resistivity as proxy
            shale_mask = rt < np.percentile(rt.dropna(), 20)
        
        rt_shale = rt[shale_mask].dropna()
        
        if len(rt_shale) == 0:
            return 5.0
            
        rsh = float(rt_shale.median())
        
        return max(0.5, min(rsh, 50.0))
    
    def estimate_dt_matrix(self, dt_curve: str = 'DT',
                           vsh_series: pd.Series = None) -> float:
        """
        Estimate matrix sonic transit time.
        
        Args:
            dt_curve: DT curve mnemonic
            vsh_series: Vshale series to identify clean zones
            
        Returns:
            Estimated DTma in µs/ft
        """
        if dt_curve not in self.data.columns:
            return 55.5  # Default sandstone
            
        dt = self.data[dt_curve].dropna()
        
        if vsh_series is not None:
            clean_mask = vsh_series < 0.2
            dt = self.data.loc[clean_mask, dt_curve].dropna()
        
        if len(dt) == 0:
            return 55.5
        
        # Matrix DT is typically the low end
        dt_ma = float(np.percentile(dt, 5))
        
        return np.clip(dt_ma, 50, 60)
    
    def calibrate_permeability_coefficients(self,
                                            core_k: np.ndarray,
                                            core_phi: np.ndarray,
                                            core_swi: np.ndarray = None) -> Dict[str, float]:
        """
        Calibrate Wyllie-Rose/Timur permeability coefficients using core data.
        
        K = C * (PHI^P) / (Swi^Q)
        
        Uses log-log regression:
        log(K) = log(C) + P*log(PHI) - Q*log(Swi)
        
        Args:
            core_k: Core permeability values (mD)
            core_phi: Core porosity values (fraction)
            core_swi: Core irreducible water saturation (fraction)
            
        Returns:
            Dictionary with C, P, Q coefficients
        """
        # Default values (Timur)
        defaults = {'C': 8581, 'P': 4.4, 'Q': 2.0}
        
        if len(core_k) < 5:
            return defaults
        
        # Filter valid data
        valid = (core_k > 0) & (core_phi > 0)
        if core_swi is not None:
            valid &= (core_swi > 0)
        
        k = core_k[valid]
        phi = core_phi[valid]
        
        if len(k) < 5:
            return defaults
        
        if core_swi is not None and len(core_swi[valid]) == len(k):
            swi = core_swi[valid]
            
            # Multiple linear regression in log space
            # log(K) = log(C) + P*log(PHI) - Q*log(Swi)
            X = np.column_stack([
                np.ones(len(k)),
                np.log10(phi),
                -np.log10(swi)
            ])
            y = np.log10(k)
            
            try:
                coeffs, residuals, rank, s = np.linalg.lstsq(X, y, rcond=None)
                C = 10 ** coeffs[0]
                P = coeffs[1]
                Q = coeffs[2]
                
                return {
                    'C': float(np.clip(C, 100, 50000)),
                    'P': float(np.clip(P, 3, 6)),
                    'Q': float(np.clip(Q, 1, 3))
                }
            except:
                pass
        else:
            # Simple regression: log(K) = log(C) + P*log(PHI)
            try:
                slope, intercept, r_value, p_value, std_err = stats.linregress(
                    np.log10(phi), np.log10(k)
                )
                C = 10 ** intercept
                P = slope
                
                return {
                    'C': float(np.clip(C, 100, 50000)),
                    'P': float(np.clip(P, 3, 6)),
                    'Q': 2.0  # Default
                }
            except:
                pass
        
        return defaults
    
    def estimate_swi(self, sw_series: pd.Series,
                      vsh_series: pd.Series = None) -> float:
        """
        Estimate irreducible water saturation (Swi).
        
        Args:
            sw_series: Water saturation series
            vsh_series: Vshale series
            
        Returns:
            Estimated Swi (fraction)
        """
        sw = sw_series.dropna()
        
        if vsh_series is not None:
            # Focus on clean zones
            clean_mask = vsh_series < 0.3
            sw = sw_series[clean_mask].dropna()
        
        if len(sw) == 0:
            return 0.2  # Default
        
        # Swi is typically around P10-P20 of Sw distribution
        swi = float(np.percentile(sw, 15))
        
        return np.clip(swi, 0.05, 0.5)
    
    def estimate_shale_parameters(self, gr_curve: str = 'GR',
                                   rhob_curve: str = 'RHOB',
                                   nphi_curve: str = 'NPHI',
                                   dt_curve: str = 'DT',
                                   vsh_threshold: float = 0.8) -> Dict[str, float]:
        """
        Estimate shale parameters from pure shale zones using statistical approach.
        
        Identifies pure shale zones (Vsh > threshold) and calculates:
        - rho_shale: Mean RHOB in shale zones
        - nphi_shale: Mean NPHI in shale zones  
        - dt_shale: Mean DT in shale zones
        
        Args:
            gr_curve: GR curve mnemonic
            rhob_curve: RHOB curve mnemonic
            nphi_curve: NPHI curve mnemonic
            dt_curve: DT curve mnemonic
            vsh_threshold: Vsh threshold for pure shale identification
            
        Returns:
            Dictionary with estimated shale parameters
        """
        results = {
            'rho_shale': 2.45,
            'nphi_shale': 0.35,
            'dt_shale': 100.0,
            'gr_min': 20.0,
            'gr_max': 120.0,
            'method': 'default'
        }
        
        # First, identify shale zones using GR
        if gr_curve in self.data.columns:
            gr = self.data[gr_curve]
            gr_valid = gr.dropna()
            if len(gr_valid) > 0:
                gr_min = float(np.percentile(gr_valid, 5))
                gr_max = float(np.percentile(gr_valid, 95))
                results['gr_min'] = gr_min
                results['gr_max'] = gr_max
                
                # Calculate IGR (GR index) on full data
                igr = (gr - gr_min) / (gr_max - gr_min) if (gr_max - gr_min) > 10 else gr / 150
                igr = np.clip(igr, 0, 1)
                
                # Pure shale zones: IGR > threshold
                shale_mask = (igr > vsh_threshold) & (gr.notna())
                
                if shale_mask.sum() > 0:
                    results['method'] = 'statistical'
                    
                    # Get shale zone indices
                    shale_indices = shale_mask[shale_mask].index
                    
                    # Estimate RHOB_shale
                    if rhob_curve in self.data.columns:
                        rhob_shale_values = self.data.loc[shale_indices, rhob_curve].dropna()
                        if len(rhob_shale_values) > 0:
                            results['rho_shale'] = float(np.median(rhob_shale_values))
                    
                    # Estimate NPHI_shale
                    if nphi_curve in self.data.columns:
                        nphi_shale_values = self.data.loc[shale_indices, nphi_curve].dropna()
                        if len(nphi_shale_values) > 0:
                            results['nphi_shale'] = float(np.median(nphi_shale_values))
                    
                    # Estimate DT_shale
                    if dt_curve in self.data.columns:
                        dt_shale_values = self.data.loc[shale_indices, dt_curve].dropna()
                        if len(dt_shale_values) > 0:
                            results['dt_shale'] = float(np.median(dt_shale_values))
        
        # Bound to reasonable ranges
        results['rho_shale'] = np.clip(results['rho_shale'], 2.2, 2.7)
        results['nphi_shale'] = np.clip(results['nphi_shale'], 0.15, 0.5)
        results['dt_shale'] = np.clip(results['dt_shale'], 70, 150)
        
        return results
    
    def get_shale_zone_statistics(self, gr_curve: str = 'GR',
                                   rhob_curve: str = 'RHOB',
                                   nphi_curve: str = 'NPHI', 
                                   dt_curve: str = 'DT',
                                   vsh_threshold: float = 0.8) -> Dict[str, Dict]:
        """
        Get detailed statistics for shale zones.
        
        Returns mean, std, min, max for each shale parameter.
        """
        stats = {}
        
        if gr_curve in self.data.columns:
            gr = self.data[gr_curve]
            gr_valid = gr.dropna()
            if len(gr_valid) > 0:
                gr_min = float(np.percentile(gr_valid, 5))
                gr_max = float(np.percentile(gr_valid, 95))
                igr = (gr - gr_min) / (gr_max - gr_min) if (gr_max - gr_min) > 10 else gr / 150
                igr = np.clip(igr, 0, 1)
                shale_mask = (igr > vsh_threshold) & (gr.notna())
                
                if shale_mask.sum() > 0:
                    stats['shale_points'] = int(shale_mask.sum())
                    
                    # Get shale zone indices
                    shale_indices = shale_mask[shale_mask].index
                    
                    for curve_name, curve_key in [(rhob_curve, 'RHOB'), (nphi_curve, 'NPHI'), (dt_curve, 'DT')]:
                        if curve_name in self.data.columns:
                            values = self.data.loc[shale_indices, curve_name].dropna()
                            if len(values) > 0:
                                stats[curve_key] = {
                                    'mean': float(values.mean()),
                                    'std': float(values.std()),
                                    'min': float(values.min()),
                                    'max': float(values.max()),
                                    'median': float(values.median())
                                }
        return stats


def get_humble_parameters() -> Dict[str, float]:
    """
    Get Humble equation parameters for Archie-type equations.
    
    Returns:
        Dictionary with a, m, n parameters
    """
    return {
        'a': 0.62,      # Tortuosity factor
        'm': 2.15,      # Cementation exponent
        'n': 2.0        # Saturation exponent
    }


def get_default_fluid_parameters() -> Dict[str, float]:
    """
    Get default fluid parameters.
    
    Returns:
        Dictionary with fluid parameters
    """
    return {
        'rho_fluid': 1.0,      # Water density (g/cc)
        'dt_fluid': 189.0,     # Water DT (µs/ft)
    }


def get_default_matrix_parameters(lithology: str = 'sandstone') -> Dict[str, float]:
    """
    Get default matrix parameters for common lithologies.
    
    Args:
        lithology: Lithology type ('sandstone', 'limestone', 'dolomite')
        
    Returns:
        Dictionary with matrix parameters
    """
    params = {
        'sandstone': {
            'rho_matrix': 2.65,
            'dt_matrix': 55.5,
            'nphi_matrix': -0.02,
        },
        'limestone': {
            'rho_matrix': 2.71,
            'dt_matrix': 47.5,
            'nphi_matrix': 0.0,
        },
        'dolomite': {
            'rho_matrix': 2.87,
            'dt_matrix': 43.5,
            'nphi_matrix': 0.02,
        }
    }
    
    return params.get(lithology.lower(), params['sandstone'])


def get_default_shale_parameters() -> Dict[str, float]:
    """
    Get default shale parameters.
    
    Returns:
        Dictionary with shale parameters
    """
    return {
        'rho_shale': 2.45,
        'dt_shale': 100.0,
        'nphi_shale': 0.35,
    }
