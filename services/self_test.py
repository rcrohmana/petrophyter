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


def step_lrlc() -> str:
    """The LRLC stack imports; a Pickett fit recovers Archie's m, RT_CUT, the laminated-sand Rt and the estimated Qv match their closed forms, Sw with constant m and n arrays equals the scalar result, an invasion round trip recovers Rt, Rxo and the diameter, the Shell m model is refused outside carbonate zones, BibTeX renders and the Rt chain runs."""
    import numpy as np
    import pandas as pd

    import modules.lrlc.chain as chain
    import modules.lrlc.movable  # noqa: F401
    import modules.lrlc.screening  # noqa: F401
    from modules.lrlc.pickett import fit_pickett
    from modules.lrlc.rt_cutoff import SwInputs, rt_cutoff
    from modules.param_scopes import UNZONED
    from modules.references import to_bibtex_all

    # Pickett: synthetic Archie wet line (m = 2, a = 1, Rw = 0.05) with small deterministic noise
    # and a few resistive outliers that the Huber fit must shrug off.
    rng = np.random.default_rng(7)
    phi = np.geomspace(0.08, 0.35, 40)
    rt = 0.05 / phi ** 2.0 * 10.0 ** rng.normal(0.0, 0.01, phi.size)
    rt[[3, 17, 29]] *= 3.0
    fit = fit_pickett(phi, rt, np.ones(phi.size, dtype=bool), a=1.0, m_current=2.0)
    if fit.status != "ok" or abs(fit.m - 2.0) > 0.04:
        raise RuntimeError(f"Pickett fit failed: {fit.status}, m = {fit.m:.3f}")

    # Rt cutoff: the Archie closed form a Rw / (PHIE^m Sw^n) at Sw = 0.5 is 5 ohm.m for PHIE = 0.2.
    index = pd.RangeIndex(3)
    inputs = SwInputs(phie=0.2, phit=0.2, vsh=0.1, rw_eff=0.05, rsh_eff=2.0, rwb_eff=0.05,
                      ws_b=1.0, a=1.0, m=2.0, n=2.0, ws_qv=0.0, dw_swb=0.0)
    cut, _n_eligible, n_no_root = rt_cutoff("Archie", inputs, 0.5, index)
    if n_no_root or not np.allclose(cut, 5.0, rtol=1e-6):
        raise RuntimeError(f"RT_CUT {cut} does not match the Archie closed form 5.0")

    if not to_bibtex_all().strip():
        raise RuntimeError("the reference registry rendered no BibTeX")

    # Rt chain with a local identity step (a StepSpec that is never registered globally).
    def identity(rt_in, _ctx, _params):
        return chain.StepResult(rt_out=rt_in.copy(), valid_mask=np.isfinite(rt_in))

    spec = chain.StepSpec(name="selftest_identity", order=1, column="RT_ID", fn=identity,
                          label="Identity", description="SELF TEST IDENTITY", refs=())
    rt_in = np.array([2.0, 5.0, 20.0, np.nan])
    arrays = {"depth": np.arange(4.0), "vsh": np.full(4, 0.2), "phit": np.full(4, 0.2),
              "phie": np.full(4, 0.2), "rsh": np.full(4, 2.0), "rw": np.full(4, 0.05)}
    lrlc = {"resolved": {"default": {"rt_steps": ["selftest_identity"], "rt_fallback": "nan"},
                         "zones": {}}}
    # apply_rt_chain resolves step names through the registry, so the spec is present only
    # for this call and the registry is restored afterwards.
    saved = dict(chain.STEPS)
    chain.STEPS["selftest_identity"] = spec
    try:
        out = chain.apply_rt_chain(rt_in, arrays, np.array([UNZONED] * 4, dtype=object), lrlc, False)
    finally:
        chain.STEPS.clear()
        chain.STEPS.update(saved)
    if "selftest_identity" in chain.STEPS:
        raise RuntimeError("the local step leaked into the registry")
    if not np.array_equal(out.rt_sw, rt_in, equal_nan=True):
        raise RuntimeError("the identity Rt chain changed the resistivity")
    if not out.write_rt_sw or "RT_ID" not in out.columns:
        raise RuntimeError("the Rt chain did not write its columns")

    # Laminated sand: Rt 5 ohm.m with 30 percent laminar shale of 2 ohm.m gives 14 ohm.m sand
    # (parallel conductance); an estimated Qv of 25 meq/100 g clay at Vsh 0.15, PHIT 0.20 is 0.3975.
    from modules.lrlc.laminated import hagiwara_rt
    from modules.lrlc.qv import estimate_qv

    sand, valid, _counts = hagiwara_rt(np.array([5.0]), 0.3, 2.0, 0.3, 0.8, 0.8, 0.95)
    if not valid[0] or abs(sand[0] - 14.0) > 1e-9:
        raise RuntimeError(f"laminated-sand Rt {sand} does not match the closed form 14.0")
    qv_est, _qv_counts = estimate_qv(np.array([0.15]), np.array([0.20]), 25.0, 2.65, 0.03, 3.0)
    if abs(qv_est[0] - 0.3975) > 1e-9:
        raise RuntimeError(f"estimated Qv {qv_est} does not match the closed form 0.3975")

    # Sw with constant m and n arrays must equal the scalar result exactly (Archie and Simandoux).
    from modules.petrophysics import PetrophysicsCalculator

    frame = pd.DataFrame({"RT": np.array([4.0, 12.0, 30.0, 80.0])})
    calc = PetrophysicsCalculator(frame)
    phie = pd.Series([0.12, 0.18, 0.22, 0.25])
    vsh = pd.Series([0.30, 0.20, 0.10, 0.05])
    m_arr, n_arr = np.full(4, 2.1), np.full(4, 1.8)
    for label, scalar, array in (
        ("Archie", calc.calculate_sw_archie("RT", phie, 0.05, 1.0, 2.1, 1.8),
         calc.calculate_sw_archie("RT", phie, 0.05, 1.0, m_arr, n_arr)),
        ("Simandoux", calc.calculate_sw_simandoux("RT", phie, vsh, 0.05, 2.0, 1.0, 2.1, 1.8),
         calc.calculate_sw_simandoux("RT", phie, vsh, 0.05, 2.0, 1.0, m_arr, n_arr)),
    ):
        if not np.array_equal(np.asarray(scalar), np.asarray(array), equal_nan=True):
            raise RuntimeError(f"{label} Sw with m and n arrays differs from the scalar result")

    # Invasion round trip: the generic induction tool at di = 40 in reads 8.5034, 4.1303 and
    # 2.3127 ohm.m over Rt 20 and Rxo 2 ohm.m; inverting those three readings returns the profile.
    from modules.lrlc.invasion import GENERIC_TOOLS, fit_invasion, forward_ra

    tool = GENERIC_TOOLS["generic_induction"]
    r50 = (tool["deep"], tool["medium"], tool["shallow"])
    ra = forward_ra(np.array([20.0]), np.array([2.0]), np.array([40.0]), r50, tool["p"])[0]
    if not np.allclose(ra, [8.5034, 4.1303, 2.3127], atol=5e-5):
        raise RuntimeError(f"invasion forward model {ra} does not match the worked readings")
    inv = fit_invasion(ra[0], rm=ra[1], rs=ra[2], r50=r50, p=tool["p"])
    got = (inv.rt[0], inv.rxo[0], inv.di[0])
    if not (inv.valid[0] and np.allclose(got, [20.0, 2.0, 40.0], rtol=1e-6)):
        raise RuntimeError(f"invasion round trip returned Rt, Rxo, di = {got}")

    # Shell gate: the Shell m model is refused (scoped m kept) in a zone that is not carbonate
    # unless confirmed, and evaluated (m = 2.06 at porosity 0.10) in a carbonate zone.
    from modules.lrlc.variable_mn import build_mn_curves

    shell = {"Z": {"mn_mode": "curve", "m_model": "shell", "m_coef": [2.15, 0.0, 0.0, 0.0],
                   "shell_confirm": False, "n_model": "constant", "n_coef": [2.0, 0.0]}}
    labels = np.array(["Z"], dtype=object)
    args = (np.array([0.10]), np.array([0.0]), labels, shell, 2.15, 2.0, (1.0, 4.0), (1.0, 4.0))
    refused = build_mn_curves(*args, "Sandstone (Humble)")
    allowed = build_mn_curves(*args, "Carbonate")
    if refused.m[0] != 2.15 or refused.m_valid[0]:
        raise RuntimeError(f"Shell m was not refused outside a carbonate zone: {refused.m}")
    if abs(allowed.m[0] - 2.06) > 1e-9:
        raise RuntimeError(f"Shell m {allowed.m} does not match the closed form 2.06")
    return (f"Pickett m = {fit.m:.3f}, RT_CUT = {cut[0]:.3f} ohm.m, laminated Rt = {sand[0]:.1f} "
            f"ohm.m, Qv = {qv_est[0]:.4f} meq/mL, m/n arrays = scalars, invasion Rt = {got[0]:.2f} "
            f"ohm.m, Shell gate ok, chain ok")


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
    ("lrlc", step_lrlc),
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
