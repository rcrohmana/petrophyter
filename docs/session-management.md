[Back to README](../README.md)

# Session Management

Session management was introduced in v1.1 for project continuity. Since format 2.0 a session stores the whole multi-well project; format 2.1 adds the record of how each well's tops and core data were imported.

- **Session → Save Session…:** Export the project to a JSON file.
- **Session → Load Session…:** Re-open the saved wells and restore every parameter scope.
- **Version Compatibility:** Track the session format version.

A format 2.1 session stores:

- `global_params`: the project parameters (all the values listed below);
- `zone_params`: project · zone parameters, keyed by zone name;
- `wells`: for each well its key, display name, LAS source paths (and merge step and gap when merged), curve mapping (including the optional `TVD` curve), analysis mode and formations, well parameters (`overrides`), well · zone parameters (`zone_overrides`), the tops and core file paths with the core depth unit, and the import records `tops_import` and `core_import`;
- `active_key`: the active well.

Loading a 2.0 or 2.1 session replaces the loaded wells: the LAS, tops, and core files are read again from their paths. Wells whose files are missing are skipped, and all notes appear in one banner. The wells are rebuilt in the background: the window stays responsive and the status bar shows the progress, for example `Restoring 3 of 10: BKS-03`. While it runs, opening files, Save Session, Merge LAS Files, Run Analysis and Run All Wells are unavailable ("Unavailable while a session is loading"). **New Project** or another **Load Session…** cancels the restore and leaves no partial project. If the restore fails, the project stays empty and a banner says why.

**Import records.** When tops or core data were assigned to a well from a multi-well file, the well stores a `tops_import` or `core_import` record: the file well name and its spellings, the columns that were used, the delimiter, decimal mark and encoding that were detected, the sheet, the depth unit, the fill-down setting, the last-formation rule and, for core data, the porosity scale. Loading the session replays the record exactly, so a manual choice such as mapping the file well `BKS-1` to the loaded well `BKS-01`, a column picked by hand, or a depth unit chosen in the dialog survives. If the file no longer holds any of the stored spellings, or the replay fails, Petrophyter falls back to matching the file by well name and adds a note to the banner. A 2.0 session has no records and always matches by name. A well whose tops or core file was loaded without a well column has no record. Results are not stored, so restored wells need a run (**Analysis → Run All Wells**).

Project parameters include:

- Analysis mode and formations
- All VShale, porosity, water-saturation, and permeability parameters
- Archie coefficients and lithology settings
- Cutoff values
- Gas-correction settings *(v1.1)*
- Rw and Rsh values with their Auto/Manual modes *(session format 1.4)*
- Temperature settings: correction on or off, surface temperature, gradient and its Auto mode, Rw reference temperature, temperature datum depth, Rsh reference temperature, and Waxman-Smits B from temperature. Older sessions load with the datum at 0, no Rsh reference temperature, and B from temperature off, which reproduces their results.
- Merge and core settings

The current session format version is **2.1**. Format 2.0 files still load, with name matching for tops and core data. Format 1.x files still load: they hold parameters only, which are applied to the project (and, when a well is loaded, to its Rw, Rsh, and GR baseline as well values), and the loaded wells stay in place. Version 1.4 added `rw_mode` and `rsh_mode` (`"auto"` or `"manual"`). Older files without them load as follows: `rw_mode` is `"auto"` when the saved Rw is 0.01 or lower and `"manual"` otherwise, and `rsh_mode` is `"auto"`.

**Lithology presets.** A named lithology preset at a well, zone, or well · zone scope now supplies a, m, and n at that scope. When an older session holds explicit a, m, and n entries equal to the preset's values at the same scope, loading removes those entries and keeps the preset, so later changes of the preset flow down. A note in the load banner reports it. Entries that differ from the preset stay explicit, and the project-level values are not touched.

A session never restores results. After loading a 1.x session, wells whose effective parameters changed are marked stale until you run the analysis again.

## Workflow

1. Configure all parameters as needed in the Parameters window (**View → Parameters Window**).
2. Choose **Session → Save Session…** (`Ctrl+S`) to export them to JSON.
3. Choose **Session → Load Session…** (`Ctrl+Shift+O`) later to re-open the project, then **Analysis → Run All Wells** (`Ctrl+Shift+R`).

See the [User Guide](user-guide.md#sessions) for how sessions fit into the overall workflow.
