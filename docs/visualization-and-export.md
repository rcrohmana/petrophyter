[Back to README](../README.md)

# Visualization and Export

## Interactive Log Display *(v1.1)*

The PyQtGraph display provides:

- OpenGL GPU-accelerated rendering
- Six-track composite log display
- Zoom, pan, and crosshair cursor
- Draggable depth-region selection
- Formation-top overlays
- Linked Y axes across all tracks
- Updates throttled to approximately 30 FPS for smooth interaction *(optimized in v1.2)*

## Classic Log Display *(v1.0)*

The Matplotlib display produces static, export-quality plots and includes a navigation toolbar for pan, zoom, and save operations.

## Crossplots

- Neutron-density crossplot, color-coded by Vsh
- Porosity-permeability crossplot

## Export Options

| Format | Description | Version |
|---|---|---|
| Excel (`.xlsx`) | Multi-sheet workbook containing results and a summary | v1.0 |
| CSV (`.csv`) | Full results DataFrame | v1.0 |

Merged data can also be downloaded as LAS (`.las`).
