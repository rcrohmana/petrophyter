[Back to README](../README.md)

# Session Management

Session management was introduced in v1.1 for project continuity. Since format 2.0 a session stores the whole multi-well project; format 2.1 adds the record of how each well's tops and core data were imported.

- **Session → Save Session…** (`Ctrl+S`): write the project to the current session file (the one last saved or loaded); the first time, it asks for a file.
- **Session → Save Session As…** (`Ctrl+Shift+S`): choose a new file, which becomes the current one *(v1.7.1)*.
- **Session → Load Session…:** Re-open the saved wells and restore every parameter scope.
- **Version Compatibility:** Track the session format version.

A format 2.1 session stores:

- `global_params`: the project parameters (all the values listed below);
- `zone_params`: project · zone parameters, keyed by zone name;
- `wells`: for each well its key, display name, LAS source paths (and, when merged, the merge step, gap limit and merge-rules version used for that well), curve mapping (including the optional `TVD` curve), analysis mode and formations, well parameters (`overrides`), well · zone parameters (`zone_overrides`), the tops and core file paths with the core depth unit, and the import records `tops_import` and `core_import`;
- `active_key`: the active well;
- `_app_version`: the Petrophyter version that saved the file *(v1.7.1)*.

**Merged wells** *(v1.7.1)*. Each merged well keeps its own merge step and gap limit, so a project with wells merged at different steps restores each one as it was merged. Sessions saved by v1.7.0 and older stored the last merge step of the project for every merged well; such wells are merged again under the v1.7.1 rules (no edge extrapolation, resistivity interpolated in log10) with that step, and a banner note names the step and the row count. If a merged well's row count looks wrong, import it again with **Merge LAS Files**.

Loading a 2.0 or 2.1 session replaces the loaded wells: the LAS, tops, and core files are read again from their paths. Wells whose files are missing are skipped, and all notes appear in one banner. The wells are rebuilt in the background: the window stays responsive and the status bar shows the progress, for example `Restoring 3 of 10: BKS-03`. While it runs, opening files, Save Session, Merge LAS Files, Run Analysis and Run All Wells are unavailable ("Unavailable while a session is loading"). **New Project** or another **Load Session…** cancels the restore and leaves no partial project. If the restore fails, or every well in the file is skipped, the project that was open stays as it was and a warning banner says why *(v1.7.1)*.

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

**Unsaved changes** *(v1.7.1)*. An asterisk at the start of the window title marks changes since the last save or load. Closing the window, loading a session, or starting a new project with unsaved changes asks Save, Discard, or Cancel. Loading a session clears the mark; New Project clears it and forgets the current file. Loading a format 1.x session (parameters only) leaves the project unsaved with no current file, so Save asks for a new file instead of overwriting the old one. The mark and the current file are not stored in the session.

A session never restores results. After loading a 1.x session, wells whose effective parameters changed are marked stale until you run the analysis again.

## Workflow

1. Configure all parameters as needed in the Parameters window (**View → Parameters Window**).
2. Choose **Session → Save Session…** (`Ctrl+S`) to export them to JSON.
3. Choose **Session → Load Session…** (`Ctrl+Shift+O`) later to re-open the project, then **Analysis → Run All Wells** (`Ctrl+Shift+R`).

See the [User Guide](user-guide.md#sessions) for how sessions fit into the overall workflow.
