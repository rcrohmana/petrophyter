[Back to README](../README.md)

# Session Management

Session management was introduced in v1.1 for project continuity.

- **Save Session:** Export analysis parameters to a JSON file.
- **Load Session:** Restore parameters from a saved JSON file.
- **Version Compatibility:** Track the session format version.

Saved parameters include:

- Analysis mode and formations
- All VShale, porosity, water-saturation, and permeability parameters
- Archie coefficients and lithology settings
- Cutoff values
- Gas-correction settings *(v1.1)*
- Merge and core settings

## Workflow

1. Configure all parameters as needed.
2. Click **Save Session** to export them to JSON.
3. Click **Load Session** later to restore the settings.
