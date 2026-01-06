"""
Pytest Fixtures for Petrophyter Tests
"""

import pytest
import pandas as pd
import numpy as np
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def sample_log_data():
    """Generate sample log data for testing."""
    np.random.seed(42)
    n_samples = 100
    
    depth = np.linspace(1000, 1100, n_samples)
    
    # Create realistic log data
    data = pd.DataFrame({
        'DEPTH': depth,
        'GR': 50 + 30 * np.random.random(n_samples) + 20 * np.sin(depth / 10),
        'RHOB': 2.3 + 0.2 * np.random.random(n_samples),
        'NPHI': 0.2 + 0.1 * np.random.random(n_samples),
        'DT': 80 + 20 * np.random.random(n_samples),
        'RT': 10 + 90 * np.random.random(n_samples)
    })
    
    return data


@pytest.fixture
def clean_sand_data():
    """Generate data representing clean sand (low shale)."""
    np.random.seed(42)
    n_samples = 50
    
    data = pd.DataFrame({
        'DEPTH': np.linspace(1000, 1050, n_samples),
        'GR': 20 + 10 * np.random.random(n_samples),  # Low GR
        'RHOB': 2.0 + 0.1 * np.random.random(n_samples),  # Low density
        'NPHI': 0.25 + 0.05 * np.random.random(n_samples),  # High porosity
        'DT': 100 + 10 * np.random.random(n_samples),
        'RT': 50 + 50 * np.random.random(n_samples)  # High resistivity
    })
    
    return data


@pytest.fixture
def shaly_data():
    """Generate data representing shaly formation."""
    np.random.seed(42)
    n_samples = 50
    
    data = pd.DataFrame({
        'DEPTH': np.linspace(1000, 1050, n_samples),
        'GR': 100 + 20 * np.random.random(n_samples),  # High GR
        'RHOB': 2.6 + 0.1 * np.random.random(n_samples),  # High density
        'NPHI': 0.35 + 0.05 * np.random.random(n_samples),  # High NPHI
        'DT': 120 + 10 * np.random.random(n_samples),
        'RT': 2 + 5 * np.random.random(n_samples)  # Low resistivity
    })
    
    return data


@pytest.fixture
def gas_zone_data():
    """Generate data representing gas zone (N-D crossover)."""
    np.random.seed(42)
    n_samples = 50
    
    data = pd.DataFrame({
        'DEPTH': np.linspace(1000, 1050, n_samples),
        'GR': 30 + 10 * np.random.random(n_samples),  # Low GR (clean)
        'RHOB': 1.8 + 0.1 * np.random.random(n_samples),  # Very low density (gas)
        'NPHI': 0.05 + 0.05 * np.random.random(n_samples),  # Low NPHI (gas effect)
        'DT': 150 + 20 * np.random.random(n_samples),
        'RT': 200 + 100 * np.random.random(n_samples)  # Very high RT
    })
    
    return data
