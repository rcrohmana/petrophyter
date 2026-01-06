"""
Data Quality Control Module for Petrophyter
Provides QC statistics and data validation functions
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class CurveQCResult:
    """Quality control result for a single curve."""
    mnemonic: str
    total_points: int
    valid_points: int
    null_count: int
    null_percentage: float
    min_value: float
    max_value: float
    mean_value: float
    std_value: float
    median_value: float
    p5_value: float
    p95_value: float
    outlier_count: int
    quality_score: float  # 0-100


@dataclass
class DataQCReport:
    """Complete QC report for all curves."""
    well_name: str
    depth_range: Tuple[float, float]
    total_depth: float
    step: float
    total_points: int
    curves_available: List[str]
    curves_required: List[str]
    curves_missing: List[str]
    curve_results: Dict[str, CurveQCResult]
    overall_quality_score: float


class QCModule:
    """
    Quality Control module for analyzing LAS data quality.
    """
    
    # Required curves for petrophysics calculations
    REQUIRED_CURVES = ['GR', 'RHOB', 'NPHI']
    OPTIONAL_CURVES = ['DT', 'RT', 'RS', 'SP', 'CALI', 'DRHO', 'PEF']
    
    # Reasonable ranges for common curves
    CURVE_RANGES = {
        'GR': (0, 250),
        'RHOB': (1.8, 3.0),
        'NPHI': (-0.15, 0.60),
        'DT': (40, 180),
        'RT': (0.1, 10000),
        'RS': (0.1, 10000),
        'SP': (-200, 100),
        'CALI': (4, 20),
        'PEF': (1, 10),
    }
    
    def __init__(self, data: pd.DataFrame, well_name: str = "Unknown"):
        """
        Initialize QC module with data.
        
        Args:
            data: DataFrame containing log data
            well_name: Name of the well
        """
        self.data = data.copy()
        self.well_name = well_name
        self.curve_results = {}
        
    def run_qc(self, curve_mapping: Dict[str, str] = None) -> DataQCReport:
        """
        Run complete QC analysis on the data.
        
        Args:
            curve_mapping: Dictionary mapping standard names to actual curve mnemonics
            
        Returns:
            DataQCReport object with complete QC results
        """
        if curve_mapping is None:
            curve_mapping = {}
            
        # Depth analysis
        depth_col = 'DEPTH' if 'DEPTH' in self.data.columns else self.data.columns[0]
        depth_range = (self.data[depth_col].min(), self.data[depth_col].max())
        total_depth = abs(depth_range[1] - depth_range[0])
        
        # Calculate step
        if len(self.data) > 1:
            steps = np.diff(self.data[depth_col].values)
            step = np.median(np.abs(steps))
        else:
            step = 0.0
            
        # Identify available curves
        curves_available = [c for c in self.data.columns if c != depth_col]
        
        # Map required curves
        curves_required = self.REQUIRED_CURVES.copy()
        curves_missing = []
        
        for req_curve in curves_required:
            found = False
            mapped_name = curve_mapping.get(req_curve, req_curve)
            if mapped_name in curves_available:
                found = True
            if not found:
                curves_missing.append(req_curve)
        
        # Analyze each curve
        for curve in curves_available:
            self.curve_results[curve] = self._analyze_curve(curve)
        
        # Calculate overall quality score
        if self.curve_results:
            overall_quality = np.mean([r.quality_score for r in self.curve_results.values()])
        else:
            overall_quality = 0.0
            
        return DataQCReport(
            well_name=self.well_name,
            depth_range=depth_range,
            total_depth=total_depth,
            step=step,
            total_points=len(self.data),
            curves_available=curves_available,
            curves_required=curves_required,
            curves_missing=curves_missing,
            curve_results=self.curve_results,
            overall_quality_score=overall_quality
        )
    
    def _analyze_curve(self, curve: str) -> CurveQCResult:
        """
        Analyze a single curve for QC metrics.
        
        Args:
            curve: Curve mnemonic to analyze
            
        Returns:
            CurveQCResult object
        """
        series = self.data[curve]
        total_points = len(series)
        
        # Count nulls
        null_mask = series.isna()
        null_count = null_mask.sum()
        null_percentage = (null_count / total_points) * 100 if total_points > 0 else 0
        
        # Valid data statistics
        valid_data = series.dropna()
        valid_points = len(valid_data)
        
        if valid_points > 0:
            min_val = float(valid_data.min())
            max_val = float(valid_data.max())
            mean_val = float(valid_data.mean())
            std_val = float(valid_data.std())
            median_val = float(valid_data.median())
            p5_val = float(np.percentile(valid_data, 5))
            p95_val = float(np.percentile(valid_data, 95))
            
            # Outlier detection using IQR
            q1 = valid_data.quantile(0.25)
            q3 = valid_data.quantile(0.75)
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr
            outlier_count = int(((valid_data < lower_bound) | (valid_data > upper_bound)).sum())
        else:
            min_val = max_val = mean_val = std_val = median_val = p5_val = p95_val = np.nan
            outlier_count = 0
        
        # Calculate quality score (0-100)
        quality_score = self._calculate_quality_score(
            null_percentage, outlier_count, total_points, curve
        )
        
        return CurveQCResult(
            mnemonic=curve,
            total_points=total_points,
            valid_points=valid_points,
            null_count=null_count,
            null_percentage=null_percentage,
            min_value=min_val,
            max_value=max_val,
            mean_value=mean_val,
            std_value=std_val,
            median_value=median_val,
            p5_value=p5_val,
            p95_value=p95_val,
            outlier_count=outlier_count,
            quality_score=quality_score
        )
    
    def _calculate_quality_score(self, null_pct: float, outliers: int, 
                                  total: int, curve: str) -> float:
        """Calculate a quality score for a curve (0-100)."""
        score = 100.0
        
        # Penalty for null values
        score -= min(null_pct * 0.5, 40)  # Max 40 point penalty
        
        # Penalty for outliers
        if total > 0:
            outlier_pct = (outliers / total) * 100
            score -= min(outlier_pct * 0.3, 20)  # Max 20 point penalty
        
        return max(0, min(100, score))
    
    def get_curve_statistics(self, curve: str) -> Optional[Dict]:
        """Get statistics for a specific curve."""
        if curve in self.curve_results:
            result = self.curve_results[curve]
            return {
                'min': result.min_value,
                'max': result.max_value,
                'mean': result.mean_value,
                'std': result.std_value,
                'median': result.median_value,
                'p5': result.p5_value,
                'p95': result.p95_value,
                'null_pct': result.null_percentage,
                'quality_score': result.quality_score
            }
        return None
    
    def identify_bad_hole(self, cali_curve: str = None, bit_size: float = None,
                          threshold: float = 0.15) -> pd.Series:
        """
        Identify bad hole conditions based on caliper.
        
        Args:
            cali_curve: Caliper curve mnemonic
            bit_size: Bit size in same units as caliper
            threshold: Fractional threshold for bad hole (default 15%)
            
        Returns:
            Boolean series indicating bad hole conditions
        """
        if cali_curve is None or cali_curve not in self.data.columns:
            return pd.Series([False] * len(self.data))
            
        cali = self.data[cali_curve]
        
        if bit_size is None:
            # Estimate bit size from minimum caliper
            bit_size = cali.dropna().quantile(0.05)
        
        # Bad hole where caliper exceeds threshold
        bad_hole = (cali - bit_size).abs() / bit_size > threshold
        
        return bad_hole.fillna(False)
    
    def get_data_gaps(self, curve: str, min_gap_size: int = 5) -> List[Tuple[float, float]]:
        """
        Find continuous data gaps in a curve.
        
        Args:
            curve: Curve mnemonic
            min_gap_size: Minimum number of consecutive nulls to consider a gap
            
        Returns:
            List of (start_depth, end_depth) tuples for each gap
        """
        if curve not in self.data.columns or 'DEPTH' not in self.data.columns:
            return []
            
        null_mask = self.data[curve].isna()
        depth = self.data['DEPTH'].values
        
        gaps = []
        in_gap = False
        gap_start = 0
        gap_count = 0
        
        for i, is_null in enumerate(null_mask):
            if is_null:
                if not in_gap:
                    gap_start = i
                    in_gap = True
                gap_count += 1
            else:
                if in_gap and gap_count >= min_gap_size:
                    gaps.append((depth[gap_start], depth[i-1]))
                in_gap = False
                gap_count = 0
        
        # Check if gap extends to end
        if in_gap and gap_count >= min_gap_size:
            gaps.append((depth[gap_start], depth[-1]))
            
        return gaps


def create_qc_summary_table(qc_report: DataQCReport) -> pd.DataFrame:
    """
    Create a summary table from QC report.
    
    Args:
        qc_report: DataQCReport object
        
    Returns:
        DataFrame with QC summary
    """
    rows = []
    for curve, result in qc_report.curve_results.items():
        rows.append({
            'Curve': curve,
            'Valid Points': result.valid_points,
            'Null %': f"{result.null_percentage:.1f}%",
            'Min': f"{result.min_value:.3f}" if not np.isnan(result.min_value) else 'N/A',
            'Max': f"{result.max_value:.3f}" if not np.isnan(result.max_value) else 'N/A',
            'Mean': f"{result.mean_value:.3f}" if not np.isnan(result.mean_value) else 'N/A',
            'P5': f"{result.p5_value:.3f}" if not np.isnan(result.p5_value) else 'N/A',
            'P95': f"{result.p95_value:.3f}" if not np.isnan(result.p95_value) else 'N/A',
            'Quality': f"{result.quality_score:.0f}/100"
        })
    
    return pd.DataFrame(rows)
