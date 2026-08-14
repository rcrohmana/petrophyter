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


def test_spec_collects_conda_mkl_forwarder_target_when_available():
    source = (ROOT / "petrophyter_pyqt_2.spec").read_text(encoding="utf-8")

    assert 'os.path.join(sys.prefix, "Library", "bin", "mkl_rt.3.dll")' in source
    assert "+ mkl_binaries" in source


def test_installer_registry_follows_selected_install_mode():
    source = (ROOT / "installer" / "Petrophyter.iss").read_text(encoding="utf-8")

    assert "Root: HKA;" in source
    assert "Root: HKLM;" not in source
