"""
Petrophysics Calculations Module for Petrophyter
Core calculations for Vshale, Porosity, Sw, and Permeability
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional
from scipy.optimize import brentq


class PetrophysicsCalculator:
    """
    Petrophysics calculations engine.

    Implements:
    - Vshale (Linear GR method)
    - Porosity (Density, Neutron-Density, Sonic)
    - Water Saturation (Archie, Indonesian, Simandoux)
    - Permeability (Wyllie-Rose, Timur)
    """

    def __init__(self, data: pd.DataFrame):
        """
        Initialize calculator with log data.

        Args:
            data: DataFrame containing log curves
        """
        self.data = data.copy()
        self.results = pd.DataFrame(index=data.index)
        if "DEPTH" in data.columns:
            self.results["DEPTH"] = data["DEPTH"]

    # =========================================================================
    # VSHALE CALCULATIONS
    # =========================================================================

    def calculate_vshale_linear(
        self, gr_curve: str = "GR", gr_min: float = None, gr_max: float = None
    ) -> pd.Series:
        """
        Calculate Vshale using Linear GR method.

        Vsh = (GR - GR_min) / (GR_max - GR_min)

        Args:
            gr_curve: GR curve mnemonic
            gr_min: Clean sand GR (auto-calculated if None)
            gr_max: Pure shale GR (auto-calculated if None)

        Returns:
            Vshale series (0-1)
        """
        if gr_curve not in self.data.columns:
            return pd.Series([np.nan] * len(self.data))

        gr = self.data[gr_curve]

        # Auto-calculate baselines if not provided
        if gr_min is None:
            gr_min = float(np.nanpercentile(gr, 5))
        if gr_max is None:
            gr_max = float(np.nanpercentile(gr, 95))

        # Ensure minimum separation
        if gr_max - gr_min < 10:
            gr_min = float(np.nanmin(gr))
            gr_max = float(np.nanmax(gr))

        # Calculate Vshale
        vsh = (gr - gr_min) / (gr_max - gr_min)

        # Clip to 0-1 range
        vsh = np.clip(vsh, 0, 1)

        self.results["VSH"] = vsh
        return vsh

    def calculate_vshale_larionov_tertiary(self, igr: pd.Series) -> pd.Series:
        """
        Calculate Vshale using Larionov equation for Tertiary rocks.

        Vsh = 0.083 * (2^(3.7*IGR) - 1)

        Args:
            igr: GR index (linear Vsh)

        Returns:
            Vshale series
        """
        vsh = 0.083 * (np.power(2, 3.7 * igr) - 1)
        return np.clip(vsh, 0, 1)

    def calculate_vshale_larionov_older(self, igr: pd.Series) -> pd.Series:
        """
        Calculate Vshale using Larionov equation for older (consolidated) rocks.

        Vsh = 0.33 * (2^(2*IGR) - 1)

        Args:
            igr: GR index (linear Vsh)

        Returns:
            Vshale series
        """
        vsh = 0.33 * (np.power(2, 2 * igr) - 1)
        return np.clip(vsh, 0, 1)

    def calculate_all_vshale(
        self,
        gr_curve: str = "GR",
        gr_min: float = None,
        gr_max: float = None,
        methods: list = None,
    ) -> Dict[str, pd.Series]:
        """
        Calculate Vshale using multiple methods.

        Args:
            gr_curve: GR curve mnemonic
            gr_min: Clean sand GR baseline
            gr_max: Pure shale GR baseline
            methods: List of methods to calculate. Options:
                     'linear', 'larionov_tertiary', 'larionov_older'
                     If None, calculates all methods.

        Returns:
            Dictionary with Vshale for each method
        """
        if methods is None:
            methods = ["linear", "larionov_tertiary", "larionov_older"]

        # First calculate linear (IGR - Gamma Ray Index)
        igr = self.calculate_vshale_linear(gr_curve, gr_min, gr_max)

        results = {}

        if "linear" in methods:
            results["VSH_LINEAR"] = igr.copy()
            self.results["VSH_LINEAR"] = igr.copy()

        if "larionov_tertiary" in methods:
            vsh_tertiary = self.calculate_vshale_larionov_tertiary(igr)
            results["VSH_LARIO_TERT"] = vsh_tertiary
            self.results["VSH_LARIO_TERT"] = vsh_tertiary

        if "larionov_older" in methods:
            vsh_older = self.calculate_vshale_larionov_older(igr)
            results["VSH_LARIO_OLD"] = vsh_older
            self.results["VSH_LARIO_OLD"] = vsh_older

        # Set default VSH (linear by default, can be overridden)
        if "linear" in methods:
            self.results["VSH"] = results["VSH_LINEAR"]

        return results

    # =========================================================================
    # POROSITY CALCULATIONS
    # =========================================================================

    def calculate_porosity_density(
        self, rhob_curve: str = "RHOB", rho_matrix: float = 2.65, rho_fluid: float = 1.0
    ) -> pd.Series:
        """
        Calculate density porosity (PHID).

        PHID = (RHO_ma - RHOB) / (RHO_ma - RHO_fl)

        Args:
            rhob_curve: Bulk density curve mnemonic
            rho_matrix: Matrix density (g/cc)
            rho_fluid: Fluid density (g/cc)

        Returns:
            Density porosity series
        """
        if rhob_curve not in self.data.columns:
            return pd.Series([np.nan] * len(self.data))

        rhob = self.data[rhob_curve]

        phid = (rho_matrix - rhob) / (rho_matrix - rho_fluid)

        # Clip to reasonable range
        phid = np.clip(phid, -0.05, 0.50)

        self.results["PHID"] = phid
        return phid

    def calculate_porosity_neutron(
        self, nphi_curve: str = "NPHI", nphi_matrix: float = -0.02
    ) -> pd.Series:
        """
        Calculate neutron porosity (corrected).

        Args:
            nphi_curve: Neutron porosity curve mnemonic
            nphi_matrix: Matrix neutron porosity response

        Returns:
            Neutron porosity series
        """
        if nphi_curve not in self.data.columns:
            return pd.Series([np.nan] * len(self.data))

        nphi = self.data[nphi_curve].copy()

        # Apply matrix correction if needed
        phin = nphi - nphi_matrix

        # Clip to reasonable range
        phin = np.clip(phin, -0.05, 0.50)

        self.results["PHIN"] = phin
        return phin

    def calculate_porosity_sonic(
        self, dt_curve: str = "DT", dt_matrix: float = 55.5, dt_fluid: float = 189.0
    ) -> pd.Series:
        """
        Calculate sonic porosity using Wyllie time-average equation.

        PHIS = (DT - DT_ma) / (DT_fl - DT_ma)

        Args:
            dt_curve: Sonic transit time curve mnemonic
            dt_matrix: Matrix transit time (µs/ft)
            dt_fluid: Fluid transit time (µs/ft)

        Returns:
            Sonic porosity series
        """
        if dt_curve not in self.data.columns:
            return pd.Series([np.nan] * len(self.data))

        dt = self.data[dt_curve]

        phis = (dt - dt_matrix) / (dt_fluid - dt_matrix)

        # Clip to reasonable range
        phis = np.clip(phis, 0, 0.50)

        self.results["PHIS"] = phis
        return phis

    def calculate_phit_neutron_density(
        self, phid: pd.Series = None, phin: pd.Series = None
    ) -> pd.Series:
        """
        Calculate total porosity from neutron-density crossplot.

        PHIT = sqrt((NPHI^2 + PHID^2) / 2)

        Args:
            phid: Density porosity series
            phin: Neutron porosity series

        Returns:
            Total porosity series
        """
        if phid is None:
            phid = self.results.get("PHID", pd.Series([np.nan] * len(self.data)))
        if phin is None:
            phin = self.results.get("PHIN", pd.Series([np.nan] * len(self.data)))

        # Square root mean of squares
        phit = np.sqrt((phid**2 + phin**2) / 2)

        # Clip to reasonable range
        phit = np.clip(phit, 0, 0.45)

        self.results["PHIT"] = phit
        return phit

    def calculate_phie(
        self, phit: pd.Series = None, vsh: pd.Series = None
    ) -> pd.Series:
        """
        Calculate effective porosity from total porosity.

        PHIE = PHIT * (1 - Vsh)

        Args:
            phit: Total porosity series
            vsh: Vshale series

        Returns:
            Effective porosity series
        """
        if phit is None:
            phit = self.results.get("PHIT", pd.Series([np.nan] * len(self.data)))
        if vsh is None:
            vsh = self.results.get("VSH", pd.Series([0] * len(self.data)))

        phie = phit * (1 - vsh)

        # Clip to reasonable range
        phie = np.clip(phie, 0, 0.40)

        self.results["PHIE"] = phie
        return phie

    def calculate_phie_density(
        self,
        vsh: pd.Series = None,
        rhob_shale: float = 2.45,
        rho_matrix: float = 2.65,
        rho_fluid: float = 1.0,
    ) -> pd.Series:
        """
        Calculate effective porosity from density (PHIE_D).

        PHIE_D = PHID - (Vsh * PHID_shale)

        Args:
            vsh: Vshale series
            rhob_shale: Shale bulk density (g/cc)
            rho_matrix: Matrix density (g/cc)
            rho_fluid: Fluid density (g/cc)

        Returns:
            Effective density porosity series
        """
        phid = self.results.get("PHID", pd.Series([np.nan] * len(self.data)))
        if vsh is None:
            vsh = self.results.get("VSH", pd.Series([0] * len(self.data)))

        # Shale porosity from density
        phid_shale = (rho_matrix - rhob_shale) / (rho_matrix - rho_fluid)

        # Shale correction
        phie_d = phid - (vsh * phid_shale)
        phie_d = np.clip(phie_d, 0, 0.40)

        self.results["PHIE_D"] = phie_d
        return phie_d

    def calculate_phie_neutron(
        self, vsh: pd.Series = None, nphi_shale: float = 0.35
    ) -> pd.Series:
        """
        Calculate effective porosity from neutron (PHIE_N).

        PHIE_N = PHIN - (Vsh * NPHI_shale)

        Args:
            vsh: Vshale series
            nphi_shale: Shale neutron porosity response

        Returns:
            Effective neutron porosity series
        """
        phin = self.results.get("PHIN", pd.Series([np.nan] * len(self.data)))
        if vsh is None:
            vsh = self.results.get("VSH", pd.Series([0] * len(self.data)))

        # Shale correction
        phie_n = phin - (vsh * nphi_shale)
        phie_n = np.clip(phie_n, 0, 0.40)

        self.results["PHIE_N"] = phie_n
        return phie_n

    def calculate_phie_sonic(
        self,
        vsh: pd.Series = None,
        dt_shale: float = 100.0,
        dt_matrix: float = 55.5,
        dt_fluid: float = 189.0,
    ) -> pd.Series:
        """
        Calculate effective porosity from sonic (PHIE_S).

        Apply shale correction to sonic porosity.

        Args:
            vsh: Vshale series
            dt_shale: Shale sonic transit time
            dt_matrix: Matrix sonic transit time
            dt_fluid: Fluid sonic transit time

        Returns:
            Effective sonic porosity series
        """
        phis = self.results.get("PHIS", pd.Series([np.nan] * len(self.data)))
        if vsh is None:
            vsh = self.results.get("VSH", pd.Series([0] * len(self.data)))

        # Shale porosity
        phi_shale = (dt_shale - dt_matrix) / (dt_fluid - dt_matrix)

        # Shale correction
        phie_s = phis - (vsh * phi_shale)
        phie_s = np.clip(phie_s, 0, 0.40)

        self.results["PHIE_S"] = phie_s
        return phie_s

    def calculate_phie_density_neutron(
        self,
        vsh: pd.Series = None,
        nphi_shale: float = 0.35,
        rhob_shale: float = 2.45,
        rho_matrix: float = 2.65,
        rho_fluid: float = 1.0,
    ) -> pd.Series:
        """
        Calculate effective porosity from density-neutron crossplot (PHIE_DN).

        Uses shale-corrected N-D crossplot.

        Args:
            vsh: Vshale series
            nphi_shale: Shale neutron porosity
            rhob_shale: Shale bulk density
            rho_matrix: Matrix density
            rho_fluid: Fluid density

        Returns:
            Effective density-neutron porosity series
        """
        phid = self.results.get("PHID", pd.Series([np.nan] * len(self.data)))
        phin = self.results.get("PHIN", pd.Series([np.nan] * len(self.data)))
        if vsh is None:
            vsh = self.results.get("VSH", pd.Series([0] * len(self.data)))

        # Shale porosity from density
        phid_shale = (rho_matrix - rhob_shale) / (rho_matrix - rho_fluid)

        # Corrected porosities
        phid_corr = phid - (vsh * phid_shale)
        phin_corr = phin - (vsh * nphi_shale)

        # Clip negative values
        phid_corr = np.maximum(phid_corr, 0)
        phin_corr = np.maximum(phin_corr, 0)

        # RMS average
        phie_dn = np.sqrt((phid_corr**2 + phin_corr**2) / 2)
        phie_dn = np.clip(phie_dn, 0, 0.40)

        self.results["PHIE_DN"] = phie_dn
        return phie_dn

    def calculate_all_phie(
        self,
        vsh: pd.Series = None,
        nphi_shale: float = 0.35,
        rhob_shale: float = 2.45,
        dt_shale: float = 100.0,
        rho_matrix: float = 2.65,
        rho_fluid: float = 1.0,
        dt_matrix: float = 55.5,
        dt_fluid: float = 189.0,
        gas_correction: bool = False,
        gas_nphi_factor: float = 0.30,
        gas_rhob_factor: float = 0.15,
    ) -> Dict[str, pd.Series]:
        """
        Calculate all effective porosity methods.

        Args:
            vsh: Vshale series
            nphi_shale: Shale neutron porosity
            rhob_shale: Shale bulk density
            dt_shale: Shale sonic transit time
            rho_matrix: Matrix density
            rho_fluid: Fluid density
            dt_matrix: Matrix sonic transit time
            dt_fluid: Fluid sonic transit time
            gas_correction: Enable gas correction for PHIE
            gas_nphi_factor: Neutron gas correction factor (0.2-0.4 typical)
            gas_rhob_factor: Density gas correction factor (0.1-0.2 typical)

        Returns:
            Dictionary with all PHIE calculations
        """
        if vsh is None:
            vsh = self.results.get("VSH", pd.Series([0] * len(self.data)))

        results = {}
        results["PHIE_D"] = self.calculate_phie_density(
            vsh, rhob_shale, rho_matrix, rho_fluid
        )
        results["PHIE_N"] = self.calculate_phie_neutron(vsh, nphi_shale)
        results["PHIE_S"] = self.calculate_phie_sonic(
            vsh, dt_shale, dt_matrix, dt_fluid
        )
        results["PHIE_DN"] = self.calculate_phie_density_neutron(
            vsh, nphi_shale, rhob_shale, rho_matrix, rho_fluid
        )

        # Gas correction (if enabled)
        if gas_correction:
            results["PHIE_GAS"] = self.calculate_phie_gas_corrected(
                vsh=vsh,
                nphi_shale=nphi_shale,
                rhob_shale=rhob_shale,
                rho_matrix=rho_matrix,
                rho_fluid=rho_fluid,
                gas_nphi_factor=gas_nphi_factor,
                gas_rhob_factor=gas_rhob_factor,
            )
            # Set default PHIE to gas-corrected when enabled
            self.results["PHIE"] = results["PHIE_GAS"]
        else:
            # Set default PHIE to PHIE_DN
            self.results["PHIE"] = results["PHIE_DN"]

        return results

    def calculate_phie_gas_corrected(
        self,
        vsh: pd.Series = None,
        nphi_shale: float = 0.35,
        rhob_shale: float = 2.45,
        rho_matrix: float = 2.65,
        rho_fluid: float = 1.0,
        gas_nphi_factor: float = 0.30,
        gas_rhob_factor: float = 0.15,
    ) -> pd.Series:
        """
        Calculate effective porosity with gas correction (PHIE_GAS).

        In gas zones, the neutron tool reads too low (gas has very low hydrogen index)
        and density tool reads too high (gas has low density). This method applies
        correction factors to compensate for the gas effect.

        Gas Correction Method:
        1. Detect gas zones using neutron-density crossover (PHIN < PHID)
        2. For gas zones:
           - PHIN_corrected = PHIN / (1 - gas_nphi_factor)
           - PHID_corrected = PHID * (1 - gas_rhob_factor)
        3. Calculate PHIE from corrected values with shale correction

        Args:
            vsh: Vshale series
            nphi_shale: Shale neutron porosity response
            rhob_shale: Shale bulk density
            rho_matrix: Matrix density
            rho_fluid: Fluid density
            gas_nphi_factor: Neutron correction factor (0.2-0.4, higher = more correction)
            gas_rhob_factor: Density correction factor (0.1-0.2, higher = more correction)

        Returns:
            Gas-corrected effective porosity series
        """
        phid = self.results.get("PHID", pd.Series([np.nan] * len(self.data)))
        phin = self.results.get("PHIN", pd.Series([np.nan] * len(self.data)))

        if vsh is None:
            vsh = self.results.get("VSH", pd.Series([0] * len(self.data)))

        # Shale porosity from density
        phid_shale = (rho_matrix - rhob_shale) / (rho_matrix - rho_fluid)

        # Detect gas zones: neutron < density (crossover)
        # Gas effect causes PHIN to read low, PHID to read high
        gas_zone = phin < phid

        # Initialize corrected porosities
        phid_corr = phid.copy()
        phin_corr = phin.copy()

        # Apply gas correction only in gas zones
        # Neutron reads low in gas, so we increase it
        # Density reads high in gas (low PHID), so we increase PHID
        phin_corr = np.where(
            gas_zone,
            phin / (1 - gas_nphi_factor),  # Increase neutron in gas zones
            phin,
        )

        phid_corr = np.where(
            gas_zone,
            phid / (1 - gas_rhob_factor),  # Increase density porosity in gas zones
            phid,
        )

        # Apply shale correction
        phid_corr = phid_corr - (vsh * phid_shale)
        phin_corr = phin_corr - (vsh * nphi_shale)

        # Clip negative values
        phid_corr = np.maximum(phid_corr, 0)
        phin_corr = np.maximum(phin_corr, 0)

        # RMS average (same as PHIE_DN)
        phie_gas = np.sqrt((phid_corr**2 + phin_corr**2) / 2)
        phie_gas = np.clip(phie_gas, 0, 0.45)

        # Convert back to Series
        phie_gas = pd.Series(phie_gas, index=self.data.index)

        self.results["PHIE_GAS"] = phie_gas

        # Also store gas zone flag for diagnostics
        self.results["GAS_FLAG"] = pd.Series(
            gas_zone.astype(int), index=self.data.index
        )

        return phie_gas

    # =========================================================================
    # WATER SATURATION CALCULATIONS
    # =========================================================================

    def calculate_sw_archie(
        self,
        rt_curve: str = "RT",
        phie: pd.Series = None,
        rw: float = 0.05,
        a: float = 0.62,
        m: float = 2.15,
        n: float = 2.0,
    ) -> pd.Series:
        """
        Calculate water saturation using Archie equation.

        Sw = ((a * Rw) / (Rt * PHIE^m))^(1/n)

        Args:
            rt_curve: Resistivity curve mnemonic
            phie: Effective porosity series
            rw: Formation water resistivity (ohm.m)
            a: Tortuosity factor (Humble: 0.62)
            m: Cementation exponent (Humble: 2.15)
            n: Saturation exponent (2.0)

        Returns:
            Water saturation series (0-1)
        """
        if rt_curve not in self.data.columns:
            return pd.Series([np.nan] * len(self.data))

        rt = self.data[rt_curve]

        if phie is None:
            phie = self.results.get("PHIE", pd.Series([0.15] * len(self.data)))

        # Avoid division by zero
        phie_safe = np.maximum(phie, 0.001)
        rt_safe = np.maximum(rt, 0.001)

        # Archie equation
        sw = np.power((a * rw) / (rt_safe * np.power(phie_safe, m)), 1 / n)

        # Clip to 0-1 range
        sw = np.clip(sw, 0, 1)

        self.results["SW_ARCHIE"] = sw
        return sw

    def calculate_sw_indonesian(
        self,
        rt_curve: str = "RT",
        phie: pd.Series = None,
        vsh: pd.Series = None,
        rw: float = 0.05,
        rsh: float = 5.0,
        a: float = 0.62,
        m: float = 2.15,
        n: float = 2.0,
    ) -> pd.Series:
        """
        Calculate water saturation using Indonesian equation.

        Suitable for shaly sands.

        1/sqrt(Rt) = sqrt(PHIE^m/(a*Rw)) * Sw^(n/2) + Vsh^(1-Vsh/2)/sqrt(Rsh) * Sw^(n/2)

        Args:
            rt_curve: Resistivity curve mnemonic
            phie: Effective porosity series
            vsh: Vshale series
            rw: Formation water resistivity (ohm.m)
            rsh: Shale resistivity (ohm.m)
            a, m, n: Archie parameters

        Returns:
            Water saturation series (0-1)
        """
        if rt_curve not in self.data.columns:
            return pd.Series([np.nan] * len(self.data))

        rt = self.data[rt_curve]

        if phie is None:
            phie = self.results.get("PHIE", pd.Series([0.15] * len(self.data)))
        if vsh is None:
            vsh = self.results.get("VSH", pd.Series([0.2] * len(self.data)))

        sw_list = []

        for i in range(len(rt)):
            rt_i = rt.iloc[i] if hasattr(rt, "iloc") else rt[i]
            phie_i = phie.iloc[i] if hasattr(phie, "iloc") else phie[i]
            vsh_i = vsh.iloc[i] if hasattr(vsh, "iloc") else vsh[i]

            if np.isnan(rt_i) or np.isnan(phie_i) or phie_i <= 0.001 or rt_i <= 0:
                sw_list.append(np.nan)
                continue

            # Indonesian equation terms
            term1 = np.sqrt(np.power(phie_i, m) / (a * rw))
            term2 = np.power(vsh_i, (1 - vsh_i / 2)) / np.sqrt(rsh)

            lhs = 1 / np.sqrt(rt_i)

            # Solve for Sw iteratively
            def indonesian_func(sw):
                return (term1 * np.power(sw, n / 2) + term2 * np.power(sw, n / 2)) - lhs

            try:
                sw_solved = brentq(indonesian_func, 0.001, 1.5)
                sw_solved = np.clip(sw_solved, 0, 1)
            except:
                # Fallback to Archie
                sw_solved = np.power((a * rw) / (rt_i * np.power(phie_i, m)), 1 / n)
                sw_solved = np.clip(sw_solved, 0, 1)

            sw_list.append(sw_solved)

        sw = pd.Series(sw_list, index=self.data.index)
        self.results["SW_INDO"] = sw
        return sw

    def calculate_sw_simandoux(
        self,
        rt_curve: str = "RT",
        phie: pd.Series = None,
        vsh: pd.Series = None,
        rw: float = 0.05,
        rsh: float = 5.0,
        a: float = 0.62,
        m: float = 2.15,
        n: float = 2.0,
    ) -> pd.Series:
        """
        Calculate water saturation using Simandoux equation.

        1/Rt = (PHIE^m * Sw^n)/(a*Rw) + (Vsh * Sw)/Rsh

        Solved as quadratic: A*Sw^2 + B*Sw - C = 0

        Args:
            rt_curve: Resistivity curve mnemonic
            phie: Effective porosity series
            vsh: Vshale series
            rw: Formation water resistivity (ohm.m)
            rsh: Shale resistivity (ohm.m)
            a, m, n: Archie parameters

        Returns:
            Water saturation series (0-1)
        """
        if rt_curve not in self.data.columns:
            return pd.Series([np.nan] * len(self.data))

        rt = self.data[rt_curve]

        if phie is None:
            phie = self.results.get("PHIE", pd.Series([0.15] * len(self.data)))
        if vsh is None:
            vsh = self.results.get("VSH", pd.Series([0.2] * len(self.data)))

        # Simandoux with n=2 is a quadratic in Sw
        # A = PHIE^m / (a*Rw)
        # B = Vsh / Rsh
        # C = 1 / Rt
        # A*Sw^2 + B*Sw - C = 0

        phie_safe = np.maximum(phie, 0.001)
        rt_safe = np.maximum(rt, 0.001)

        A = np.power(phie_safe, m) / (a * rw)
        B = vsh / rsh
        C = 1 / rt_safe

        # Quadratic formula: Sw = (-B + sqrt(B^2 + 4AC)) / (2A)
        discriminant = B**2 + 4 * A * C
        discriminant = np.maximum(discriminant, 0)  # Ensure non-negative

        sw = (-B + np.sqrt(discriminant)) / (2 * A)

        # For n != 2, need iterative solution
        # Clip to 0-1 range
        sw = np.clip(sw, 0, 1)

        self.results["SW_SIMAN"] = sw
        return sw

    def calculate_sw_waxman_smits(
        self,
        rt_curve: str = "RT",
        phie: pd.Series = None,
        rw: float = 0.05,
        a: float = 0.62,
        m: float = 2.15,
        n: float = 2.0,
        qv: float = 0.2,
        B: float = 1.0,
    ) -> pd.Series:
        """
        Calculate water saturation using Waxman-Smits equation.

        Ct = (1/F*) * (Sw^n*) * (Cw + (B*Qv) / Sw)

        Where:
        - Ct = 1/Rt (Total conductivity)
        - F* = a / PHIE^m
        - Cw = 1/Rw
        - Qv = cation exchange capacity per unit pore volume
        - B = equivalent conductance of clay exchange cations

        Args:
            rt_curve: Resistivity curve mnemonic
            phie: Effective porosity series
            rw: Formation water resistivity (ohm.m)
            a, m, n: Archie parameters
            qv: Qv parameter (meq/ml)
            B: B parameter (mho cm^2/meq)

        Returns:
            Water saturation series (0-1)
        """
        if rt_curve not in self.data.columns:
            return pd.Series([np.nan] * len(self.data))

        rt = self.data[rt_curve]

        if phie is None:
            phie = self.results.get("PHIE", pd.Series([0.15] * len(self.data)))

        sw_list = []

        # Pre-calculate constants where possible
        cw = 1.0 / rw if rw > 0 else 0

        for i in range(len(rt)):
            rt_i = rt.iloc[i] if hasattr(rt, "iloc") else rt[i]
            phie_i = phie.iloc[i] if hasattr(phie, "iloc") else phie[i]

            if np.isnan(rt_i) or np.isnan(phie_i) or phie_i <= 0.001 or rt_i <= 0:
                sw_list.append(np.nan)
                continue

            # Formation factor F*
            f_star = a / np.power(phie_i, m)
            ct = 1.0 / rt_i

            # Function to solve: f(Sw) = Model_Ct - Actual_Ct = 0
            # Model_Ct = (1/F*) * Sw^n * (Cw + B*Qv/Sw)
            #          = (1/F*) * (Cw * Sw^n + B*Qv * Sw^(n-1))

            def ws_func(sw):
                # Guard against small Sw
                sw = max(sw, 1e-6)
                term1 = cw * np.power(sw, n)
                term2 = (B * qv) * np.power(sw, n - 1)
                model_ct = (1.0 / f_star) * (term1 + term2)
                return model_ct - ct

            try:
                # Root finding
                if ws_func(0.001) * ws_func(1.0) < 0:
                    sw_solved = brentq(ws_func, 0.001, 1.0)
                    sw_solved = np.clip(sw_solved, 0, 1)
                else:
                    # Fallback if no root in range (rare)
                    sw_solved = 1.0 if ws_func(1.0) < 0 else 0.0
            except:
                sw_solved = np.nan

            sw_list.append(sw_solved)

        sw = pd.Series(sw_list, index=self.data.index)
        self.results["SW_WS"] = sw
        return sw

    def calculate_sw_dual_water(
        self,
        rt_curve: str = "RT",
        phie: pd.Series = None,
        rw: float = 0.05,
        a: float = 0.62,
        m: float = 2.15,
        n: float = 2.0,
        swb: float = 0.1,
        rwb: float = 0.2,
    ) -> pd.Series:
        """
        Calculate water saturation using Dual-Water model.

        Ct = (1/Ft) * [ (Swt - Swb) * Cw + Swb * Cwb ] / Swt * Swt^n
           = (1/Ft) * Swt^n * [ (Cwf * (Swt - Swb) / Swt) + (Cwb * Swb / Swt) ]
           Simplify:
           Ct = (Swt^n / Ft) * [ Cw + (Cwb - Cw) * (Swb / Swt) ]

        Where:
        - Swt = Total water saturation (what we solve for)
        - Swb = Bound water saturation (input)

        Args:
            rt_curve: Resistivity curve mnemonic
            phie: Total porosity (Note: DW uses PHIT typically, but we use PHIE passed in
                  if we assume params are tuned for it, or user passes PHIT)
            rw: Free water resistivity
            a, m, n: Archie parameters
            swb: Bound water saturation fraction
            rwb: Bound water resistivity

        Returns:
            Water saturation series (0-1)
        """
        if rt_curve not in self.data.columns:
            return pd.Series([np.nan] * len(self.data))

        rt = self.data[rt_curve]

        # Dual water ideally uses PHIT, but we operate with whatever 'phie' is passed.
        # If the user selected DW, they should ideally check if they want to pass PHIT.
        # For consistency with other methods signature, we accept 'phie'.
        if phie is None:
            phie = self.results.get(
                "PHIT", self.results.get("PHIE", pd.Series([0.15] * len(self.data)))
            )

        sw_list = []

        cw = 1.0 / rw if rw > 0 else 0
        cwb = 1.0 / rwb if rwb > 0 else 0

        for i in range(len(rt)):
            rt_i = rt.iloc[i] if hasattr(rt, "iloc") else rt[i]
            phi_i = phie.iloc[i] if hasattr(phie, "iloc") else phie[i]

            if np.isnan(rt_i) or np.isnan(phi_i) or phi_i <= 0.001 or rt_i <= 0:
                sw_list.append(np.nan)
                continue

            # Formation factor based on total porosity (usually)
            f_t = a / np.power(phi_i, m)
            ct_measured = 1.0 / rt_i

            # f(Swt) = Model_Ct - Measured_Ct
            def dw_func(swt):
                # Swt must be >= Swb ideally, but for numerical stability we allow [Swb, 1]
                # Swf = Swt - Swb. If Swt < Swb, logic breaks physically.
                swt = max(swt, swb + 1e-4)  # Ensure slightly above Swb

                # Conductivity eq:
                # Ct = (Swt^n / Ft) * (Cw + (Cwb - Cw) * Swb / Swt)
                term = cw + (cwb - cw) * (swb / swt)
                model_ct = (np.power(swt, n) / f_t) * term
                return model_ct - ct_measured

            try:
                # Root search in [Swb, 1.0]
                lower_bound = min(max(swb + 0.001, 0.001), 0.99)

                val_low = dw_func(lower_bound)
                val_high = dw_func(1.0)

                if val_low * val_high < 0:
                    sw_solved = brentq(dw_func, lower_bound, 1.0)
                else:
                    # If measured cond is very high, Sw -> 1
                    if abs(val_high) < abs(val_low):
                        sw_solved = 1.0
                    else:
                        # If measured cond is very low, Sw -> Swb
                        sw_solved = variable_swb = swb

                sw_solved = np.clip(sw_solved, 0, 1)
            except:
                sw_solved = np.nan

            sw_list.append(sw_solved)

        sw = pd.Series(sw_list, index=self.data.index)
        self.results["SW_DW"] = sw
        return sw

    # =========================================================================
    # IRREDUCIBLE WATER SATURATION (Swirr) CALCULATIONS
    # =========================================================================

    def calculate_swirr_buckles(
        self, phie: pd.Series = None, k_buckles: float = 0.02
    ) -> pd.Series:
        """
        Calculate Swirr using Buckles number approach.

        Swirr = K_buckles / PHIE

        Args:
            phie: Effective porosity series
            k_buckles: Buckles number (0.01-0.04 for sandstone, higher for carbonate)

        Returns:
            Swirr series
        """
        if phie is None:
            phie = self.results.get("PHIE", pd.Series([0.15] * len(self.data)))

        phie_safe = np.maximum(phie, 0.01)  # Avoid division by very small numbers
        swirr = k_buckles / phie_safe

        # Bound to reasonable range
        swirr = np.clip(swirr, 0.05, 0.5)

        self.results["SWIRR_BUCKLES"] = swirr
        return swirr

    def calculate_swirr_clean_zone(
        self,
        sw: pd.Series = None,
        vsh: pd.Series = None,
        vsh_threshold: float = 0.2,
        sw_threshold: float = 0.5,
    ) -> pd.Series:
        """
        Calculate Swirr from clean zone approach.

        Identifies clean zones (low Vsh, low Sw) and uses minimum Sw as Swirr.

        Args:
            sw: Water saturation series
            vsh: Vshale series
            vsh_threshold: Maximum Vsh for clean zone
            sw_threshold: Maximum Sw for hydrocarbon zone

        Returns:
            Swirr series (constant value based on clean zone minimum)
        """
        if sw is None:
            sw = self.results.get(
                "SW_INDO",
                self.results.get("SW_ARCHIE", pd.Series([0.5] * len(self.data))),
            )
        if vsh is None:
            vsh = self.results.get("VSH", pd.Series([0.3] * len(self.data)))

        # Identify clean hydrocarbon zones
        clean_hc_zone = (vsh < vsh_threshold) & (sw < sw_threshold)

        if clean_hc_zone.sum() > 0:
            # Minimum Sw in clean HC zones = Swirr
            swirr_value = float(sw[clean_hc_zone].min())
        else:
            # Fallback: use P5 of all Sw as estimate
            swirr_value = float(np.percentile(sw.dropna(), 5))

        # Bound to reasonable range
        swirr_value = np.clip(swirr_value, 0.05, 0.5)

        swirr = pd.Series([swirr_value] * len(self.data), index=self.data.index)

        self.results["SWIRR_CLEANZONE"] = swirr
        return swirr

    def calculate_swirr_statistical(
        self, sw: pd.Series = None, vsh: pd.Series = None, percentile: float = 5
    ) -> pd.Series:
        """
        Calculate Swirr using statistical approach.

        Uses percentile of Sw in clean zones as Swirr estimate.

        Args:
            sw: Water saturation series
            vsh: Vshale series
            percentile: Percentile to use (default P5)

        Returns:
            Swirr series
        """
        if sw is None:
            sw = self.results.get(
                "SW_INDO",
                self.results.get("SW_ARCHIE", pd.Series([0.5] * len(self.data))),
            )
        if vsh is None:
            vsh = self.results.get("VSH", pd.Series([0.3] * len(self.data)))

        # Use Sw in relatively clean zones
        clean_mask = vsh < 0.4

        if clean_mask.sum() > 0:
            sw_clean = sw[clean_mask].dropna()
            if len(sw_clean) > 0:
                swirr_value = float(np.percentile(sw_clean, percentile))
            else:
                swirr_value = 0.2
        else:
            swirr_value = float(np.percentile(sw.dropna(), percentile))

        # Bound to reasonable range
        swirr_value = np.clip(swirr_value, 0.05, 0.5)

        swirr = pd.Series([swirr_value] * len(self.data), index=self.data.index)

        self.results["SWIRR_STAT"] = swirr
        return swirr

    def calculate_swirr_hierarchical(
        self,
        phie: pd.Series = None,
        sw: pd.Series = None,
        vsh: pd.Series = None,
        k_buckles: float = 0.02,
        vsh_clean_threshold: float = 0.10,
        sw_hc_threshold: float = 0.50,
    ) -> Tuple[pd.Series, Dict]:
        """
        Calculate Swirr using hierarchical workflow (recommended without core data).

        Workflow:
        1. Find Clean Hydrocarbon Zone: If clean zone (Vsh < 10%) with low Sw exists,
           use P10 of Sw in that zone as Swirr
        2. Buckles Fallback: If no clean HC zone, use Buckles number to estimate
           Swirr = k_buckles / PHIE
        3. Statistical Bound: Limit Swirr to 0.05-0.50 and never exceed Sw_observed

        Args:
            phie: Effective porosity series
            sw: Water saturation series
            vsh: Vshale series
            k_buckles: Buckles number (default 0.02 for sandstone)
            vsh_clean_threshold: Vsh threshold for identifying clean zone (default 0.10)
            sw_hc_threshold: Sw threshold for identifying hydrocarbon zone (default 0.50)

        Returns:
            Tuple of (Swirr series, info dictionary with method used)
        """
        if phie is None:
            phie = self.results.get("PHIE", pd.Series([0.15] * len(self.data)))
        if sw is None:
            sw = self.results.get(
                "SW_INDO",
                self.results.get("SW_ARCHIE", pd.Series([0.5] * len(self.data))),
            )
        if vsh is None:
            vsh = self.results.get("VSH", pd.Series([0.3] * len(self.data)))

        info = {
            "method": "buckles_fallback",
            "clean_hc_zones_found": 0,
            "swirr_value": None,
            "warning": None,
        }

        # Step 1: Try to find Clean Hydrocarbon Zone (Vsh < 10%, Sw < 50%)
        clean_hc_zone = (
            (vsh < vsh_clean_threshold) & (sw < sw_hc_threshold) & (phie > 0.05)
        )
        clean_hc_count = clean_hc_zone.sum()
        info["clean_hc_zones_found"] = int(clean_hc_count)

        if clean_hc_count > 10:  # Need sufficient data points
            # Use P10 of Sw in clean HC zone as Swirr
            sw_clean_hc = sw[clean_hc_zone].dropna()
            swirr_from_clean = float(np.percentile(sw_clean_hc, 10))

            # Create Swirr profile (constant for simplicity)
            swirr = pd.Series(
                [swirr_from_clean] * len(self.data), index=self.data.index
            )
            info["method"] = "clean_hc_zone"
            info["swirr_value"] = swirr_from_clean

        else:
            # Step 2: Buckles Fallback - calculate profile from PHIE
            phie_safe = np.maximum(phie, 0.01)
            swirr = k_buckles / phie_safe
            info["method"] = "buckles_fallback"
            info["swirr_value"] = float(swirr.mean())

        # Step 3: Statistical Bounds
        # Swirr should be >= 0.05 (physically reasonable)
        swirr = np.maximum(swirr, 0.05)

        # Swirr should never exceed observed Sw (illogical)
        swirr = np.minimum(swirr, sw)

        # Upper bound at 0.60 (very shaley)
        swirr = np.minimum(swirr, 0.60)

        # Check for warnings
        if (swirr < 0.05).any():
            info["warning"] = "Some Swirr values below 0.05 (clipped)"
        if (swirr > sw).any():
            info["warning"] = "Some Swirr values exceeded Sw (clipped to Sw)"

        self.results["SWIRR"] = swirr
        self.results["SWIRR_METHOD"] = info["method"]

        return swirr, info

    def calculate_all_swirr(
        self,
        phie: pd.Series = None,
        sw: pd.Series = None,
        vsh: pd.Series = None,
        k_buckles: float = 0.02,
        vsh_threshold: float = 0.2,
        methods: list = None,
    ) -> Dict[str, pd.Series]:
        """
        Calculate Swirr using multiple methods for comparison.

        Args:
            phie: Effective porosity series
            sw: Water saturation series
            vsh: Vshale series
            k_buckles: Buckles number for Buckles method
            vsh_threshold: Vsh threshold for clean zone method
            methods: List of methods. Options: 'hierarchical', 'buckles', 'clean_zone', 'statistical'

        Returns:
            Dictionary with Swirr for each method
        """
        if methods is None:
            methods = ["hierarchical"]  # Default to hierarchical

        results = {}

        if "hierarchical" in methods:
            swirr, info = self.calculate_swirr_hierarchical(phie, sw, vsh, k_buckles)
            results["SWIRR"] = swirr
            results["info"] = info

        if "buckles" in methods:
            results["SWIRR_BUCKLES"] = self.calculate_swirr_buckles(phie, k_buckles)

        if "clean_zone" in methods:
            results["SWIRR_CLEANZONE"] = self.calculate_swirr_clean_zone(
                sw, vsh, vsh_threshold
            )

        if "statistical" in methods:
            results["SWIRR_STAT"] = self.calculate_swirr_statistical(sw, vsh)

        # Default SWIRR is from hierarchical if available
        if "SWIRR" not in self.results:
            if "SWIRR_BUCKLES" in results:
                self.results["SWIRR"] = results["SWIRR_BUCKLES"]

        return results

    # =========================================================================
    # PERMEABILITY CALCULATIONS
    # =========================================================================

    def calculate_permeability_timur(
        self, phie: pd.Series = None, swi: pd.Series = None
    ) -> pd.Series:
        """
        Calculate permeability using Timur equation.

        K = 8581 * (PHIE^4.4) / (Swi^2)

        Args:
            phie: Effective porosity series
            swi: Irreducible water saturation series

        Returns:
            Permeability series (mD)
        """
        if phie is None:
            phie = self.results.get("PHIE", pd.Series([0.15] * len(self.data)))

        # Estimate Swi if not provided
        if swi is None:
            # Use Sw as proxy, assuming hydrocarbon zones are at Swi
            sw = self.results.get("SW_ARCHIE", None)
            if sw is not None:
                # Minimum Sw in clean zones
                vsh = self.results.get("VSH", pd.Series([0] * len(self.data)))
                swi = sw.copy()
                # In clean zones with hydrocarbons, Sw ~ Swi
                swi = np.clip(swi, 0.05, 0.9)
            else:
                swi = pd.Series([0.2] * len(self.data))

        phie_safe = np.maximum(phie, 0.001)
        swi_safe = np.maximum(swi, 0.05)

        # Timur equation
        k = 8581 * np.power(phie_safe, 4.4) / np.power(swi_safe, 2)

        # Bound to reasonable range
        k = np.clip(k, 0.001, 50000)

        self.results["PERM_TIMUR"] = k
        return k

    def calculate_permeability_wyllie_rose(
        self,
        phie: pd.Series = None,
        swi: pd.Series = None,
        C: float = 100,
        P: float = 4.5,
        Q: float = 2.0,
    ) -> pd.Series:
        """
        Calculate permeability using Wyllie-Rose equation.

        K = C * (PHIE^P) / (Swi^Q)

        Args:
            phie: Effective porosity series
            swi: Irreducible water saturation series
            C, P, Q: Wyllie-Rose coefficients

        Returns:
            Permeability series (mD)
        """
        if phie is None:
            phie = self.results.get("PHIE", pd.Series([0.15] * len(self.data)))

        if swi is None:
            sw = self.results.get("SW_ARCHIE", None)
            if sw is not None:
                swi = np.clip(sw, 0.05, 0.9)
            else:
                swi = pd.Series([0.2] * len(self.data))

        phie_safe = np.maximum(phie, 0.001)
        swi_safe = np.maximum(swi, 0.05)

        # Wyllie-Rose equation
        k = C * np.power(phie_safe, P) / np.power(swi_safe, Q)

        # Bound to reasonable range
        k = np.clip(k, 0.001, 50000)

        self.results["PERM_WR"] = k
        return k

    def classify_flow_units(self, perm: pd.Series = None) -> pd.Series:
        """
        Classify permeability into Flow Unit Classes.

        Classification:
        - Tight: < 1 mD
        - Poor: 1-10 mD
        - Fair: 10-100 mD
        - Good: 100-1000 mD
        - Excellent: > 1000 mD

        Args:
            perm: Permeability series (mD)

        Returns:
            Series with flow unit classification
        """
        if perm is None:
            perm = self.results.get(
                "PERM_TIMUR",
                self.results.get("PERM_WR", pd.Series([10] * len(self.data))),
            )

        def classify(k):
            if np.isnan(k):
                return "Unknown"
            elif k < 1:
                return "Tight"
            elif k < 10:
                return "Poor"
            elif k < 100:
                return "Fair"
            elif k < 1000:
                return "Good"
            else:
                return "Excellent"

        flow_unit = perm.apply(classify)
        self.results["FLOW_UNIT"] = flow_unit
        return flow_unit

    def get_permeability_quality_flags(
        self, perm: pd.Series = None, swirr: pd.Series = None, phie: pd.Series = None
    ) -> Dict:
        """
        Generate quality flags/warnings for permeability calculation.

        Args:
            perm: Permeability series
            swirr: Swirr series used in calculation
            phie: PHIE series used in calculation

        Returns:
            Dictionary with flags and statistics
        """
        if perm is None:
            perm = self.results.get("PERM_TIMUR", pd.Series())
        if swirr is None:
            swirr = self.results.get("SWIRR", pd.Series())
        if phie is None:
            phie = self.results.get("PHIE", pd.Series())

        flags = {
            "warnings": [],
            "info": [],
            "extreme_high_k": 0,
            "extreme_low_k": 0,
            "low_swirr_count": 0,
            "quality_score": "Good",
        }

        if len(perm) == 0:
            flags["warnings"].append("No permeability data calculated")
            return flags

        # Check for extreme values
        extreme_high = (perm > 10000).sum()  # > 10 Darcy
        extreme_low = (perm < 0.01).sum()  # < 0.01 mD
        flags["extreme_high_k"] = int(extreme_high)
        flags["extreme_low_k"] = int(extreme_low)

        if extreme_high > 0:
            flags["warnings"].append(
                f"{extreme_high} points with k > 10,000 mD (unrealistic)"
            )

        if extreme_low > 0:
            flags["info"].append(f"{extreme_low} points with k < 0.01 mD (tight rock)")

        # Check Swirr quality
        if len(swirr) > 0:
            low_swirr = (swirr < 0.08).sum()
            flags["low_swirr_count"] = int(low_swirr)

            if low_swirr > len(swirr) * 0.1:  # > 10% have very low Swirr
                flags["warnings"].append(
                    f"{low_swirr} points with Swirr < 0.08 (may cause overestimated k)"
                )

        # Check PHIE quality
        if len(phie) > 0:
            low_phie = (phie < 0.02).sum()
            if low_phie > len(phie) * 0.3:  # > 30% have very low porosity
                flags["info"].append(
                    f"{low_phie} points with PHIE < 0.02 (tight formation)"
                )

        # Overall quality assessment
        if len(flags["warnings"]) > 0:
            flags["quality_score"] = "Warning"
        elif extreme_high > 0 or extreme_low > 0:
            flags["quality_score"] = "Review"
        else:
            flags["quality_score"] = "Good"

        # Flow unit distribution
        if "FLOW_UNIT" in self.results:
            flow_unit = self.results["FLOW_UNIT"]
            flags["flow_unit_distribution"] = flow_unit.value_counts().to_dict()

        return flags

    # =========================================================================
    # NET PAY CALCULATIONS
    # =========================================================================

    def calculate_net_pay(
        self,
        vsh: pd.Series = None,
        phie: pd.Series = None,
        sw: pd.Series = None,
        vsh_cutoff: float = 0.4,
        phi_cutoff: float = 0.08,
        sw_cutoff: float = 0.6,
        step: float = None,
    ) -> Dict[str, float]:
        """
        Calculate Gross Sand, Net Reservoir, and Net Pay thicknesses.

        Args:
            vsh: Vshale series
            phie: Effective porosity series
            sw: Water saturation series
            vsh_cutoff: Vshale cutoff for gross sand
            phi_cutoff: Porosity cutoff for net reservoir
            sw_cutoff: Sw cutoff for net pay
            step: Depth step (auto-detected if None)

        Returns:
            Dictionary with thickness values
        """
        if vsh is None:
            vsh = self.results.get("VSH", pd.Series([0] * len(self.data)))
        if phie is None:
            phie = self.results.get("PHIE", pd.Series([0] * len(self.data)))
        if sw is None:
            sw = self.results.get(
                "SW_ARCHIE",
                self.results.get(
                    "SW_INDO",
                    self.results.get("SW_SIMAN", pd.Series([1] * len(self.data))),
                ),
            )

        # Determine step
        if step is None:
            if "DEPTH" in self.data.columns:
                depths = self.data["DEPTH"].dropna()
                if len(depths) > 1:
                    step = abs(np.median(np.diff(depths)))
                else:
                    step = 0.1
            else:
                step = 0.1

        # Create flags
        gross_sand_flag = vsh < vsh_cutoff
        net_res_flag = gross_sand_flag & (phie > phi_cutoff)
        net_pay_flag = net_res_flag & (sw < sw_cutoff)

        # Store flags
        self.results["GROSS_SAND_FLAG"] = gross_sand_flag.astype(int)
        self.results["NET_RES_FLAG"] = net_res_flag.astype(int)
        self.results["NET_PAY_FLAG"] = net_pay_flag.astype(int)

        # Calculate thicknesses
        gross_sand = gross_sand_flag.sum() * step
        net_reservoir = net_res_flag.sum() * step
        net_pay = net_pay_flag.sum() * step

        # Calculate average properties in net pay
        if net_pay_flag.sum() > 0:
            avg_phi = float(phie[net_pay_flag].mean())
            avg_sw = float(sw[net_pay_flag].mean())
            avg_vsh = float(vsh[net_pay_flag].mean())
        else:
            avg_phi = avg_sw = avg_vsh = np.nan

        # N/G ratios
        ng_res = net_reservoir / gross_sand if gross_sand > 0 else 0
        ng_pay = net_pay / gross_sand if gross_sand > 0 else 0

        return {
            "gross_sand": float(gross_sand),
            "net_reservoir": float(net_reservoir),
            "net_pay": float(net_pay),
            "ng_reservoir": float(ng_res),
            "ng_pay": float(ng_pay),
            "avg_phie_pay": float(avg_phi),
            "avg_sw_pay": float(avg_sw),
            "avg_vsh_pay": float(avg_vsh),
        }

    def calculate_hcpv(
        self,
        phie: pd.Series = None,
        sw: pd.Series = None,
        depth: pd.Series = None,
        net_res_flag: pd.Series = None,
        net_pay_flag: pd.Series = None,
    ) -> Dict[str, pd.Series]:
        """
        Calculate Hydrocarbon Pore Volume (HCPV).

        HCPV represents the volumetric fraction of hydrocarbons per unit depth.

        Calculation Steps:
        1. HCPV_frac = PHIE * (1 - Sw)        # Hydrocarbon fraction per depth
        2. dz = depth[i] - depth[i-1]         # Depth increment (feet)
        3. dHCPV = HCPV_frac * dz             # Incremental HCPV
        4. HCPV_cum = cumsum(dHCPV)           # Cumulative HCPV
        5. Net gating:
           - Apply NET_RES_FLAG to get Net Reservoir HCPV
           - Apply NET_PAY_FLAG to get Net Pay HCPV

        Args:
            phie: Effective porosity (v/v)
            sw: Water saturation (v/v) - primary Sw
            depth: Depth in feet
            net_res_flag: Net reservoir flag (0 or 1)
            net_pay_flag: Net pay flag (0 or 1)

        Returns:
            Dict with all HCPV curves:
            - HCPV_FRAC: Hydrocarbon fraction = PHIE * (1-Sw)
            - dHCPV: Incremental HCPV (gross)
            - HCPV_CUM: Cumulative HCPV (gross)
            - HCPV_NET_RES: HCPV fraction gated by net reservoir
            - dHCPV_NET_RES: Incremental HCPV for net reservoir
            - HCPV_CUM_NET_RES: Cumulative HCPV for net reservoir
            - HCPV_NET_PAY: HCPV fraction gated by net pay
            - dHCPV_NET_PAY: Incremental HCPV for net pay
            - HCPV_CUM_NET_PAY: Cumulative HCPV for net pay
        """
        # Get data from results if not provided
        if phie is None:
            phie = self.results.get("PHIE", pd.Series([0.15] * len(self.data)))
        if sw is None:
            sw = self.results.get("SW", pd.Series([0.5] * len(self.data)))
        if depth is None:
            depth = self.data.get("DEPTH", pd.Series(range(len(self.data))))
        if net_res_flag is None:
            net_res_flag = self.results.get(
                "NET_RES_FLAG", pd.Series([1] * len(self.data))
            )
        if net_pay_flag is None:
            net_pay_flag = self.results.get(
                "NET_PAY_FLAG", pd.Series([1] * len(self.data))
            )

        # Ensure proper types
        phie = pd.Series(phie).reset_index(drop=True)
        sw = pd.Series(sw).reset_index(drop=True)
        depth = pd.Series(depth).reset_index(drop=True)
        net_res_flag = pd.Series(net_res_flag).reset_index(drop=True)
        net_pay_flag = pd.Series(net_pay_flag).reset_index(drop=True)

        # Step 1: Calculate HCPV fraction (hydrocarbon fraction per depth)
        hcpv_frac = phie * (1 - sw)
        hcpv_frac = np.clip(hcpv_frac, 0, 1)  # Bound to 0-1

        # Step 2: Calculate depth increment (dz) in feet
        dz = np.abs(depth.diff())
        dz.iloc[0] = dz.iloc[1] if len(dz) > 1 else 0  # Handle first row

        # Step 3: Incremental HCPV (gross)
        d_hcpv = hcpv_frac * dz
        d_hcpv = d_hcpv.fillna(0)

        # Step 4: Cumulative HCPV (gross)
        hcpv_cum = d_hcpv.cumsum()

        # Step 5: Net Gating
        # Net Reservoir
        hcpv_net_res = hcpv_frac * net_res_flag
        d_hcpv_net_res = hcpv_net_res * dz
        d_hcpv_net_res = d_hcpv_net_res.fillna(0)
        hcpv_cum_net_res = d_hcpv_net_res.cumsum()

        # Net Pay
        hcpv_net_pay = hcpv_frac * net_pay_flag
        d_hcpv_net_pay = hcpv_net_pay * dz
        d_hcpv_net_pay = d_hcpv_net_pay.fillna(0)
        hcpv_cum_net_pay = d_hcpv_net_pay.cumsum()

        # Store in results
        self.results["HCPV_FRAC"] = hcpv_frac
        self.results["dHCPV"] = d_hcpv
        self.results["HCPV_CUM"] = hcpv_cum
        self.results["HCPV_NET_RES"] = hcpv_net_res
        self.results["dHCPV_NET_RES"] = d_hcpv_net_res
        self.results["HCPV_CUM_NET_RES"] = hcpv_cum_net_res
        self.results["HCPV_NET_PAY"] = hcpv_net_pay
        self.results["dHCPV_NET_PAY"] = d_hcpv_net_pay
        self.results["HCPV_CUM_NET_PAY"] = hcpv_cum_net_pay

        return {
            "HCPV_FRAC": hcpv_frac,
            "dHCPV": d_hcpv,
            "HCPV_CUM": hcpv_cum,
            "HCPV_NET_RES": hcpv_net_res,
            "dHCPV_NET_RES": d_hcpv_net_res,
            "HCPV_CUM_NET_RES": hcpv_cum_net_res,
            "HCPV_NET_PAY": hcpv_net_pay,
            "dHCPV_NET_PAY": d_hcpv_net_pay,
            "HCPV_CUM_NET_PAY": hcpv_cum_net_pay,
        }

    def get_results(self) -> pd.DataFrame:
        """Get all calculated results as a DataFrame."""
        return self.results

    def export_results(self, include_original: bool = True) -> pd.DataFrame:
        """
        Export results with or without original data.

        Args:
            include_original: Whether to include original log data

        Returns:
            DataFrame with results
        """
        if include_original:
            return pd.concat(
                [self.data, self.results.drop(columns=["DEPTH"], errors="ignore")],
                axis=1,
            )
        return self.results


def run_full_analysis(
    data: pd.DataFrame, curve_mapping: Dict[str, str], params: Dict[str, float]
) -> Tuple[pd.DataFrame, Dict]:
    """
    Run complete petrophysics analysis workflow.

    Args:
        data: Input log data
        curve_mapping: Mapping of curve types to mnemonics
        params: Calculation parameters (Rw, Rsh, matrix props, etc.)

    Returns:
        Tuple of (results DataFrame, summary dictionary)
    """
    calc = PetrophysicsCalculator(data)

    # Get curves
    gr_curve = curve_mapping.get("GR", "GR")
    rhob_curve = curve_mapping.get("RHOB", "RHOB")
    nphi_curve = curve_mapping.get("NPHI", "NPHI")
    dt_curve = curve_mapping.get("DT", "DT")
    rt_curve = curve_mapping.get("RT", "RT")

    # Parameters
    gr_min = params.get("gr_min")
    gr_max = params.get("gr_max")
    rho_matrix = params.get("rho_matrix", 2.65)
    rho_fluid = params.get("rho_fluid", 1.0)
    dt_matrix = params.get("dt_matrix", 55.5)
    dt_fluid = params.get("dt_fluid", 189.0)
    rw = params.get("rw", 0.05)
    rsh = params.get("rsh", 5.0)
    a = params.get("a", 0.62)
    m = params.get("m", 2.15)
    n = params.get("n", 2.0)

    # Calculate Vshale
    vsh = calc.calculate_vshale_linear(gr_curve, gr_min, gr_max)

    # Calculate porosities
    phid = calc.calculate_porosity_density(rhob_curve, rho_matrix, rho_fluid)
    phin = calc.calculate_porosity_neutron(nphi_curve)
    phis = calc.calculate_porosity_sonic(dt_curve, dt_matrix, dt_fluid)

    # Total porosity (N-D crossplot)
    phit = calc.calculate_phit_neutron_density(phid, phin)

    # Effective porosity
    phie = calc.calculate_phie(phit, vsh)

    # Water saturation (all methods)
    sw_archie = calc.calculate_sw_archie(rt_curve, phie, rw, a, m, n)
    sw_indo = calc.calculate_sw_indonesian(rt_curve, phie, vsh, rw, rsh, a, m, n)
    sw_siman = calc.calculate_sw_simandoux(rt_curve, phie, vsh, rw, rsh, a, m, n)

    # Permeability
    perm_timur = calc.calculate_permeability_timur(phie)

    C = params.get("C", 100)
    P = params.get("P", 4.5)
    Q = params.get("Q", 2.0)
    perm_wr = calc.calculate_permeability_wyllie_rose(phie, None, C, P, Q)

    # Net pay (using Indonesian Sw as default)
    vsh_cutoff = params.get("vsh_cutoff", 0.4)
    phi_cutoff = params.get("phi_cutoff", 0.08)
    sw_cutoff = params.get("sw_cutoff", 0.6)

    summary = calc.calculate_net_pay(
        vsh, phie, sw_indo, vsh_cutoff, phi_cutoff, sw_cutoff
    )

    return calc.export_results(), summary
