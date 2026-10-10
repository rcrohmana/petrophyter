# Petrophyter Design System

This document is the binding contract for all UI work in Petrophyter.
**`themes/tokens.py` is the source of truth. The tables here are documentation.**
If this file and the code disagree, the code wins and this file needs a fix.

Rules are enforced by `tests/test_design_compliance.py` (plus the token tests in
`tests/test_design_tokens.py`). Never widen a whitelist without amending this document.

## 1. Principles

1. Neutral first, accent is scarce.
2. Hierarchy comes from spacing and type, not borders.
3. Data outranks chrome.
4. One radius, one border weight.
5. Nothing is modal unless it blocks.

Aesthetic: industrial scientific (cool grays, one technical accent, thin monochrome
stroke icons). Light theme is primary; dark has the identical key set.

## 2. Tokens

All values live in `themes/tokens.py`: `COLORS`, `TYPOGRAPHY`, `SPACING`, `METRICS`,
`PLOT_COLORS`, `PLOT_CHROME`, `PLOT_COLOR_OVERRIDES`. UI code reads colors through
`themes.colors.get_color` / `get_plot_color` / `get_plot_chrome`, or through the
rendered QSS. `light` and `dark` must have identical keys (`test_theme_key_parity`).

### 2.1 Colors

| Token | Light | Dark | Use |
|---|---|---|---|
| `bg_base` | `#F0F2F4` | `#17191D` | Window, menu bar, toolbar, Data Browser, table headers |
| `bg_surface` | `#FFFFFF` | `#1F2227` | Content area, inputs, tables, plot figure/axes |
| `bg_sunken` | `#E8EAED` | `#131518` | Disabled fills, progress track |
| `bg_hover` | `#E9EBEE` | `#262A30` | Hover |
| `bg_pressed` | `#DFE2E6` | `#2C3138` | Pressed |
| `border` | `#D5D9DE` | `#2E3238` | Hairlines, grid |
| `border_strong` | `#B8BEC5` | `#3D434B` | Header underline, spines, scrollbar handles |
| `text_primary` | `#1F2328` | `#D5D9DE` | Body text |
| `text_secondary` | `#57606A` | `#9AA1A9` | Labels, icons, plot text |
| `text_muted` | `#798089` | `#6E757D` | Captions, placeholders |
| `text_disabled` | `#A5ABB3` | `#4E545B` | Disabled text |
| `text_on_accent` | `#FFFFFF` | `#FFFFFF` | Text on accent fills |
| `accent` | `#3D6E96` | `#5B8DB8` | See accent rule below |
| `accent_hover` | `#356185` | `#6C9CC4` | Primary button hover |
| `accent_pressed` | `#2E5677` | `#4A7CA6` | Primary button pressed |
| `accent_subtle` | `#E4EDF4` | `#243240` | Selection background, info banner |
| `accent_muted` | `#9EB6CA` | `#3D5F7F` | Disabled slider fill |
| `focus_ring` | `#8FB0CC` | `#7DA5C9` | Slider handle focus border |
| `success` | `#2E7D46` | `#57A773` | OK status |
| `success_subtle` | `#E6F2EA` | `#1E2C23` | Success banner |
| `warning` | `#B26A00` | `#C98A2E` | Warning status |
| `warning_subtle` | `#F7EEDF` | `#2E271B` | Warning banner |
| `error` | `#B3382E` | `#C75E55` | Error status |
| `error_subtle` | `#F6E7E5` | `#2E1F1E` | Error tint |
| `tooltip_bg` | `#2B2F34` | `#33383F` | Tooltip |
| `tooltip_text` | `#F0F2F4` | `#E4E7EA` | Tooltip |

**Accent rule.** Accent is allowed only on: the Run Analysis button, the active-tab
underline, selection, focus, ghost links, and the info banner.

### 2.2 Typography

- Family: `Segoe UI`; numeric data: `Consolas`. Set once in `main.py`:
  `app.setFont(QFont("Segoe UI", 9))`.
- Scale (pt): `font_caption` 8, `font_body` 9, `font_subheading` 10, `font_max` 11.
  Nothing larger than 11pt anywhere.
- Weights: 400 and 600 only.
- Section labels: 8pt, 600, uppercase via Python `.upper()` (QSS has no
  `text-transform`), `text_muted` (`QLabel#SectionLabel`). Sub-section labels:
  8pt 600 `text_secondary` (`QLabel#SubsectionLabel`).
- Numeric table cells: Consolas 9pt right-aligned, applied by the shared
  `PandasTableModel` (`ui/widgets/table_model.py`).

### 2.3 Spacing and metrics

| Token | Value |
|---|---|
| `SPACING` xs / sm / md / lg / xl / xxl | 4 / 8 / 12 / 16 / 24 / 32 px |
| `radius` | 3 px (the only radius) |
| `control_height` | 26 px |
| `toolbar_height` | 34 px |
| `panel_min_width` / `default` / `max` | 220 / 300 / 320 px (Data Browser) |
| `params_window_width` x `height` | 640 x 560 (min 560 x 420) |
| `params_page_list_width` | 180 px |
| `splitter_handle` | 4 px |
| `scrollbar_width` | 10 px |

No shadows, no gradients, one 1px border weight.

### 2.4 Plot tokens

- `PLOT_COLORS`: curve colors (GR green, RHOB red, NPHI blue, ...). Industry convention,
  theme independent, **never change a value**. Named entries replace former inline
  colors: `GR_FILL`, `FORMATION_TOP`, `SW_DEFAULT`, `DEFAULT_HISTOGRAM`, `RES_FILL`.
- `PLOT_CHROME[theme]`: `figure`, `axes` = `bg_surface`; `grid` = `border`;
  `spine` = `border_strong`; `text` = `text_secondary`; `crosshair` = `text_muted`;
  `selection` = `accent`.
- `PLOT_COLOR_OVERRIDES["dark"]["RT"]` = `text_primary` (black RT is unreadable on dark).
- Matplotlib annotations, edges and bboxes take colors from `get_plot_chrome()` or
  `get_plot_color()`, never from literals.

## 3. Theming architecture

- `themes/template.py`: one QSS template (`string.Template`, `$token` placeholders).
- `themes/renderer.py`: `render_qss(theme, qss_icon_dir)`; raises on an unresolved token.
- `themes/theme_manager.py`: `set_theme` clears the icon cache, applies the rendered
  QSS and a QPalette built from tokens, then runs callbacks.
- Dynamic styling in `ui/` uses Qt properties only: `themes.helpers.set_status(widget,
  "success" | "warning" | "error" | "muted" | "accent" | None)` and the `variant`
  property (`"primary"`, `"ghost"`, `"link"`) on buttons. Look is defined in the
  template via attribute selectors. Object names used by the template:
  `SectionLabel`, `SubsectionLabel`, `PlaceholderLabel`, `AboutTitle`, `QcChip`,
  `InfoStrip*`, `NotificationBanner`, `WellIndicator`.
- Icons are cached per theme, and a stored `QIcon` never recolors itself. Any widget that
  calls `setIcon(get_icon(...))` once must re-set it in a `refresh_theme()` that
  `MainWindow._handle_theme_change` calls (done for the Parameters window, Merge dialog,
  banner, Data Browser, tabs and interactive log).
- **No `setStyleSheet` anywhere in `ui/`.**

## 4. Components

### 4.1 Buttons: three variants

| Variant | Look | Rule |
|---|---|---|
| Primary (`variant="primary"`) | `accent` fill, `text_on_accent`, weight 600 | Run Analysis only |
| Standard (default) | `bg_surface`, 1px `border`, `text_primary` | Everything else (Merge, Calculate, Apply, Download, dialogs) |
| Ghost (`variant="ghost"`) | transparent, `text_secondary`, hover `bg_hover` | Toolbar icon buttons, banner close, inline link-style actions |

All: 26px, 3px radius, 12px horizontal padding. A `link` variant exists in the
template for text-only actions.

### 4.2 Inputs

`bg_surface`, 1px `border`, 26px, 3px radius. Focus: 1px `accent` border. Disabled:
`bg_sunken` + `text_disabled`. Checkbox and radio indicators are 14px with a 1px
`border_strong` outline on `bg_surface`. A checked checkbox fills with `accent` and shows the
Lucide `check` tick (2px corner radius). A radio is a circle (the one round shape, exempt from
the 3px radius) whose checked state is a thick `accent` ring with a `bg_surface` center. Combo and spin arrows are Lucide chevrons injected through
the QSS `image:` URLs (`$qss_icons`, written by `ensure_qss_icons`). Combo popup:
`bg_surface`, selection `accent_subtle`.

### 4.3 Tables

Header `bg_base`, 8pt 600 `text_secondary`, bottom border `border_strong`. Rows
`bg_surface` with hairline separators, no zebra, no grid lines. Selection
`accent_subtle` + `text_primary`. Numeric cells Consolas 9pt right-aligned. Score
columns may color by threshold (>=90 success, 70-89 warning, <70 error): the only color
inside tables.

### 4.4 Section headers

`QGroupBox` borders are styled away globally (`border: none`, 8pt muted title), so
existing group boxes act as flat headed sections. Do not add new bordered boxes.
Collapsible sections no longer exist (`CollapsibleGroupBox` was deleted with the
sidebar); the template keeps `QFrame#SectionHeader` rules, but no code uses them.

### 4.5 Info strip (`ui/widgets/info_strip.py`)

Replaces `MetricCard`. A row of label/value blocks separated by hairline rules,
transparent, no boxes. Label 8pt uppercase `text_muted`; value 10pt 600
`text_primary`. API: `add_block(key, label)`, `set_value(key, text)`,
`set_status(key, status)`, `value_label(key)`. Used by QC, Petrophysics, Diagnostics and
Summary tabs.

### 4.6 NotificationBanner (`ui/widgets/notification_banner.py`)

One slot above the tabs. Variant icon (16px), 9pt message, ghost close button (`x`).
Kinds: `success`, `warning`, `info` (subtle backgrounds with matching border). Failures
are not banners: `show_message` rejects other kinds. Non-modal. Shown through
`MainWindow.show_banner(kind, message)`.

### 4.7 Status indicators

- `StatusDot` / `dot_pixmap(status, size=8)` in `ui/widgets/status_dot.py`: filled 8px
  circle painted with `QPainter`. **Not a Lucide icon**: Lucide `circle` is an outline
  ring. `dot_pixmap` statuses: `success`, `warning`, `error`, `off`. The `StatusDot`
  label widget takes kinds `ok`, `warn`, `off` instead.
- QC chip in the status bar: `QC 80/100`, 8pt 600, status by threshold (>=90, 70-89, <70).
- Stale-results label: `MainWindow.stale_label` (objectName `StaleLabel`), a permanent
  status-bar label reading `Parameters changed — press F5 to update results`. It takes the
  `warning` status via `set_status`, appears when parameters change after a successful
  analysis, and is cleared on analysis start and on New Project.

### 4.8 Empty states and progress

Placeholders: centered, `text_muted`, `QLabel#PlaceholderLabel`, plain instruction
text (for example `Run analysis to view diagnostics`). Progress: status-bar
`QProgressBar`, 6px tall, `accent` chunk on `bg_sunken`, visible only while working.

### 4.9 Scrollbars and splitter

Scrollbars 10px, flat, no arrow buttons, handle `border_strong` (hover `text_muted`).
Splitter handle 4px, `bg_base`, `border_strong` on hover.

### 4.10 Plot chrome

Figure/axes `bg_surface`, grid `border`, spines `border_strong`, text `text_secondary`.
Curve colors are untouched. The matplotlib toolbar icons come from `get_icon` and are
re-applied in `PlotWidget.update_theme_colors()` so they recolor on theme change.

### 4.11 About dialog

App name uses `QLabel#AboutTitle` (11pt 600), version line `SubsectionLabel`, sections
separated by plain hairline rules. License-table HTML takes its border color from
`get_color("border")`. Version comes from `version.py` (`APP_VERSION`,
`APP_VERSION_DISPLAY`).

### 4.12 Data tree (Data Browser, `ui/data_browser.py`)

- Read-only `QTreeView` on `bg_base`; shows data and status, never an input control.
  Enforced by `test_data_browser_is_read_only`.
- Two columns: Name (9pt, group nodes 600) and Info (8pt, `text_muted`, right-aligned).
  Curve role tags (`GR`, `RHOB`, `NPHI`, `DT`, `RT`) are 8pt 600 `text_secondary`.
- Icons 16px (`file-text` LAS, `activity` curves, `layers` tops, `database` core, `sigma`
  results). Status is an 8px dot from `dot_pixmap`, never colored row text.
- One root per well of the project, in load order. The root shows the well name, its
  depth range and a status dot (`off` loaded, `success` analysed, `warning` out of date,
  `error` failed). The active well's root is bold with the `crosshair` icon and starts
  expanded; other wells use `cylinder` and start collapsed. Clicking any item makes its
  well active (`well_selected(str)`); the root menu adds Set as Active Well and Remove
  Well (`remove_well_requested(str)`, confirmed by the main window).
- Width 220 to 320px (default 300). Empty state: `No data loaded` with an
  `Open LAS File(s)...` link.
- Selection `accent_subtle`; hover `bg_hover`; unloaded and merged-away sources are muted.
- Context menus reuse the main window's `QAction` objects (passed in via `set_actions`),
  chosen per node kind: Open LAS and Merge LAS on well and LAS nodes, Curve Mapping on
  curve nodes, Open Tops and Analysis Scope on tops, Open Core and Core Matching on core,
  Run Analysis on results. Double-clicking a "Not loaded" tops or core node, or a curve
  node, emits `action_requested(str)` (`open_tops`, `open_core`, `page_curves`).
- A formation with zone parameters (project · zone or this well's well · zone) carries a
  marker and a tooltip listing them. Double-clicking a formation emits
  `action_requested("edit_zone:<ZONE>")`; the main window sets the Well scope with that
  zone and opens the Zones page.

### 4.13 Parameters window (`ui/parameters_window.py`)

- Modeless `Tool` dialog parented to `MainWindow`, created once, shown and hidden. Title
  `Parameters — Petrophyter`. 640x560, minimum 560x420.
- Left: 180px page list under non-selectable group labels ANALYSIS / PARAMETERS /
  CORRECTIONS; selected row `accent_subtle` with a 2px `accent` left bar. Right: stacked
  pages in a scroll area. Footer: one `Close` (Standard); no Primary button.
- Pages (key: title): `scope` Analysis Scope, `curves` Curve Mapping, `core` Core
  Matching, `porosity` Porosity Method, `vshale` VShale, `cutoffs` Cutoffs, `rock` Rock
  Properties, `sat` Saturation Models, `perm` Permeability, `gas` Gas Correction. The
  `PAGES` tuple is the source of truth; each page is reachable from one menu action
  (`test_parameter_menus_cover_pages`, in `tests/test_main_window_chrome.py`).
  `EXTRA_PAGES` adds `zones` Zones under a SCOPES group label (no menu action).
- Scope bar (`ui/widgets/scope_bar.py`) above the pages: checkable `Project` /
  `Well: <name>` buttons (the checked one Primary), a `Zone:` combo (`All zones` plus the
  zones in scope) and a `text_muted` caption ("Values for every well", "UPPER in
  BKS-01"). It drives `AppModel.set_edit_scope` and follows `scope_changed` back. At the
  flat project scope the pages look exactly as before.
- At any other scope each scoped field gets a `FieldModeControl`: a 22px tool button
  whose menu holds Auto (`refresh-cw`, only where the parameter supports it) / Manual
  (`sliders-horizontal`) / Inherit (`layers`), then Copy to… (`copy`) and Set as project
  default (`house`). Inherited values use the muted input state with a tooltip naming
  the source; out-of-range values use the warning input state. Fields that cannot be set
  at the edited scope are disabled with a tooltip.
- Zones page (`ui/widgets/zone_grid.py`): a `QTableWidget`, one row per zone, columns
  Zone, a, m, n, Rw, Rsh, ρ matrix, the three cutoffs, and a read-only GR clean–shale.
  Muted cells inherit; typing sets, clearing inherits, `auto` sets Rw / Rsh to Auto.
- Temperature section (`TemperatureGroup`) on the Saturation Models page: Correct Rw for
  formation temperature, Surface temp, Gradient with an Auto checkbox, Rw ref. temp.
  Well-scoped only (no zone).
- Apply-to-shale buttons act only at the flat project scope.
- Live apply: no OK/Cancel/Apply. Edits emit `parameters_updated`. Calculate buttons
  use the `calculator` icon, "Apply Calculated" buttons the `check` icon. Calculate
  results show as status text under the button, never in a popup.
- Run Analysis stays the only accent control; F5 works while this window has focus.

### 4.14 Load Summary dialog (`ui/widgets/load_summary_dialog.py`)

Modal task dialog shown when two or more LAS files are opened (File > Open LAS File(s) or
Merge LAS Files). Files are parsed on a worker thread first. Contents: a note line
("Files in the same group are merged into one well. Files from different wells are never
merged."), a file table (File, Well, Key, Depth range, Step, Curves, Notes, Group combo),
Step (ft) and Gap limit spin boxes (enabled only when a group holds more than one file),
`Load N wells` (Standard) and `Cancel`. Files that failed to parse are shown disabled with
their error. The OK button is disabled, with a tooltip naming the files, when a group mixes
wells whose identities differ. A single file loads directly without the dialog.

The toolbar `WellSelector` combo (`ui/widgets/well_selector.py`) mirrors the project's
wells and is shown when there are two or more; it emits `well_selected(str)` only on a
user choice.

## 5. Notification policy

| Event | Surface |
|---|---|
| Success, completion (analysis, save/load session, export, merge) | NotificationBanner (success) and/or status-bar message. Never modal. |
| Non-blocking warnings (depth-unit ambiguity) | NotificationBanner (warning) |
| Load notes (files, session restore, tops/core well matching, depth coverage) | One NotificationBanner per load listing every note |
| Some wells failed in a multi-well run | One NotificationBanner (warning) naming each failed well; a single failed well with no other result still uses the error dialog |
| Precondition warnings | Prevented by action enablement; otherwise status-bar message |
| Failures (parse, merge, analysis, save/load) | `QMessageBox.critical` / `.warning` |
| Destructive confirmation (New Project with data) | `QMessageBox.question` |

`QMessageBox.information` must not appear anywhere.

## 6. Iconography

Lucide (ISC license, text in `NOTICE`): monochrome stroke SVGs in `icons/lucide/`,
`stroke="currentColor"`, stroke width 1.75. `themes.icon_loader.get_icon(name,
color_token="text_secondary")` recolors per theme, renders 16/18/24px at DPR 1 and 2,
and caches by `(name, theme, color_token)`. `clear_icon_cache()` runs on every theme
change. `app_icon.svg` / `.ico` are the application logo and are outside this set.

| Icon | Use |
|---|---|
| `folder-open` | Open LAS, Data Browser empty-state link |
| `file-plus` | New Project |
| `folder-input` | Load Session |
| `save` | Save Session; matplotlib toolbar save |
| `play` | Run Analysis |
| `merge` | Merge LAS |
| `download` | Save merged LAS, CSV and Excel export |
| `layers` | Formation tops |
| `database` | Core data |
| `file-text` | LAS file nodes |
| `activity` | Curve nodes |
| `sigma` | Results node, computed curves |
| `sun`, `moon` | Theme menu items |
| `panel-left` | View > Data Browser |
| `sliders-horizontal` | Parameters toolbar button; matplotlib "tune" |
| `book-open` | User Guide |
| `info` | About, info banner |
| `circle-check` | Success banner |
| `triangle-alert` | Warning banner |
| `circle-x` | Error variant |
| `x` | Banner close |
| `chevron-down`, `chevron-up`, `chevron-right` | Combo, spin and tree arrows (QSS) |
| `check` | "Apply Calculated" buttons; checkbox tick (QSS) |
| `calculator` | "Calculate" buttons |
| `refresh-cw` | Reset View (interactive log) |
| `copy` | Copy Citation |
| `house`, `arrow-left`, `arrow-right`, `move`, `zoom-in`, `settings-2` | matplotlib toolbar (home, back, forward, pan, zoom, subplots) |

That is 35 files. **Status dots are not Lucide icons**: they are painted by
`dot_pixmap` (see 4.7).

**Adding an icon:** add the name to `ICONS` in `scripts/fetch_lucide_icons.py`, run the
script (it downloads from Lucide and normalizes the stroke), add a row to this table,
then reference it with `get_icon("name")`. `test_icon_references_are_bundled` fails if a
referenced icon is missing.

## 7. Prohibitions

| Prohibition | Enforced by |
|---|---|
| No emoji in user-facing strings (includes the checkmark, warning, arrow and triangle glyph ranges in the test regex) | `test_no_emoji` |
| No hex colors outside `themes/tokens.py` (scans `ui/`, `main.py`, `services/`) | `test_no_hex_colors_outside_tokens` |
| No named CSS colors (`color: green`, ...) in `ui/` | `test_no_named_css_colors` |
| No `setStyleSheet` in `ui/` (whitelist is empty) | `test_no_inline_stylesheets` |
| No inline `font-size` in `ui/` | `test_no_inline_font_sizes_in_ui` |
| No `QMessageBox.information` anywhere scanned | `test_no_information_messagebox` |
| Icon names must exist in `icons/lucide/` | `test_icon_references_are_bundled` |
| Data Browser has no input widgets and no `parameter_groups` import | `test_data_browser_is_read_only` |
| Light and dark token keys are identical | `test_theme_key_parity` (`tests/test_design_tokens.py`) |
| QSS renders with no unresolved `$token` | `test_qss_renders_without_residue` (`tests/test_design_tokens.py`) |
| No font above 11pt via `QFont` / `setPointSize` | Review only; the scan covers inline `font-size`, not `QFont` sizes |
| No radius other than 3px, no shadows, no gradients | Review only; keep them in the template |
| Accent only where section 2.1 allows | Review only |
| No new bordered group boxes | Review only |

## 8. Contribution checklist

1. Need a new color, size or metric? Add it to `themes/tokens.py` first (both themes).
2. Add or change the QSS rule in `themes/template.py` using `$tokens`, never literals.
3. In `ui/`, style through object names, the `variant` property and `set_status`; never
   `setStyleSheet`, hex colors, named colors, `font-size` or emoji.
4. Use `get_icon("name")` for icons; add new icons per section 6.
5. Check the result in both themes and take a screenshot of each
   (`python scripts/capture_ui.py --out <dir> --theme both`).
6. Run `pytest tests/test_design_compliance.py`, then the full suite.
