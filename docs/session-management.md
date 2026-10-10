[Back to README](../README.md)

# Session Management

Session management was introduced in v1.1 for project continuity. Since format 2.0 a session stores the whole multi-well project.

- **Session → Save Session…:** Export the project to a JSON file.
- **Session → Load Session…:** Re-open the saved wells and restore every parameter scope.
- **Version Compatibility:** Track the session format version.

A format 2.0 session stores:

- `global_params`: the project parameters (all the values listed below);
- `zone_params`: project · zone parameters, keyed by zone name;
- `wells`: for each well its key, display name, LAS source paths (and merge step and gap when merged), curve mapping, analysis mode and formations, well parameters (`overrides`), well · zone parameters (`zone_overrides`), and the tops and core file paths with the core depth unit;
- `active_key`: the active well.

Loading a 2.0 session replaces the loaded wells: the LAS, tops, and core files are read again from their paths. Wells whose files are missing are skipped, and all notes appear in one banner. Results are not stored, so restored wells need a run (**Analysis → Run All Wells**).

Project parameters include:

- Analysis mode and formations
- All VShale, porosity, water-saturation, and permeability parameters
- Archie coefficients and lithology settings
- Cutoff values
- Gas-correction settings *(v1.1)*
- Rw and Rsh values with their Auto/Manual modes *(session format 1.4)*
- Merge and core settings

The current session format version is **2.0**. Format 1.x files still load: they hold parameters only, which are applied to the project (and, when a well is loaded, to its Rw, Rsh, and GR baseline as well values), and the loaded wells stay in place. Version 1.4 added `rw_mode` and `rsh_mode` (`"auto"` or `"manual"`). Older files without them load as follows: `rw_mode` is `"auto"` when the saved Rw is 0.01 or lower and `"manual"` otherwise, and `rsh_mode` is `"auto"`.

A session never restores results. After loading a 1.x session, wells whose effective parameters changed are marked stale until you run the analysis again.

## Workflow

1. Configure all parameters as needed in the Parameters window (**View → Parameters Window**).
2. Choose **Session → Save Session…** (`Ctrl+S`) to export them to JSON.
3. Choose **Session → Load Session…** (`Ctrl+Shift+O`) later to re-open the project, then **Analysis → Run All Wells** (`Ctrl+Shift+R`).

See the [User Guide](user-guide.md#sessions) for how sessions fit into the overall workflow.
