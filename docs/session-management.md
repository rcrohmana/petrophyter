[Back to README](../README.md)

# Session Management

Session management was introduced in v1.1 for project continuity.

- **Session → Save Session…:** Export analysis parameters to a JSON file.
- **Session → Load Session…:** Restore parameters from a saved JSON file.
- **Version Compatibility:** Track the session format version.

Saved parameters include:

- Analysis mode and formations
- All VShale, porosity, water-saturation, and permeability parameters
- Archie coefficients and lithology settings
- Cutoff values
- Gas-correction settings *(v1.1)*
- Rw and Rsh values with their Auto/Manual modes *(session format 1.4)*
- Merge and core settings

The current session format version is **1.4**. Version 1.4 adds `rw_mode` and `rsh_mode` (`"auto"` or `"manual"`). Older files without them load as follows: `rw_mode` is `"auto"` when the saved Rw is 0.01 or lower and `"manual"` otherwise, and `rsh_mode` is `"auto"`.

A session restores parameters only, not results. If results are on screen when you load a session, they are marked stale until you run the analysis again.

## Workflow

1. Configure all parameters as needed in the Parameters window (**View → Parameters Window**).
2. Choose **Session → Save Session…** (`Ctrl+S`) to export them to JSON.
3. Choose **Session → Load Session…** (`Ctrl+Shift+O`) later to restore the settings.

See the [User Guide](user-guide.md#sessions) for how sessions fit into the overall workflow.
