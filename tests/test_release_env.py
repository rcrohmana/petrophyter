"""Release environment checks. These tests must never skip.

With ``RELEASE=1`` (build gate, CI) ``tests/conftest.py`` turns any skipped test
into a failure, so a missing optional package cannot hide in a release build.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_interactive_log_engine_packages_import():
    import OpenGL
    import pyqtgraph

    assert pyqtgraph.__version__
    assert OpenGL.__version__


def _run_pytest(tmp_path, release):
    """Run a tiny test module (one skip, one pass) under the real RELEASE hook."""
    (tmp_path / "conftest.py").write_text(
        "from tests.conftest import pytest_make_collect_report, pytest_runtest_makereport\n",
        encoding="utf-8",
    )
    (tmp_path / "test_tiny.py").write_text(
        textwrap.dedent(
            """
            import pytest

            def test_passes():
                pass

            @pytest.mark.skip(reason="optional package missing")
            def test_skipped():
                pass
            """
        ),
        encoding="utf-8",
    )
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    env.pop("RELEASE", None)
    if release:
        env["RELEASE"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist",
         "--rootdir", str(tmp_path), "-c", str(tmp_path / "pytest.ini"), str(tmp_path)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )


def test_release_flag_turns_a_skip_into_a_failure(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    proc = _run_pytest(tmp_path, release=True)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, out
    assert "skipped" not in out.splitlines()[-1], out  # a mark skip is reported at setup
    assert "1 passed" in out and ("1 error" in out or "1 failed" in out), out
    assert "optional package missing" in out, out


def test_without_release_flag_a_skip_stays_a_skip(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    proc = _run_pytest(tmp_path, release=False)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "1 skipped" in out and "1 passed" in out, out
