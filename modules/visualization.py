"""
Visualization Module for Petrophyter
Log plotting and data visualization functions
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.ticker import AutoMinorLocator
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, List, Tuple, Optional


class LogPlotter:
    """
    Log visualization class for creating multi-track displays.
    """
    
    # Color schemes
    COLORS = {
        'GR': '#00AA00',
        'RHOB': '#FF0000',
        'NPHI': '#0000FF',
        'DT': '#FF00FF',
        'RT': '#000000',
        'VSH': '#8B4513',
        'PHIT': '#00FFFF',
        'PHIE': '#00CED1',
        'SW': '#1E90FF',
        'PERM': '#FFD700',
    }
    
    def __init__(self, data: pd.DataFrame, depth_col: str = 'DEPTH'):
        """
        Initialize plotter with data.
        
        Args:
            data: DataFrame containing log data
            depth_col: Depth column name
        """
        self.data = data
        self.depth_col = depth_col
        
    def create_composite_log(self, 
                             curves_config: List[Dict],
                             depth_range: Tuple[float, float] = None,
                             formation_tops: List[Dict] = None,
                             title: str = "Composite Log") -> go.Figure:
        """
        Create an interactive composite log using Plotly.
        
        Args:
            curves_config: List of dicts with curve configuration
                Each dict: {'name': str, 'track': int, 'color': str, 
                           'min': float, 'max': float, 'log_scale': bool}
            depth_range: Optional (top, bottom) depth range
            formation_tops: Optional list of formation top dicts
            title: Plot title
            
        Returns:
            Plotly figure
        """
        # Filter data by depth range
        if depth_range:
            mask = (self.data[self.depth_col] >= depth_range[0]) & \
                   (self.data[self.depth_col] <= depth_range[1])
            plot_data = self.data[mask].copy()
        else:
            plot_data = self.data.copy()
        
        # Determine number of tracks
        tracks = max([c.get('track', 1) for c in curves_config])
        
        # Create subplots
        fig = make_subplots(
            rows=1, cols=tracks,
            shared_yaxes=True,
            horizontal_spacing=0.02
        )
        
        # Add curves
        for config in curves_config:
            curve_name = config['name']
            if curve_name not in plot_data.columns:
                continue
                
            track = config.get('track', 1)
            color = config.get('color', self.COLORS.get(curve_name, '#000000'))
            line_style = config.get('line_style', 'solid')
            
            fig.add_trace(
                go.Scatter(
                    x=plot_data[curve_name],
                    y=plot_data[self.depth_col],
                    mode='lines',
                    name=curve_name,
                    line=dict(color=color, width=1),
                    showlegend=True
                ),
                row=1, col=track
            )
            
            # Set axis range
            if 'min' in config and 'max' in config:
                fig.update_xaxes(
                    range=[config['min'], config['max']],
                    row=1, col=track
                )
            
            # Log scale
            if config.get('log_scale', False):
                fig.update_xaxes(type='log', row=1, col=track)
        
        # Add formation tops if provided
        if formation_tops:
            for fm in formation_tops:
                depth = fm.get('depth', 0)
                name = fm.get('name', '')
                for col in range(1, tracks + 1):
                    fig.add_hline(y=depth, line_dash='dash', 
                                  line_color='gray', 
                                  annotation_text=name if col == 1 else '',
                                  row=1, col=col)
        
        # Update layout
        fig.update_yaxes(autorange='reversed', title_text='Depth (ft)', row=1, col=1)
        fig.update_layout(
            title=title,
            height=800,
            showlegend=True,
            legend=dict(orientation='h', yanchor='bottom', y=1.02)
        )
        
        return fig
    
    def create_standard_log(self, 
                            gr_curve: str = 'GR',
                            rt_curve: str = 'RT',
                            rhob_curve: str = 'RHOB',
                            nphi_curve: str = 'NPHI',
                            dt_curve: str = 'DT',
                            depth_range: Tuple[float, float] = None) -> go.Figure:
        """
        Create a standard 4-track log display.
        
        Track 1: GR + Vshale
        Track 2: Resistivity
        Track 3: Density + Neutron
        Track 4: Porosity + Sw
        
        Args:
            Various curve names
            depth_range: Optional depth range
            
        Returns:
            Plotly figure
        """
        curves_config = [
            # Track 1: GR
            {'name': gr_curve, 'track': 1, 'color': '#00AA00', 'min': 0, 'max': 150},
            {'name': 'VSH', 'track': 1, 'color': '#8B4513', 'min': 0, 'max': 1},
            
            # Track 2: Resistivity
            {'name': rt_curve, 'track': 2, 'color': '#000000', 'log_scale': True},
            
            # Track 3: Density-Neutron
            {'name': rhob_curve, 'track': 3, 'color': '#FF0000', 'min': 1.95, 'max': 2.95},
            {'name': nphi_curve, 'track': 3, 'color': '#0000FF', 'min': 0.45, 'max': -0.15},
            
            # Track 4: Porosity-Sw
            {'name': 'PHIE', 'track': 4, 'color': '#00CED1', 'min': 0, 'max': 0.4},
            {'name': 'SW_INDO', 'track': 4, 'color': '#1E90FF', 'min': 0, 'max': 1},
        ]
        
        return self.create_composite_log(curves_config, depth_range)
    
    def create_petrophysics_summary(self,
                                     depth_range: Tuple[float, float] = None) -> go.Figure:
        """
        Create a petrophysics summary log.
        
        Track 1: GR + Vsh
        Track 2: Porosity (all methods)
        Track 3: Sw (all methods)
        Track 4: Permeability
        Track 5: Pay flags
        
        Returns:
            Plotly figure
        """
        curves_config = [
            # Track 1: GR
            {'name': 'GR', 'track': 1, 'color': '#00AA00', 'min': 0, 'max': 150},
            {'name': 'VSH', 'track': 1, 'color': '#8B4513', 'min': 0, 'max': 1},
            
            # Track 2: Porosity
            {'name': 'PHIE_D', 'track': 2, 'color': '#FF0000', 'min': 0, 'max': 0.4},
            {'name': 'PHIE_N', 'track': 2, 'color': '#0000FF', 'min': 0, 'max': 0.4},
            {'name': 'PHIE_DN', 'track': 2, 'color': '#00CED1', 'min': 0, 'max': 0.4},
            
            # Track 3: Sw
            {'name': 'SW_ARCHIE', 'track': 3, 'color': '#FF6B6B', 'min': 0, 'max': 1},
            {'name': 'SW_INDO', 'track': 3, 'color': '#4ECDC4', 'min': 0, 'max': 1},
            {'name': 'SW_SIMAN', 'track': 3, 'color': '#45B7D1', 'min': 0, 'max': 1},
            
            # Track 4: Permeability
            {'name': 'PERM_TIMUR', 'track': 4, 'color': '#FFD700', 'log_scale': True},
            {'name': 'PERM_WR', 'track': 4, 'color': '#FF8C00', 'log_scale': True},
            
            # Track 5: Pay flags
            {'name': 'NET_PAY_FLAG', 'track': 5, 'color': '#00FF00', 'min': 0, 'max': 1},
        ]
        
        return self.create_composite_log(curves_config, depth_range, 
                                         title="Petrophysics Summary")


def create_histogram(data: pd.Series, 
                     title: str = "Histogram",
                     bins: int = 50,
                     color: str = '#1E90FF') -> go.Figure:
    """
    Create a histogram plot.
    
    Args:
        data: Data series
        title: Plot title
        bins: Number of bins
        color: Bar color
        
    Returns:
        Plotly figure
    """
    fig = go.Figure()
    
    # Check for empty data
    data_clean = data.dropna()
    if len(data_clean) == 0:
        fig.add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16)
        )
        fig.update_layout(title=title)
        return fig
    
    fig.add_trace(go.Histogram(
        x=data_clean,
        nbinsx=bins,
        marker_color=color,
        opacity=0.7
    ))
    
    # Add statistics lines
    mean_val = data_clean.mean()
    p5_val = np.percentile(data_clean, 5)
    p95_val = np.percentile(data_clean, 95)
    
    fig.add_vline(x=mean_val, line_dash='solid', line_color='red',
                  annotation_text=f'Mean: {mean_val:.2f}')
    fig.add_vline(x=p5_val, line_dash='dash', line_color='green',
                  annotation_text=f'P5: {p5_val:.2f}')
    fig.add_vline(x=p95_val, line_dash='dash', line_color='green',
                  annotation_text=f'P95: {p95_val:.2f}')
    
    fig.update_layout(
        title=title,
        xaxis_title=title,
        yaxis_title='Frequency',
        showlegend=False
    )
    
    return fig


def create_crossplot(x_data: pd.Series,
                     y_data: pd.Series,
                     color_data: pd.Series = None,
                     x_label: str = 'X',
                     y_label: str = 'Y',
                     title: str = 'Crossplot') -> go.Figure:
    """
    Create a crossplot.
    
    Args:
        x_data: X-axis data
        y_data: Y-axis data
        color_data: Optional data for color coding
        x_label: X-axis label
        y_label: Y-axis label
        title: Plot title
        
    Returns:
        Plotly figure
    """
    fig = go.Figure()
    
    if color_data is not None:
        fig.add_trace(go.Scatter(
            x=x_data,
            y=y_data,
            mode='markers',
            marker=dict(
                size=5,
                color=color_data,
                colorscale='Viridis',
                colorbar=dict(title='Color'),
                opacity=0.7
            ),
            text=[f'{x_label}: {x:.2f}<br>{y_label}: {y:.2f}' 
                  for x, y in zip(x_data, y_data)]
        ))
    else:
        fig.add_trace(go.Scatter(
            x=x_data,
            y=y_data,
            mode='markers',
            marker=dict(size=5, color='#1E90FF', opacity=0.7)
        ))
    
    fig.update_layout(
        title=title,
        xaxis_title=x_label,
        yaxis_title=y_label
    )
    
    return fig


def create_depth_plot_matplotlib(data: pd.DataFrame,
                                  curves: List[str],
                                  depth_col: str = 'DEPTH',
                                  depth_range: Tuple[float, float] = None,
                                  figsize: Tuple[int, int] = (12, 10)) -> plt.Figure:
    """
    Create a multi-track log using matplotlib.
    
    Args:
        data: Log data
        curves: List of curves to plot
        depth_col: Depth column name
        depth_range: Optional depth range
        figsize: Figure size
        
    Returns:
        Matplotlib figure
    """
    # Filter data
    if depth_range:
        mask = (data[depth_col] >= depth_range[0]) & (data[depth_col] <= depth_range[1])
        plot_data = data[mask].copy()
    else:
        plot_data = data.copy()
    
    n_tracks = len(curves)
    fig, axes = plt.subplots(1, n_tracks, figsize=figsize, sharey=True)
    
    if n_tracks == 1:
        axes = [axes]
    
    colors = ['#00AA00', '#FF0000', '#0000FF', '#FF00FF', '#000000', '#FFD700']
    
    for i, curve in enumerate(curves):
        if curve in plot_data.columns:
            ax = axes[i]
            color = colors[i % len(colors)]
            
            ax.plot(plot_data[curve], plot_data[depth_col], color=color, linewidth=0.5)
            ax.set_xlabel(curve)
            ax.invert_yaxis()
            ax.grid(True, alpha=0.3)
            ax.xaxis.set_minor_locator(AutoMinorLocator())
            
            if i == 0:
                ax.set_ylabel('Depth')
    
    plt.tight_layout()
    return fig


def create_summary_bar_chart(summary: Dict[str, float],
                             title: str = "Net Pay Summary") -> go.Figure:
    """
    Create a bar chart for net pay summary.
    
    Args:
        summary: Dictionary with summary values
        title: Plot title
        
    Returns:
        Plotly figure
    """
    categories = ['Gross Sand', 'Net Reservoir', 'Net Pay']
    values = [
        summary.get('gross_sand', 0),
        summary.get('net_reservoir', 0),
        summary.get('net_pay', 0)
    ]
    
    colors = ['#FFA07A', '#90EE90', '#00CED1']
    
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        x=categories,
        y=values,
        marker_color=colors,
        text=[f'{v:.1f} ft' for v in values],
        textposition='outside'
    ))
    
    fig.update_layout(
        title=title,
        yaxis_title='Thickness (ft)',
        showlegend=False
    )
    
    return fig
