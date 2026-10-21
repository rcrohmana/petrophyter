"""Smoke test of a built Petrophyter: ``Petrophyter.exe --self-test``.

The build script and CI run this against the frozen application. It proves, in
about a second, what a plain launch cannot: the numeric stack imports, a LAPACK
routine runs (the v1.7.0 crash was in scipy's LAPACK on a PC without Anaconda),
the main window builds, and the pipeline runs on a small synthetic well.

Rules:

- one line per step, ``ok`` or ``FAILED``; the exit code is 0 only if every step passed;
- no dialog is shown and the user's QSettings are never touched (they point at a
  temp folder);
- the frozen exe has no console, so every line is also written to ``log_path``
  (flushed per line, so a hard crash still shows the step that was running).

This module must not import ``tests``: the frozen app does not contain it.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Callable, List, Optional, Tuple

FLAG = "--self-test"
LOG_FLAG = "--self-test-log"
OK_LINE = "SELFTEST OK"
FAIL_LINE = "SELFTEST FAILED"

_FULL_MAPPING = {"GR": "GR", "RHOB": "RHOB", "NPHI": "NPHI", "DT": "DT", "RT": "RT"}


def synthetic_well(n_samples: int = 100):
    """Return a small deterministic log DataFrame (a clean-ish sand/shale section)."""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(42)
    depth = np.linspace(1000.0, 1100.0, n_samples)
    return pd.DataFrame(
        {
            "DEPTH": depth,
            "GR": 50 + 30 * rng.random(n_samples) + 20 * np.sin(depth / 10),
            "RHOB": 2.3 + 0.2 * rng.random(n_samples),
            "NPHI": 0.2 + 0.1 * rng.random(n_samples),
            "DT": 80 + 20 * rng.random(n_samples),
            "RT": 10 + 90 * rng.random(n_samples),
        }
    )


# ---------------------------------------------------------------- steps


def step_imports() -> str:
    import lasio
    import matplotlib
    import numpy
    import openpyxl
    import OpenGL
    import pandas
    import pyqtgraph
    import scipy

    return (
        f"numpy {numpy.__version__}, scipy {scipy.__version__}, pandas {pandas.__version__}, "
        f"matplotlib {matplotlib.__version__}, lasio {lasio.__version__}, "
        f"openpyxl {openpyxl.__version__}, pyqtgraph {pyqtgraph.__version__}, "
        f"PyOpenGL {OpenGL.__version__}"
    )


def step_lapack() -> str:
    """Call LAPACK through scipy and numpy; a missing MKL library aborts here."""
    import numpy as np
    from scipy import linalg, optimize

    a = np.array([[4.0, 1.0, 0.0], [1.0, 3.0, 1.0], [0.0, 1.0, 2.0]])
    b = np.array([1.0, 2.0, 3.0])
    x = linalg.solve(a, b)
    if not np.allclose(a @ x, b):
        raise RuntimeError("scipy.linalg.solve returned a wrong answer")
    sv = np.linalg.svd(a, compute_uv=False)
    if not np.all(np.isfinite(sv)):
        raise RuntimeError("numpy.linalg.svd returned non-finite values")
    t = np.linspace(0.0, 1.0, 20)
    popt, _ = optimize.curve_fit(lambda t_, k: np.exp(-k * t_), t, np.exp(-2.0 * t), p0=[1.0])
    if abs(popt[0] - 2.0) > 1e-6:
        raise RuntimeError("scipy.optimize.curve_fit returned a wrong answer")
    return "scipy.linalg.solve, numpy.linalg.svd, scipy.optimize.curve_fit"


def step_uncertainty() -> str:
    """The Monte Carlo module imports and the Latin hypercube sampler (scipy.stats.qmc) runs."""
    import modules.uncertainty  # noqa: F401
    from scipy.stats import qmc

    draw = qmc.LatinHypercube(d=2, seed=1).random(4)
    if draw.shape != (4, 2):
        raise RuntimeError(f"unexpected Latin hypercube shape {draw.shape}")
    return "qmc LatinHypercube ok"


def step_shf() -> str:
    """The saturation-height stack imports, a robust Leverett J fit (scipy least_squares) runs and Sw(h) evaluates."""
    import numpy as np

    import modules.pc_handler  # noqa: F401
    import modules.shf_stage  # noqa: F401
    import services.shf_service  # noqa: F401
    from modules.shf import STATUS_OK, PcCurve, fit_core_pc, leverett_j, sw_shf

    pc = np.array([5.0, 10.0, 20.0, 50.0, 100.0])
    curves = []
    for k, phi in ((50.0, 0.18), (200.0, 0.24), (10.0, 0.14)):
        sw = np.clip(0.25 * leverett_j(pc, k, phi, 72.0) ** -0.6, 0.0, 1.0)
        curves.append(PcCurve(pc_psi=pc, sw=sw, k_md=k, phi=phi, sigma_cos_lab=72.0))
    fit = fit_core_pc(curves, "All")
    if fit.status != STATUS_OK or not fit.params:
        raise RuntimeError(f"saturation-height fit failed: {fit.status} {fit.message}")
    sw = sw_shf(np.array([-5.0, 20.0, 200.0]), 100.0, 0.2, fit, 0.4, 26.0)
    if not (sw[0] == 1.0 and 0.0 < sw[2] < sw[1] <= 1.0):
        raise RuntimeError(f"unexpected Sw from height {sw}")
    return "Leverett J fit ok"


def step_pipeline() -> str:
    from modules.pipeline import run_pipeline

    results, summary = run_pipeline(synthetic_well(), dict(_FULL_MAPPING), {})
    if len(results) == 0 or not summary:
        raise RuntimeError("the pipeline returned no results")
    return f"{len(results)} rows, {len(results.columns)} columns"


def _resource_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) if base else Path(__file__).resolve().parent.parent


def step_window() -> str:
    """Build the main window offscreen with throwaway QSettings, then close it."""
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication

    settings_dir = tempfile.mkdtemp(prefix="petrophyter_selftest_")
    try:
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(
            QSettings.Format.IniFormat, QSettings.Scope.UserScope, settings_dir
        )
        app = QApplication.instance() or QApplication(sys.argv[:1])
        app.setStyle("Fusion")

        from themes import ThemeManager
        from ui.main_window import MainWindow

        icons_dir = str(_resource_dir() / "icons").replace("\\", "/")
        theme_manager = ThemeManager(app, icons_dir)
        theme_manager.set_theme("light")
        window = MainWindow(theme_manager)
        window.show()
        app.processEvents()
        platform = app.platformName()
        window.close()
        app.processEvents()
        window.deleteLater()
        app.processEvents()
        return f"main window built on the '{platform}' platform"
    finally:
        shutil.rmtree(settings_dir, ignore_errors=True)


STEPS: List[Tuple[str, Callable[[], str]]] = [
    ("imports", step_imports),
    ("lapack", step_lapack),
    ("uncertainty", step_uncertainty),
    ("saturation-height", step_shf),
    ("pipeline", step_pipeline),
    ("main window", step_window),
]


# ---------------------------------------------------------------- runner


def run(log_path: Optional[str] = None, steps=None) -> int:
    """Run every step; return 0 if all passed, 1 otherwise."""
    log_file = None
    if log_path:
        try:
            log_file = open(log_path, "w", encoding="utf-8")
        except OSError:
            log_file = None

    def emit(line: str) -> None:
        for stream in (sys.stdout, log_file):
            if stream is None:
                continue
            try:
                stream.write(line + "\n")
                stream.flush()
            except Exception:
                pass

    failed: Optional[str] = None
    try:
        for name, func in steps if steps is not None else STEPS:
            emit(f"[self-test] {name} ...")
            try:
                detail = func()
            except BaseException as exc:  # a failed import must not escape as a dialog
                emit(f"[self-test] {name}: FAILED ({type(exc).__name__}: {exc})")
                for line in traceback.format_exc().rstrip().splitlines():
                    emit("    " + line)
                failed = name
                break
            emit(f"[self-test] {name}: ok ({detail})")
        emit(f"{FAIL_LINE}: {failed}" if failed else OK_LINE)
    finally:
        if log_file is not None:
            log_file.close()
    return 1 if failed else 0


def run_cli(argv) -> int:
    """Entry for ``main.py --self-test [--self-test-log PATH]``."""
    log_path = None
    if LOG_FLAG in argv:
        i = argv.index(LOG_FLAG)
        if i + 1 < len(argv):
            log_path = argv[i + 1]
    return run(log_path)
