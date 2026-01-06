# -*- mode: python ; coding: utf-8 -*-
# Petrophyter PyQt - PyInstaller spec file

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# Collect all PyQt6 components
pyqt6_datas, pyqt6_binaries, pyqt6_hiddenimports = collect_all('PyQt6')

# Collect matplotlib backend
mpl_datas, mpl_binaries, mpl_hiddenimports = collect_all('matplotlib')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=pyqt6_binaries + mpl_binaries,
    datas=[
        ('icons', 'icons'),  # Include icons folder
    ] + pyqt6_datas + mpl_datas,
    hiddenimports=[
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui', 
        'PyQt6.QtWidgets',
        'PyQt6.QtSvg',
        'PyQt6.sip',
        'matplotlib.backends.backend_qtagg',
        'matplotlib.backends.backend_qt',
        'matplotlib.figure',
        'pandas',
        'numpy',
        'scipy',
        'scipy.optimize',
        'scipy.stats',
        'openpyxl',
    ] + pyqt6_hiddenimports + mpl_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PyQt5', 'PySide2', 'PySide6'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# One-folder mode (recommended for faster startup)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Petrophyter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window (windowed mode)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icons/app_icon.ico',  # Uncomment if you have .ico file
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Petrophyter',
)
