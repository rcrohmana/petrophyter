[Back to README](../README.md)

# Session Management

Session management was introduced in v1.1 for project continuity. Since format 2.0 a session stores the whole multi-well project; format 2.1 adds the record of how each well's tops and core data were imported, format 2.2 *(v1.8.0)* adds the rock typing definitions and settings, and format 2.3 *(v1.9.0)* adds the Monte Carlo uncertainty setup.

- **Session → Save Session…** (`Ctrl+S`): write the project to the current session file (the one last saved or loaded); the first time, it asks for a file.
- **Session → Save Session As…** (`Ctrl+Shift+S`): choose a new file, which becomes the current one *(v1.7.1)*.
- **Session → Load Session…:** Re-open the saved wells and restore every parameter scope.
- **Version Compatibility:** Track the session format version.

A format 2.1, 2.2 or 2.3 session stores:

- `global_params`: the project parameters (all the values listed below);
- `zone_params`: project · zone parameters, keyed by zone name;
- `wells`: for each well its key, display name, LAS source paths (and, when merged, the merge step, gap limit and merge-rules version used for that well), curve mapping (including the optional `TVD` curve), analysis mode and formations, well parameters (`overrides`), well · zone parameters (`zone_overrides`), the tops and core file paths with the core depth unit, and the import records `tops_import` and `core_import`;
- `active_key`: the active well;
- `_app_version`: the Petrophyter version that saved the file *(v1.7.1)*.

**Format 2.2: rock typing** *(v1.8.0)*. A session is written as format **2.2** only when rock typing is used, that is, when **Enable rock typing in the analysis** is on or the project holds applied rock-type definitions. A project that never used rock typing is still written as format **2.1**, so a previous version reads it as before. A 2.2 session adds:

- `rock_types`: the applied definitions, the fit scope and method, the settings (reservoir only, minimum PHIE, core labels, overburden factors, and so on), a fingerprint of the core they were fitted on, and the fit report. The definitions are plain numbers, so the parameter hash of a loaded session is the same as before saving and wells are not marked out of date by the round trip;
- in `global_params`: `rock_typing_enabled`, `perm_primary` and `rt_log_perm` (these three are written in every session, at their defaults when rock typing is not used);
- in a well's `overrides`: `perm_primary` and `rt_log_perm` when set for that well.

Core labels used in the log are derived from the core each time, never saved. Results are not saved either, so a loaded session needs a run.

**Opening a 2.2 session in an older version.** A 2.2 session opens in version 1.7.x (and 1.7.0): the rock typing settings and definitions are ignored without a message, the rest of the project loads normally, and a session saved again from that version no longer contains them. **Opening a newer session.** See below.

**Format 2.3: uncertainty** *(v1.9.0)*. A session is written as format **2.3** only when at least one Monte Carlo distribution is enabled on **Parameters → Uncertainty**. Otherwise it is written as 2.2 (rock typing used) or 2.1, exactly as before, and a project whose distributions are all disabled leaves no trace in the file. A 2.3 session adds the top-level key `uncertainty`:

- `n`, `seed` and `sampling` (`lhs` or `random`);
- `distributions`: for each of `a`, `m`, `n`, `rw`, `rsh`, `vsh_cutoff`, `phi_cutoff` and `sw_cutoff`, the fields `enabled`, `kind` (`triangular`, `normal` or `uniform`), `mode` (`relative` or `additive`), `low`, `mid`, `high` and `sd`. Relative offsets are stored as fractions (0.10 is +10 %);
- `correlations`: a list of `[parameter, parameter, rho]` entries, for example `["m", "n", 0.5]`; empty when the m–n correlation is 0.

The Monte Carlo **result is not saved**. The seed, N, sampling and ranges are saved, so loading the session and running **Analysis → Run Uncertainty…** gives the same numbers. A session from before 1.9.0 has no `uncertainty` key: it loads with the default setup (nothing enabled, N 300, seed 12345, Latin hypercube) and behaves as before. The distributions are not part of the well parameters, so changing them never marks a well out of date.

**Opening a 2.3 session in an older version.** Version 1.8.0 and older read the file with the compatible fields: the `uncertainty` key is ignored without a message, and a session saved again from that version no longer contains it.

**Sessions from a newer Petrophyter.** Petrophyter refuses a session whose format major version is higher than the one it writes (3.0 or 9.0, when this version writes 2.x). It shows the message **This session was saved by a newer Petrophyter (format X.Y). Update Petrophyter to open it.** with the format of the file in place of X.Y, and changes nothing in the open project. Without this guard, such a file would be read as an old parameter-only session. Sessions of format 1.x, 2.0, 2.1 and 2.2 all load.

**Sessions from 1.7.1 and older** *(v1.7.2)*. Version 1.7.2 corrects several calculations (porosity,
Dual-Water and Waxman-Smits Sw, auto Rw, pay thickness and averages; see the
[v1.7.2 release notes](releases/v1.7.2.md)). A session saved by 1.7.1 or older, or without `_app_version`,
loads with the new defaults and a note in the load banner: "Saved by Petrophyter 1.7.1. Calculations changed
in 1.7.2 …; Run to see the corrected results." Results are never stored in a session, so every well is out of
date until you run the analysis. The corrections are not options and there is no legacy mode; the only way
back to a previous number is a setting such as **D-N combination: RMS**, which reproduces the old PHIT.
The new parameters `dn_combination`, `gas_crossover_min`, `gas_vsh_max` and `vsh_primary_method` are saved with
the other parameters; version 1.7.1 and older ignore them.

**Merged wells** *(v1.7.1)*. Each merged well keeps its own merge step and gap limit, so a project with wells merged at different steps restores each one as it was merged. Sessions saved by v1.7.0 and older stored the last merge step of the project for every merged well; such wells are merged again under the v1.7.1 rules (no edge extrapolation, resistivity interpolated in log10) with that step, and a banner note names the step and the row count. If a merged well's row count looks wrong, import it again with **Merge LAS Files**.

Loading a 2.0, 2.1, 2.2 or 2.3 session replaces the loaded wells: the LAS, tops, and core files are read again from their paths. Wells whose files are missing are skipped, and all notes appear in one banner. The wells are rebuilt in the background: the window stays responsive and the status bar shows the progress, for example `Restoring 3 of 10: BKS-03`. While it runs, opening files, Save Session, Merge LAS Files, Run Analysis and Run All Wells are unavailable ("Unavailable while a session is loading"). **New Project** or another **Load Session…** cancels the restore and leaves no partial project. If the restore fails, or every well in the file is skipped, the project that was open stays as it was and a warning banner says why *(v1.7.1)*.

**Source fingerprints** *(v1.7.2)*. When a file is loaded, Petrophyter computes its SHA-256 hash and size from the bytes it reads. The session stores them next to the paths: `source_fingerprints` for each well (one entry per LAS file, so a merged well has one per file), and `tops_sha256` and `core_sha256` for the tops and core files. Saving never reads the files again. The `sources` list is unchanged, so an older version still opens the session.

When you load a session, each file is compared with its stored hash before the well is rebuilt:

- **Same hash.** The well loads as before.
- **Changed.** The file is still read, and the banner says `a.las changed since the session was saved (hash differs); results will differ from the saved project`. The well needs a run, as every restored well does.
- **Missing.** Petrophyter asks you to locate the file (`Locate a.las…`). Pick the file where it is now. A file with the same hash loads with no note; a different file loads with the *changed* note. **Cancel** skips the file, and the well is skipped with a note, as in earlier versions. The folder you pick is tried first, without asking, for the other missing files of the same session.

A session saved by v1.7.0 or v1.7.1 has no hashes: it loads as before, with no note and no prompt.

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

The current session format version is **2.3** (written only when a Monte Carlo distribution is enabled; otherwise **2.2** when rock typing is used, or **2.1**). Format 2.0 and 2.1 files still load, with rock typing off, with name matching for tops and core data. Format 1.x files still load: they hold parameters only, which are applied to the project (and, when a well is loaded, to its Rw, Rsh, and GR baseline as well values), and the loaded wells stay in place. Version 1.4 added `rw_mode` and `rsh_mode` (`"auto"` or `"manual"`). Older files without them load as follows: `rw_mode` is `"auto"` when the saved Rw is 0.01 or lower and `"manual"` otherwise, and `rsh_mode` is `"auto"`.

**Lithology presets.** A named lithology preset at a well, zone, or well · zone scope now supplies a, m, and n at that scope. When an older session holds explicit a, m, and n entries equal to the preset's values at the same scope, loading removes those entries and keeps the preset, so later changes of the preset flow down. A note in the load banner reports it. Entries that differ from the preset stay explicit, and the project-level values are not touched.

**Unsaved changes** *(v1.7.1)*. An asterisk at the start of the window title marks changes since the last save or load. Closing the window, loading a session, or starting a new project with unsaved changes asks Save, Discard, or Cancel. Loading a session clears the mark; New Project clears it and forgets the current file. Loading a format 1.x session (parameters only) leaves the project unsaved with no current file, so Save asks for a new file instead of overwriting the old one. The mark and the current file are not stored in the session.

A session never restores results. After loading a 1.x session, wells whose effective parameters changed are marked stale until you run the analysis again.

## Workflow

1. Configure all parameters as needed in the Parameters window (**View → Parameters Window**).
2. Choose **Session → Save Session…** (`Ctrl+S`) to export them to JSON.
3. Choose **Session → Load Session…** (`Ctrl+Shift+O`) later to re-open the project, then **Analysis → Run All Wells** (`Ctrl+Shift+R`).

See the [User Guide](user-guide.md#sessions) for how sessions fit into the overall workflow.
