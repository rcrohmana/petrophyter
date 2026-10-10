import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_build_uses_pyinstaller_from_selected_conda_python():
    source = (ROOT / "scripts" / "build-installer.ps1").read_text(encoding="utf-8")

    assert (
        "conda run -n $CondaEnv --no-capture-output python -m PyInstaller"
        in source
    )
    assert "--no-capture-output pyinstaller" not in source


def test_spec_excludes_stale_msvc_runtime_from_qt_bin():
    source = (ROOT / "petrophyter_pyqt_2.spec").read_text(encoding="utf-8")

    assert '"pyqt6/qt6/bin/"' in source
    assert 'filename.startswith(("msvcp140", "vcruntime140"))' in source


def test_spec_bundles_the_mkl_runtime_libraries():
    # libblas/liblapack forward to mkl_rt, which loads these at run time; any
    # MKL major version (mkl_rt.2 / mkl_rt.3) must match.
    source = (ROOT / "petrophyter_pyqt_2.spec").read_text(encoding="utf-8")

    for pattern in ("mkl_rt.*.dll", "mkl_core.*.dll", "mkl_sequential.*.dll",
                    "mkl_def.*.dll", "mkl_mc3.*.dll", "mkl_avx2.*.dll", "mkl_avx512.*.dll"):
        assert f'"{pattern}"' in source, pattern
    assert "+ mkl_binaries" in source
    assert "runtime_hooks=['installer/rth_mkl_sequential.py']" in source


def test_mkl_runtime_hook_selects_the_sequential_layer(monkeypatch):
    monkeypatch.delenv("MKL_THREADING_LAYER", raising=False)
    hook = ROOT / "installer" / "rth_mkl_sequential.py"
    exec(compile(hook.read_text(encoding="utf-8"), str(hook), "exec"), {})
    assert os.environ["MKL_THREADING_LAYER"] == "SEQUENTIAL"


def test_installer_registry_follows_selected_install_mode():
    source = (ROOT / "installer" / "Petrophyter.iss").read_text(encoding="utf-8")

    assert "Root: HKA;" in source
    assert "Root: HKLM;" not in source
