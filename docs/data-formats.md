[Back to README](../README.md)

# Supported Data Formats

## LAS Files

Petrophyter supports LAS 1.2 and 2.0 well-log files. It detects common NULL values, curve types, and depth units automatically. Multiple LAS files from the same well can be merged with curve quality scoring, configurable resampling, and limited gap interpolation.

## Reading tops and core tables

Formation tops and core data are read by the same table reader, so the rules in this section apply to both.

- **Files.** `.txt`, `.csv`, `.tsv`, and `.xlsx`. Text files are read as UTF-8 (with or without a byte-order mark) and, if that fails, as Windows-1252. For a workbook, the first sheet is read; the multi-well import dialog offers a **Sheet** combo when there are several.
- **Delimiter.** Tab, comma, semicolon, or pipe. Petrophyter tries each one and keeps the one for which the required columns are found. If more than one works, the one whose rows have the most consistent number of columns wins, and then the order tab, comma, semicolon, pipe. A split that leaves a single column never wins over one that separates columns.
- **Comment and preamble lines.** Blank lines and lines starting with `#` are ignored. Up to ten lines above the header (a title, an export date) are skipped until a line with the required columns is found.
- **Unit row.** A row of units directly under the header (for example `m`, `ft`, `%`, `mD`) is dropped. If it holds `m` or `ft`, it also sets the depth unit.
- **Decimal comma.** In files not delimited by commas, a column of plain numbers that uses commas is read with the comma as the decimal mark (`0,215` is 0.215). One value that can only be a decimal comma, such as `0,215` or `1234,5`, makes every comma in the file a decimal mark. If every comma value could also be a thousands group (`1,250`, `12,000`), the commas are taken as thousands separators, so a depth is never shrunk a thousandfold. The load notes say which reading was used. Workbooks and comma-delimited files keep their cell values as they are.
- **Well column.** Optional. Accepted aliases, in priority order, are `well`, `well_name`, `wellname`, `well name`, `well id`, `uwi`, `api`, `wellbore`, `borehole`, and `well identifier`. A `uwi` or `api` column is matched against the UWI or API in the LAS header; the others are matched on the well name, ignoring case, spaces, hyphens, and underscores. A column that is entirely blank is ignored. Spellings of one well (`BKS-01`, `bks 01`, `BKS_01`) are treated as one well.
- **Merged cells.** When blank well cells look like merged cells (the first row names a well and each well forms one block of increasing depths), blank cells continue the well above. The multi-well import dialog switches this on by itself and lets you change it.
- **Rows that are left out.** A row with a missing or non-numeric depth, a blank well cell (when a well column exists), or, for tops, a blank formation name is excluded, never silently. The load banner and the import dialog count them and give the first file line numbers and the reason; for workbooks the number is the Excel row. Rows without a well are counted separately.
- **Depth units.** The unit is detected from a `(m)` or `(ft)` in the depth column name (for core) or top and bottom column names (for tops), then from a unit row. If it cannot be detected, depths are left unchanged (assumed feet) and a warning is shown; in the multi-well import dialog you must choose **M** or **FT** before importing. The dialog also notes when the depths fit the logs only under the other unit.

## Core Data

- Required: a depth column and at least one property column. Column names are trimmed and matched case-insensitively through aliases.
- Depth aliases: `depth`, `depth (m)`, `depth_m`, `md`, `tvd`, `depth_md`, and `tvdss`.
- Porosity aliases: `porosity`, `porosity (%)`, `por`, `phi`, `core_por`, and `core porosity`.
- Permeability aliases: `perm`, `permeability`, `k`, `kh`, `khor`, `hor.perm`, `hor perm`, `perm (md)`, `permeability (md)`, and `horizontal perm`.
- Grain density is optional. Aliases: `grain density`, `grain_density`, `rhog`, `rho_grain`, and `matrix density`.
- **TVD depth.** If the depth column is named `tvd` or `tvdss`, a warning says that the logs are on measured depth. Use such core data only when the well is vertical or the logs are on TVD. The multi-well import dialog asks you to confirm before it imports.
- **Porosity scale.** Whether porosity is a percentage or a fraction is decided per well from its median value: a median above 1 means percent, and the values are divided by 100. One mistyped value therefore no longer rescales a whole well. Any value that is still above 1 after conversion (for example 150 %) is excluded and reported. If the wells of one file differ, a warning lists each well's scale. In the multi-well import dialog you can override the scale of each well.
- Permeability is assumed to be in mD.
- Non-numeric property values are treated as missing. The data are sorted by depth before use.
- Without a well column, the samples belong to the active well. With one, they are assigned to loaded wells in the multi-well import dialog.

## Formation Tops

- Required: a formation name and a top depth.
- Name aliases: `stratigrafical unit`, `stratigraphical unit`, `formation`, `unit`, `name`, `fm`, `surface`, `horizon`, `marker`, `pick`, and `zone`. A well column is never taken as the formation name.
- Top aliases: `top (m)`, `top (ft)`, `top`, `top_md`, and `top_depth`. Only when none of these is present, `top md`, `md`, or `depth` is used; this reads a Petrel export with `Surface` and `MD` columns.
- Bottom aliases (optional): `bottom (m)`, `bottom (ft)`, `bottom`, `bottom_md`, and `bottom_depth`. A formation without a bottom runs to the next top of the same well. The last formation of a well then runs to the bottom of the log; in the multi-well import dialog you can choose **stop at its top** instead.
- An anomaly, code, or remarks column is optional.
- A top deeper than its bottom is swapped and counted in the load notes. A repeated formation name within a well is reported, and the shallower pick is used.
- Depths are converted to feet when the unit is meters, using the rules above. Thickness is calculated from top and bottom depths, and formations are sorted by top depth.
- Without a well column, the tops belong to the active well. With one, they are assigned to loaded wells in the multi-well import dialog.
- Each formation name is also a zone name for zone parameters; names are compared ignoring case and surrounding spaces.

## TVD curve in a LAS file

Formation temperature can use a true vertical depth curve. In **Curve Mapping**, the **TVD** row lists the curves of the well. The mnemonics `TVD`, `TVDKB`, `TVDRKB`, `TVDRT`, and `TVDBRT` are mapped automatically; `TVDSS` is not, because it is measured from sea level. A TVD curve whose declared unit is meters is converted to feet when the LAS file is loaded, and a note says so. The curve is used only if it never decreases with measured depth and does not exceed it by more than 1 ft. See [Calculation Methods](calculation-methods.md#formation-temperature) for how it is used.
