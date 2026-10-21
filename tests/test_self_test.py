"""``main.py --self-test``: the smoke test the build script and CI run on the frozen exe."""

import os
import subprocess
import sys
from pathlib import Path

from services import self_test

ROOT = Path(__file__).resolve().parents[1]


def test_numeric_steps_pass_in_process():
    assert self_test.step_imports()
    assert self_test.step_lapack()
    assert self_test.step_uncertainty()
    assert self_test.step_pipeline()


def test_synthetic_well_is_deterministic_and_complete():
    a, b = self_test.synthetic_well(), self_test.synthetic_well()
    assert list(a.columns) == ["DEPTH", "GR", "RHOB", "NPHI", "DT", "RT"]
    assert len(a) == 100 and a.equals(b)


def test_runner_reports_the_failing_step_and_exits_non_zero(tmp_path, capsys):
    def boom():
        raise RuntimeError("no LAPACK")

    log = tmp_path / "st.log"
    code = self_test.run(str(log), steps=[("first", lambda: "fine"), ("second", boom), ("third", lambda: "x")])
    text = log.read_text(encoding="utf-8")
    assert code == 1
    assert "[self-test] first: ok" in text
    assert "[self-test] second: FAILED (RuntimeError: no LAPACK)" in text
    assert "third" not in text
    assert text.strip().splitlines()[-1] == f"{self_test.FAIL_LINE}: second"
    assert "SELFTEST FAILED: second" in capsys.readouterr().out


def test_runner_writes_ok_line(tmp_path):
    log = tmp_path / "st.log"
    assert self_test.run(str(log), steps=[("only", lambda: "fine")]) == 0
    assert log.read_text(encoding="utf-8").strip().splitlines()[-1] == self_test.OK_LINE


def test_cli_parses_the_log_path(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(self_test, "run", lambda log_path=None, steps=None: seen.setdefault("log", log_path) and 0)
    self_test.run_cli(["--self-test", "--self-test-log", "x.log"])
    assert seen["log"] == "x.log"


def test_main_self_test_runs_end_to_end(tmp_path):
    """Real process: offscreen window, pipeline, exit 0, log file written, user settings untouched."""
    log = tmp_path / "selftest.log"
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)  # main.py must set it itself
    proc = subprocess.run(
        [sys.executable, str(ROOT / "main.py"), "--self-test", "--self-test-log", str(log)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=180,
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    for step in ("imports", "lapack", "pipeline", "main window"):
        assert f"[self-test] {step}: ok" in proc.stdout, out
    assert log.read_text(encoding="utf-8").strip().splitlines()[-1] == self_test.OK_LINE


def test_build_script_and_ci_run_the_gate():
    script = (ROOT / "scripts" / "build-installer.ps1").read_text(encoding="utf-8")
    assert "-SkipTests" in script
    assert "RELEASE" in script and "python -m pytest -q -rs" in script
    assert "--self-test" in script and "--self-test-log" in script
    for name in ("pip-freeze.txt", "conda-explicit.txt", "SHA256SUMS.txt"):
        assert name in script
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "requirements-lock.txt" in ci and "--self-test" in ci and "RELEASE" in ci
    spec = (ROOT / "petrophyter_pyqt_2.spec").read_text(encoding="utf-8")
    assert "collect_all('pyqtgraph')" in spec
    assert "try:\n    pg_datas" not in spec.replace("\r\n", "\n")
