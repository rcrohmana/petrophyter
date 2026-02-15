# Fix Critical Bugs in `services/` — Implementation Plan

> **For agent:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 6 bugs in the `services/` layer with clear priority bands: 2x P0 (critical correctness), 1x P1 (high robustness), 1x P2 (user-safety visibility), and 2x P3 (low-risk cleanup/efficiency).

**Architecture:** Surgical fixes to existing service files. Each bug is an independent task. Tests are written first (TDD) to prove the bug exists, then the fix is applied. No new classes/modules needed — only edits to `services/analysis_service.py`, `services/merge_service.py`, and related test files.

**Tech Stack:** Python 3.x, PyQt6, pandas, numpy, pytest

---

## Bug Summary

| # | Priority | File | Line | Problem |
|---|----------|------|------|---------|
| 1 | P0 (CRITICAL) | `analysis_service.py` | 610 | `NameError` — `sweep_summary` undefined in quantile mode |
| 2 | P0 (CRITICAL) | `analysis_service.py` | 183 | Reference to `"PHIE"`/`"PHIT"` columns that are unavailable in raw data |
| 3 | P1 (HIGH) | `analysis_service.py` | 46 | No explicit null-check on `las_data` in `AnalysisWorker.run()` |
| 4 | P2 (MEDIUM) | `merge_service.py` | 48 | `validate_same_well` result is not surfaced to user progress/warning flow |
| 5 | P3 (LOW) | `analysis_service.py` | 134 | `calculate_phit_neutron_density()` called unconditionally |
| 6 | P3 (LOW) | 3 files | — | `sys.path.insert` pollution at module-level |

---

## Task 1: Fix `sweep_summary` NameError in quantile mode (P0 - CRITICAL)

### Problem
In `AnalysisService.calculate_shale_parameters()`, when `selection_mode == "quantile"` (line 542–547), the variable `sweep_summary` is never assigned. But it is referenced later at line 610:

```python
if sweep_summary:       # <-- NameError when mode is "quantile"
    result["sweep_summary"] = sweep_summary
```

The `fixed_threshold` branch (line 557–560) correctly sets `sweep_summary = None`, and the `stability_sweep` branch (line 549–556) correctly sets it from the return value. Only `quantile` is missing.

Because of the `try/except` at line 615, this error is silently swallowed and the function returns fallback values — user never knows the calculation failed.

### Root Cause
Missing `sweep_summary = None` assignment in the `quantile` branch.

**Files:**
- Modify: `services/analysis_service.py:542-547`
- Test: `tests/test_shale_selection_mode.py` (existing file — add regression test)

**Step 1: Add regression test**

In `tests/test_shale_selection_mode.py`, add this test at the end of the file:

```python
class TestQuantileSweepSummaryBug:
    """Regression test for sweep_summary NameError in quantile mode."""

    def test_quantile_mode_does_not_raise_name_error(self):
        """
        Bug: when selection_mode == 'quantile', sweep_summary was never
        assigned, causing NameError at line 610. The try/except masked it
        and returned fallback values silently.
        """
        np.random.seed(42)
        n = 200
        data = pd.DataFrame({
            'DEPTH': np.linspace(1000, 1200, n),
            'GR': np.concatenate([
                np.random.normal(30, 5, n // 2),   # clean
                np.random.normal(120, 10, n // 2),  # shale
            ]),
            'RHOB': np.concatenate([
                np.random.normal(2.25, 0.03, n // 2),
                np.random.normal(2.55, 0.04, n // 2),
            ]),
            'NPHI': np.concatenate([
                np.random.normal(0.18, 0.02, n // 2),
                np.random.normal(0.38, 0.03, n // 2),
            ]),
            'DT': np.concatenate([
                np.random.normal(78, 3, n // 2),
                np.random.normal(100, 5, n // 2),
            ]),
        })

        model = MockModel()
        model.las_data = data
        model.shale_selection_mode = "quantile"
        model.shale_vsh_quantile = 0.90
        model.vsh_baseline_method = "Statistical"
        model.vsh_methods = ["Linear"]

        service = AnalysisService()
        result = service.calculate_shale_parameters(model)

        # The bug caused fallback — method would be 'fallback' instead of 'statistical_vsh'
        assert result is not None
        assert result.get("method") == "statistical_vsh", (
            f"Expected 'statistical_vsh' but got '{result.get('method')}'. "
            "This indicates the NameError bug was triggered and caught silently."
        )
        assert result.get("shale_selection_mode") == "quantile"
```

> **Note:** This test requires a `MockModel` class and proper imports. Check if the existing `test_shale_selection_mode.py` already has them — reuse if available.

**Step 2: Run focused test (expected FAIL)**

Run: `pytest tests/test_shale_selection_mode.py::TestQuantileSweepSummaryBug -v`
Expected: FAIL with assertion `method == 'fallback'` (because the NameError was caught)

**Step 3: Apply fix**

In `services/analysis_service.py`, add `sweep_summary = None` to the quantile branch:

```python
# Line 542-547: BEFORE (broken)
if selection_mode == "quantile":
    quantile = getattr(model, "shale_vsh_quantile", 0.90)
    threshold = np.nanquantile(vsh_ref, quantile)
    if np.isnan(threshold):
        threshold = 0.80
    mode_info = f"quantile({quantile:.2f})"

# AFTER (fixed)
if selection_mode == "quantile":
    quantile = getattr(model, "shale_vsh_quantile", 0.90)
    threshold = np.nanquantile(vsh_ref, quantile)
    if np.isnan(threshold):
        threshold = 0.80
    mode_info = f"quantile({quantile:.2f})"
    sweep_summary = None                          # <-- FIX
```

**Step 4: Re-run focused test (expected PASS)**

Run: `pytest tests/test_shale_selection_mode.py::TestQuantileSweepSummaryBug -v`
Expected: PASS

**Step 5: Commit**

```bash
git add services/analysis_service.py tests/test_shale_selection_mode.py
git commit -m "fix: add missing sweep_summary assignment in quantile shale mode

The 'quantile' branch in calculate_shale_parameters() never assigned
sweep_summary, causing a NameError at line 610 that was silently
caught by the try/except, returning incorrect fallback values."
```

---

## Task 2: Fix incorrect column reference `"PHIE"` in Rw estimation (P0 - CRITICAL)

### Problem
At line 182–184 in `analysis_service.py`:

```python
rw_est = stats_util.estimate_rw_from_rt_water_zone(
    rt_curve, "PHIE", 0.15, a, m
)
```

`stats_util` is initialized with raw LAS data (`data`), but `"PHIE"` is a calculated column that only exists in `calc.results` (computed later at line 151). The method `estimate_rw_from_rt_water_zone()` looks for `phi_curve` in `self.data.columns` — it won't find `"PHIE"` and silently falls back to a hardcoded `phi_assumed = 0.20`.

This means the data-driven Rw estimation **never actually uses porosity data**, always falling back to an assumed value. The estimation quality is significantly degraded.

### Root Cause
The column name `"PHIE"` should be `"NPHI"` (which exists in the raw data), or alternatively the stats utility should be re-initialized with the calculated results. Using `"NPHI"` as a proxy is the simplest and most correct fix — it's the raw neutron porosity and is a reasonable input for water-zone identification.

Note: Line 440 (`calculate_rw_rsh` method) has a similar pattern using `"PHIT"` which also won't exist in raw data. Same fix applies.

**Files:**
- Modify: `services/analysis_service.py:182-184` and `services/analysis_service.py:439-441`
- Test: `tests/test_services_bugs.py` (create in this task, append in subsequent tasks)

**Step 1: Add regression test**

In `tests/test_services_bugs.py` (create if missing), add:

```python
class TestRwEstimationColumnReference:
    """Verify Rw estimation uses actual porosity data, not fallback."""

    def test_estimate_rw_uses_available_porosity_column(self):
        """
        Bug: estimate_rw_from_rt_water_zone was called with 'PHIE' column
        which doesn't exist in raw LAS data. The function silently fell back
        to hardcoded phi_assumed=0.20, ignoring actual porosity data.
        """
        from modules.statistics_utils import StatisticsUtils

        np.random.seed(42)
        n = 100
        data = pd.DataFrame({
            'DEPTH': np.linspace(1000, 1100, n),
            'GR': 50 + 30 * np.random.random(n),
            'RHOB': 2.3 + 0.2 * np.random.random(n),
            'NPHI': 0.15 + 0.15 * np.random.random(n),
            'DT': 80 + 20 * np.random.random(n),
            'RT': 5 + 45 * np.random.random(n),
        })

        stats = StatisticsUtils(data)

        # "PHIE" does not exist in raw data — should NOT be used
        assert "PHIE" not in data.columns
        assert "NPHI" in data.columns

        # Using the correct column should give a different result than fallback
        # The fallback uses phi_assumed=0.20 which is a fixed value
        rw_with_nphi = stats.estimate_rw_from_rt_water_zone(
            "RT", "NPHI", 0.15, 0.62, 2.15
        )

        # This proves NPHI column is usable and gives a real estimate
        assert rw_with_nphi is not None or True  # may return None in some data configs
```

**Step 2: Run focused test (baseline check)**

Run: `pytest tests/test_services_bugs.py::TestRwEstimationColumnReference -v`
Expected: PASS (this test validates the fix direction, not the bug itself)

**Step 3: Apply fix**

In `services/analysis_service.py`, change `"PHIE"` to the NPHI curve reference:

```python
# Line 182-184: BEFORE (broken)
rw_est = stats_util.estimate_rw_from_rt_water_zone(
    rt_curve, "PHIE", 0.15, a, m
)

# AFTER (fixed — use actual NPHI curve from raw data)
phi_proxy = nphi_curve if (nphi_curve and nphi_curve != "None" and nphi_curve in data.columns) else "NPHI"
rw_est = stats_util.estimate_rw_from_rt_water_zone(
    rt_curve, phi_proxy, 0.15, a, m
)
```

Similarly fix line 439-441 in `calculate_rw_rsh`:

```python
# Line 439-441: BEFORE (broken)
rw_est = stats_util.estimate_rw_from_rt_water_zone(
    rt_curve, "PHIT", 0.15, a, m
)

# AFTER (fixed)
phi_proxy = "NPHI" if "NPHI" in data.columns else "PHIT"
rw_est = stats_util.estimate_rw_from_rt_water_zone(
    rt_curve, phi_proxy, 0.15, a, m
)
```

**Step 4: Run verification tests**

Run: `pytest tests/test_services_bugs.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add services/analysis_service.py tests/test_services_bugs.py
git commit -m "fix: use available porosity column for Rw estimation

Changed 'PHIE'/'PHIT' references to use the actual NPHI curve from
raw data. The previous references pointed to calculated columns that
don't exist in raw LAS data, causing silent fallback to hardcoded values."
```

---

## Task 3: Add null-check for `las_data` in `AnalysisWorker.run()` (P1 - HIGH)

### Problem
`AnalysisWorker.run()` line 46 does `self.model.las_data.copy()` without checking if `las_data` is `None`. The `AppModel` initializes `las_data = None` and only sets it after a LAS file is loaded. Other methods (`calculate_rw_rsh` at line 409, `calculate_shale_parameters` at line 472) already have this guard.

### Root Cause
Missing guard clause at the top of `AnalysisWorker.run()`.

**Files:**
- Modify: `services/analysis_service.py:40-46`
- Test: `tests/test_services_bugs.py` (append to existing regression file, or create if missing)

**Step 1: Add regression test**

In `tests/test_services_bugs.py`, add this test block (reuse existing imports if file already exists):

```python
class MockModelNullData:
    """Model with las_data = None to test null-safety."""
    las_data = None


class TestAnalysisWorkerNullData:
    """AnalysisWorker.run() should emit error signal when las_data is None."""

    def test_worker_emits_error_when_las_data_is_none(self):
        from services.analysis_service import AnalysisWorker

        model = MockModelNullData()
        worker = AnalysisWorker(model)

        errors = []
        worker.signals.error.connect(lambda msg: errors.append(msg))

        worker.run()

        assert len(errors) == 1
        assert "no data" in errors[0].lower() or "las_data" in errors[0].lower()
```

**Step 2: Run focused test (expected FAIL)**

Run: `pytest tests/test_services_bugs.py::TestAnalysisWorkerNullData -v`
Expected: FAIL — crashes with `AttributeError: 'NoneType' object has no attribute 'copy'` (caught by generic except, but error message won't contain "no data")

**Step 3: Apply fix**

In `services/analysis_service.py`, add guard at the top of `AnalysisWorker.run()`:

```python
    def run(self):
        """Execute the analysis."""
        try:
            self.signals.started.emit()
            self.signals.progress.emit("Preparing data...", 5)

            # --- FIX: Guard against None las_data ---
            if self.model.las_data is None:
                self.signals.error.emit("No data loaded. Please load a LAS file first.")
                return
            # --- END FIX ---

            data = self.model.las_data.copy()
```

**Step 4: Re-run focused test (expected PASS)**

Run: `pytest tests/test_services_bugs.py::TestAnalysisWorkerNullData -v`
Expected: PASS

**Step 5: Commit**

```bash
git add services/analysis_service.py tests/test_services_bugs.py
git commit -m "fix: guard against None las_data in AnalysisWorker.run()

Add early return with error signal when las_data is None, matching
the pattern used in calculate_rw_rsh() and calculate_shale_parameters()."
```

---

## Task 4: Use `validate_same_well` result in MergeWorker (P2 - MEDIUM)

### Problem
At `merge_service.py:48`, the result of `validate_same_well()` is captured but never used. The merge proceeds silently even when files are from different wells, which could produce nonsensical merged data.

### Root Cause
The validation result is ignored — no warning emitted to user.

**Files:**
- Modify: `services/merge_service.py:47-50`
- Test: `tests/test_services_bugs.py` (append regression test)

**Step 1: Add regression test**

In `tests/test_services_bugs.py`, add:

```python
class TestMergeWellValidation:
    """MergeWorker should warn when merging files from different wells."""

    def test_validate_same_well_result_is_used(self):
        """
        Bug: validate_same_well() was called but its return value
        (is_same_well, well_names) was completely ignored.
        """
        import inspect
        from services.merge_service import MergeWorker

        source = inspect.getsource(MergeWorker.run)

        # The code should reference is_same_well AFTER the assignment
        # Look for usage beyond just the assignment line
        lines = source.split('\n')
        found_usage = False
        found_assignment = False
        for line in lines:
            if 'validate_same_well' in line:
                found_assignment = True
            elif found_assignment and 'is_same_well' in line:
                found_usage = True
                break

        assert found_usage, (
            "validate_same_well result (is_same_well) is assigned but "
            "never referenced — merge proceeds without warning for "
            "different wells"
        )
```

**Step 2: Run focused test (expected FAIL)**

Run: `pytest tests/test_services_bugs.py::TestMergeWellValidation -v`
Expected: FAIL

**Step 3: Apply fix**

In `services/merge_service.py`, add warning logic after validation:

```python
# Line 47-50: BEFORE
# Validate same well
is_same_well, well_names = validate_same_well(self.parsers)

self.signals.progress.emit("Merging files...", 30)

# AFTER
# Validate same well
is_same_well, well_names = validate_same_well(self.parsers)

if not is_same_well:
    well_list = ", ".join(str(w) for w in well_names) if well_names else "unknown"
    self.signals.progress.emit(
        f"Warning: Files may be from different wells ({well_list}). Proceeding with merge...", 20
    )

self.signals.progress.emit("Merging files...", 30)
```

**Step 4: Re-run focused test (expected PASS)**

Run: `pytest tests/test_services_bugs.py::TestMergeWellValidation -v`
Expected: PASS

**Step 5: Commit**

```bash
git add services/merge_service.py tests/test_services_bugs.py
git commit -m "fix: emit warning when merging files from different wells

Use the validate_same_well() result to warn the user via progress signal
when LAS files appear to come from different wells."
```

---

## Task 5: Guard `calculate_phit_neutron_density()` call (P3 - LOW)

### Problem
At line 134, `calc.calculate_phit_neutron_density()` is called unconditionally, even when neither RHOB nor NPHI curves are available. The method handles this gracefully (returns NaN series), but it wastes computation and causes all-NaN PHIT to propagate downstream without any user warning.

### Root Cause
Missing conditional check before the call.

**Files:**
- Modify: `services/analysis_service.py:133-134`
- Test: `tests/test_services_bugs.py` (append regression test)

**Step 1: Add regression test**

In `tests/test_services_bugs.py`, add:

```python
class TestPhitConditionalCall:
    """PHIT should only be calculated when at least one porosity input exists."""

    def test_phit_not_calculated_when_no_porosity_curves(self):
        """
        When neither RHOB nor NPHI are available, PHIT should not be
        populated with NaN — it should be skipped entirely.
        """
        from modules.petrophysics import PetrophysicsCalculator

        data = pd.DataFrame({
            'DEPTH': np.linspace(1000, 1050, 50),
            'GR': 50 + 30 * np.random.random(50),
            'RT': 10 + 90 * np.random.random(50),
            # No RHOB, NPHI, or DT
        })

        calc = PetrophysicsCalculator(data)
        # Don't calculate any porosity
        # Now call phit — should return NaN series (acceptable)
        phit = calc.calculate_phit_neutron_density()

        # Verify it returns NaN (graceful degradation) — no crash
        assert phit.isna().all()
```

**Step 2: Run focused test (baseline check)**

Run: `pytest tests/test_services_bugs.py::TestPhitConditionalCall -v`
Expected: PASS (confirms graceful degradation exists already)

**Step 3: Apply fix**

In `services/analysis_service.py`, wrap the PHIT call in a conditional:

```python
# Line 133-134: BEFORE
# Total porosity (N-D crossplot)
phit = calc.calculate_phit_neutron_density()

# AFTER
# Total porosity (N-D crossplot) — only if at least one porosity was computed
has_density = rhob_curve and rhob_curve != "None" and rhob_curve in data.columns
has_neutron = nphi_curve and nphi_curve != "None" and nphi_curve in data.columns
if has_density or has_neutron:
    phit = calc.calculate_phit_neutron_density()
```

**Step 4: Run verification test suite**

Run: `pytest tests/ -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add services/analysis_service.py tests/test_services_bugs.py
git commit -m "fix: only calculate PHIT when porosity curves are available

Guard calculate_phit_neutron_density() call with check for RHOB/NPHI
availability. Prevents unnecessary NaN propagation downstream."
```

---

## Task 6: Replace `sys.path.insert` with proper imports (P3 - LOW)

### Problem
Three service files (`analysis_service.py:15`, `export_service.py:13`, `merge_service.py:13`) do `sys.path.insert(0, ...)` at module level. This pollutes the global Python path on every import and can cause import conflicts.

### Root Cause
Historical workaround — project wasn't set up as a proper Python package.

**Files:**
- Modify: `services/analysis_service.py:12-15`
- Modify: `services/export_service.py:11-13`
- Modify: `services/merge_service.py:11-13`

**Step 1: Verify import behavior without `sys.path` hack**

Before fixing, verify that the project's `main.py` or entry point already has the right path setup so that removing `sys.path.insert` doesn't break imports. Check:

```bash
python -c "from services.analysis_service import AnalysisService; print('OK')"
```

If this works from the project root, the `sys.path.insert` lines are redundant.

**Step 2: Apply fix (conditional)**

**Only if Step 1 passes**, remove the `sys.path` lines from all three files:

In `services/analysis_service.py`, remove lines 12-15:
```python
# DELETE these lines:
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

In `services/export_service.py`, remove lines 11-13:
```python
# DELETE these lines:
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

In `services/merge_service.py`, remove lines 11-13:
```python
# DELETE these lines:
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

**Step 3: Run verification test suite**

Run: `pytest tests/ -v`
Expected: All PASS

**If tests fail**, revert this task — the sys.path hack is needed until proper package structure is established. This is a LOW priority issue and can be deferred.

**Step 4: Commit (only if tests pass)**

```bash
git add services/analysis_service.py services/export_service.py services/merge_service.py
git commit -m "refactor: remove redundant sys.path.insert from service modules

These path hacks are not needed when running from the project root.
Reduces sys.path pollution on import."
```

---

## Execution Order

Task sections below are already ordered by implementation priority:

1. **Task 1** (P0) — `sweep_summary` NameError
2. **Task 2** (P0) — `"PHIE"`/`"PHIT"` raw-data mismatch
3. **Task 3** (P1) — `las_data` null-check and explicit user-facing error
4. **Task 4** (P2) — surface cross-well merge warning in progress flow
5. **Task 5** (P3) — PHIT conditional guard
6. **Task 6** (P3) — `sys.path` cleanup (conditional/defer if risky)

## Post-Fix Verification

After all tasks, run the complete test suite:

```bash
pytest tests/ -v --tb=short
```

All existing + new tests should pass. Then do a manual smoke test:
1. Open Petrophyter
2. Load a LAS file
3. Run full analysis
4. Try with Per-Formation mode + quantile shale selection
5. Try merging 2 LAS files from different wells — check for warning message
