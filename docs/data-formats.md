[Back to README](../README.md)

# Supported Data Formats

## LAS Files

Petrophyter supports LAS 1.2 and 2.0 well-log files. It detects common NULL values, curve types, and depth units automatically. Multiple LAS files from the same well can be merged with curve quality scoring, configurable resampling, and limited gap interpolation.

Checks at load *(v1.7.1)*:

- **Values ≤ 0.** Resistivity, RHOB and DT samples that are zero or negative are tool-off or casing readings; they are set to empty (NaN) and counted in the load notes, for example `RT: 2 samples ≤ 0 set to NaN`. NPHI is not masked, since slightly negative neutron porosity is real.
- **Declared units.** After unit conversion, the median of NPHI must lie in −0.1 to 1.0, RHOB in 1.0 to 3.5 g/cm³ and DT in 30 to 250 µs/ft. Otherwise a load note names the curve and asks you to check its unit. A declared unit that contradicts the values is ignored and the curve is converted as if no unit were declared, with a note.
- **Depth range.** Depths (in feet after conversion) must lie between −1 000 and 60 000 ft. A file outside that range is refused with a message naming the depth curve; this usually means a wrong depth unit.
- **TD and BHT without a unit.** A header total depth without a unit, in a file whose depths are in metres, is taken as metres. A bottom-hole temperature without a unit is taken as °F. The temperature readout in the Parameters window says which unit was assumed, and warns when the header gradient lies outside 0.5 to 4.0 °F/100 ft.

**Merging.** The merged depth grid covers the union of the files. Values are interpolated only between measured samples that are at most the gap limit apart, never past the first or last sample of a file, and a grid depth that falls on a measured sample keeps the measured value. Resistivity is interpolated in log10. A TVD or MD curve in the files is merged like any other curve *(v1.7.1)*.

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
- **Null and non-physical values** *(v1.7.1)*. Null values such as −999.25 in porosity, permeability or grain density, negative porosity, and permeability of zero or below are excluded and counted with the reason in the load notes; they never reach the statistics or the permeability calibration.
- **Matching to the logs** *(v1.7.1)*. A core sample is compared with the log only when valid log samples lie within the matching distance on both sides of it, so a core is never matched across a gap in the log. Cores beside a gap are left out and counted ("N core samples in log gaps").
- Without a well column, the samples belong to the active well. With one, they are assigned to loaded wells in the multi-well import dialog.

## Formation Tops

- Required: a formation name and a top depth.
- Name aliases: `stratigrafical unit`, `stratigraphical unit`, `formation`, `unit`, `name`, `fm`, `surface`, `horizon`, `marker`, `pick`, and `zone`. A well column is never taken as the formation name.
- Top aliases: `top (m)`, `top (ft)`, `top`, `top_md`, and `top_depth`. Only when none of these is present, `top md`, `md`, or `depth` is used; this reads a Petrel export with `Surface` and `MD` columns.
- Bottom aliases (optional): `bottom (m)`, `bottom (ft)`, `bottom`, `bottom_md`, and `bottom_depth`. A formation without a bottom runs to the next top of the same well. The last formation of a well then runs to the bottom of the log; in the multi-well import dialog you can choose **stop at its top** instead.
- An anomaly, code, or remarks column is optional.
- **TVD tops** *(v1.7.1)*. A top column with `TVD` in its header (for example `Top TVD`) is flagged as for core data: the logs are on measured depth, so the multi-well import dialog asks you to confirm before it imports, and the confirmation is stored in the session.
- A top deeper than its bottom is swapped and counted in the load notes. A repeated formation name within a well is reported, and the shallower pick is used.
- Depths are converted to feet when the unit is meters, using the rules above. Thickness is calculated from top and bottom depths, and formations are sorted by top depth.
- Without a well column, the tops belong to the active well. With one, they are assigned to loaded wells in the multi-well import dialog.
- Each formation name is also a zone name for zone parameters; names are compared ignoring case and surrounding spaces.

## Limits

To keep a mistyped unit or step from exhausting memory *(v1.7.1)*:

- A LAS, tops or core file larger than 500 MB is refused.
- A merge is refused before it starts when its depth grid would have more than 2 000 000 points or need about 1 GB of memory; the message gives the depth range and step to check.
- The merge step is limited to 0.1–1.0 ft and the gap limit to 1–50 ft, the ranges of the merge dialog. A session holding a value outside them is loaded with the nearest allowed value and a note.

## Exported files

Text that starts with `=` is never written as a formula *(v1.7.1)*:

- **Excel.** Every cell, including column headers, is written as a value. Text that starts with `=` is stored as text, so `=1+1` shows as `=1+1`.
- **CSV.** A text value that starts with `=`, `+`, `-`, `@`, a tab or a carriage return, and is not a number, gets a leading `'`, so a spreadsheet opens it as text (`-5 ft` is written as `'-5 ft`). Numbers, including negative numbers such as `-2.5`, are written unchanged.

### Provenance and the Field total

Every export records what produced its numbers *(v1.7.1)*: the Petrophyter version and build, the run time (UTC), the well's status at export (current, out of date, or latest run failed), the parameter hash of the run, and the issue counts.

- **Excel.** A **Provenance** sheet: one row per well for an all-wells export, key/value rows for one well. The **Summary** sheet lists **Parameter**, **Scope** (well, zone name, or temperature), **Value**, and **Source** for every parameter the run used.
- **LAS.** An `~OTHER INFORMATION` section before the data, starting with `Exported by Petrophyter <version> (Build <build>)`.
- **CSV.** A `<name>.provenance.txt` file next to the CSV. The CSV itself keeps one header row and one table.

**Field total.** The Field total of the Wells table and the all-wells Excel adds up wells whose results are current or out of date. Wells whose latest run failed are left out: they keep their row with the error and blank numbers, because their earlier numbers stand for settings that no longer produce a result. The Field status reads, for example, `4 wells (1 out of date)`.

## TVD curve in a LAS file

Formation temperature can use a true vertical depth curve. In **Curve Mapping**, the **TVD** row lists the curves of the well. The mnemonics `TVD`, `TVDKB`, `TVDRKB`, `TVDRT`, and `TVDBRT` are mapped automatically; `TVDSS` is not, because it is measured from sea level. A TVD curve whose declared unit is meters is converted to feet when the LAS file is loaded, and a note says so. The curve is used only if it never decreases with measured depth and does not exceed it by more than 1 ft. See [Calculation Methods](calculation-methods.md#formation-temperature) for how it is used.
