[Back to README](../README.md)

# Supported Data Formats

## LAS Files

Petrophyter supports LAS 1.2 and 2.0 well-log files. It detects common NULL values, curve types, and depth units automatically. Multiple LAS files from the same well can be merged with curve quality scoring, configurable resampling, and limited gap interpolation.

## Core Data

- Supported files: `.txt` and `.csv`; tab-separated data are preferred, with comma-separated fallback.
- Column names are trimmed and matched case-insensitively through aliases.
- A depth column is required. Accepted aliases are `depth`, `depth (m)`, `depth_m`, `md`, `tvd`, and `depth_md`.
- At least one property column is required:
  - Porosity aliases: `porosity`, `porosity (%)`, `por`, `phi`, `core_por`, and `core porosity`.
  - Permeability aliases: `perm`, `permeability`, `k`, `kh`, `hor.perm`, `perm (md)`, `permeability (md)`, and `horizontal perm`.
- Grain density is optional. Accepted aliases are `grain density`, `grain_density`, `rhog`, `rho_grain`, and `matrix density`.
- Depth units are detected from `(m)`/`_m` or `(ft)`/`_ft` in the header. Depth defaults to meters and is converted automatically to feet to match logs.
- Porosity values greater than 1 are interpreted as percentages and converted to fractions.
- Permeability is assumed to be in mD.
- Non-numeric values are coerced to NaN. Rows without depth are dropped, and the data are sorted by depth before use.

## Formation Tops

- Supported files: `.txt` and `.csv`; formation tops expect tab-separated data.
- Column names are trimmed and matched case-insensitively through aliases.
- A formation name is required. Accepted aliases are `stratigrafical unit`, `stratigraphical unit`, `formation`, `unit`, `name`, and `fm`.
- A top depth is required. Accepted aliases are `top (m)`, `top`, `top_md`, and `top_depth`.
- Bottom depth is optional. Accepted aliases are `bottom (m)`, `bottom`, `bottom_md`, and `bottom_depth`.
- An anomaly, code, or remarks column is optional.
- Depths should be supplied in meters; the application converts them to feet after loading.
- Thickness is calculated from top and bottom depths, and formations are sorted by top depth.
