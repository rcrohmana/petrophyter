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
- Merge and core settings

## Workflow

1. Configure all parameters as needed in the Parameters window (**View → Parameters Window**).
2. Choose **Session → Save Session…** (`Ctrl+S`) to export them to JSON.
3. Choose **Session → Load Session…** (`Ctrl+Shift+O`) later to restore the settings.

See the [User Guide](user-guide.md#sessions) for how sessions fit into the overall workflow.
