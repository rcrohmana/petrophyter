# -*- mode: python ; coding: utf-8 -*-
# Petrophyter PyQt - Optimized PyInstaller spec file
# Reduced size by excluding unused Qt modules (Qt3D, QML, WebEngine, SQL, etc.)

from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

block_cipher = None

# =============================================================================
# SELECTIVE COLLECTION (instead of collect_all which includes everything)
# =============================================================================

# Matplotlib - collect data but will exclude tests via excludes list
mpl_datas, mpl_binaries, mpl_hiddenimports = collect_all('matplotlib')

# pyqtgraph (optional but used for interactive plots)
try:
    pg_datas, pg_binaries, pg_hiddenimports = collect_all('pyqtgraph')
except Exception:
    pg_datas, pg_binaries, pg_hiddenimports = [], [], []

# lasio for LAS file parsing
try:
    lasio_datas, lasio_binaries, lasio_hiddenimports = collect_all('lasio')
except Exception:
    lasio_datas, lasio_binaries, lasio_hiddenimports = [], [], []

# =============================================================================
# ANALYSIS
# =============================================================================

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=mpl_binaries + pg_binaries + lasio_binaries,
    datas=[
        ('icons', 'icons'),  # Include icons folder
    ] + mpl_datas + pg_datas + lasio_datas,
    hiddenimports=[
        # PyQt6 core modules only (what we actually use)
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtSvg',
        'PyQt6.QtOpenGL',         # Required by pyqtgraph
        'PyQt6.QtOpenGLWidgets',  # Required by pyqtgraph (QOpenGLWidget)
        'PyQt6.sip',
        
        # Matplotlib backends
        'matplotlib.backends.backend_qtagg',
        'matplotlib.backends.backend_qt',
        'matplotlib.figure',
        
        # Data processing
        'pandas',
        'pandas._libs',
        'pandas._libs.tslibs',
        'numpy',
        'numpy.core',
        'scipy',
        'scipy.optimize',
        'scipy.stats',
        'scipy.interpolate',
        'scipy.special',
        
        # File handling
        'openpyxl',
        'lasio',
        
        # pyqtgraph components
        'pyqtgraph',
        'pyqtgraph.graphicsItems',
        'pyqtgraph.widgets',
        'pyqtgraph.Qt',
        
        # OpenGL for pyqtgraph GPU acceleration
        'OpenGL',
        'OpenGL.GL',
        'OpenGL.platform',
        'OpenGL.platform.win32',
    ] + mpl_hiddenimports + pg_hiddenimports + lasio_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # =========================================================
        # EXCLUDE UNUSED PYTHON FRAMEWORKS
        # =========================================================
        'tkinter',
        '_tkinter',
        'PyQt5',
        'PySide2',
        'PySide6',
        
        # =========================================================
        # EXCLUDE UNUSED QT MODULES - Major size reduction
        # =========================================================
        
        # Qt 3D - NOT USED (saves ~50MB)
        'PyQt6.Qt3DAnimation',
        'PyQt6.Qt3DCore',
        'PyQt6.Qt3DExtras',
        'PyQt6.Qt3DInput',
        'PyQt6.Qt3DLogic',
        'PyQt6.Qt3DRender',
        
        # QML/Quick - NOT USED (saves ~30MB)
        'PyQt6.QtQml',
        'PyQt6.QtQmlCore',
        'PyQt6.QtQmlModels',
        'PyQt6.QtQmlWorkerScript',
        'PyQt6.QtQuick',
        'PyQt6.QtQuick3D',
        'PyQt6.QtQuickControls2',
        'PyQt6.QtQuickWidgets',
        
        # WebEngine - NOT USED (saves ~200MB!)
        'PyQt6.QtWebEngine',
        'PyQt6.QtWebEngineCore',
        'PyQt6.QtWebEngineWidgets',
        'PyQt6.QtWebChannel',
        'PyQt6.QtWebSockets',
        'PyQt6.QtWebView',
        
        # Database - NOT USED
        'PyQt6.QtSql',
        
        # Multimedia - NOT USED
        'PyQt6.QtMultimedia',
        'PyQt6.QtMultimediaWidgets',
        
        # Network - NOT USED (confirmed by user)
        'PyQt6.QtNetwork',
        'PyQt6.QtNetworkAuth',
        
        # Print Support - NOT USED (no PDF export)
        'PyQt6.QtPrintSupport',
        
        # Other unused Qt modules
        'PyQt6.QtBluetooth',
        'PyQt6.QtNfc',
        'PyQt6.QtSensors',
        'PyQt6.QtPositioning',
        'PyQt6.QtLocation',
        'PyQt6.QtRemoteObjects',
        'PyQt6.QtSerialPort',
        'PyQt6.QtSerialBus',
        'PyQt6.QtTest',
        'PyQt6.QtTextToSpeech',
        'PyQt6.QtDesigner',
        'PyQt6.QtHelp',
        # NOTE: PyQt6.QtOpenGL and PyQt6.QtOpenGLWidgets are REQUIRED by pyqtgraph
        # Do NOT exclude them or you'll get: "QOpenGLWidget is not available" error
        'PyQt6.QtPdf',
        'PyQt6.QtPdfWidgets',
        'PyQt6.QtSpatialAudio',
        'PyQt6.QtStateMachine',
        'PyQt6.QtSvgWidgets',     # Keep QtSvg, but SvgWidgets not needed
        'PyQt6.QtXml',
        'PyQt6.QtDBus',
        'PyQt6.QtCharts',
        'PyQt6.QtDataVisualization',
        'PyQt6.QtScxml',
        'PyQt6.QtVirtualKeyboard',
        
        # =========================================================
        # EXCLUDE MATPLOTLIB TESTS - NOT NEEDED AT RUNTIME
        # =========================================================
        'matplotlib.tests',
        'matplotlib.testing',
        
        # =========================================================
        # EXCLUDE DEVELOPMENT/TESTING TOOLS
        # =========================================================
        'IPython',
        'jupyter',
        'jupyter_client',
        'jupyter_core',
        'jupyter_rfb',
        'notebook',
        'pytest',
        'pytest_cov',
        'sphinx',
        'docutils',
        'pylint',
        'mypy',
        'black',
        'flake8',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# =============================================================================
# POST-ANALYSIS: Filter out unwanted binaries/plugins from Qt
# =============================================================================

# Qt plugin directories we don't need
unwanted_plugins = [
    'geometryloaders',      # Qt3D geometry
    'renderers',            # Qt3D renderers
    'sceneparsers',         # Qt3D scene parsers
    'qmllint',              # QML linting
    'qmlls',                # QML language server
    'webview',              # WebEngine
    'scxmldatamodel',       # State machine XML
    'sqldrivers',           # Database drivers (Oracle, PostgreSQL, etc.)
    'designer',             # Qt Designer plugins
    'multimedia',           # Multimedia plugins
    'networkinformation',   # Network info
    'tls',                  # TLS/SSL (no network)
    'position',             # Positioning
]

# DLL patterns to exclude
unwanted_dlls = [
    'qt63d',            # Qt 3D
    'qt6qml',           # QML
    'qt6quick',         # Quick
    'qt6web',           # WebEngine
    'qt6designer',      # Designer
    'qt6multimedia',    # Multimedia
    'qt6network',       # Network
    'qt6sql',           # SQL
    'qt6bluetooth',     # Bluetooth
    'qt6nfc',           # NFC
    'qt6sensors',       # Sensors
    'qt6serialport',    # Serial
    'qt6test',          # Test
    'qt6scxml',         # State machine
    'qt6pdf',           # PDF
    'qt6print',         # Print
    'qt6texttospeech',  # TTS
    'qt6virtualkeyboard',
    'qt6remoteobjects',
    'qt6positioning',
    'qt6charts',
    'qt6datavis',
]

def should_exclude_binary(name):
    """Check if a binary/plugin should be excluded."""
    name_lower = name.lower()
    
    # Check plugin directories
    for plugin in unwanted_plugins:
        if plugin in name_lower:
            return True
    
    # Check DLL patterns
    for dll in unwanted_dlls:
        if dll in name_lower:
            return True
    
    return False

def should_exclude_data(name):
    """Check if a data file should be excluded."""
    name_lower = name.lower()
    
    # Exclude QML files
    if '.qml' in name_lower or '/qml/' in name_lower or '\\qml\\' in name_lower:
        return True
    
    # Exclude Qt translations we don't need
    for pattern in ['qt_designer', 'qt_help', 'qtwebengine', 'qtmultimedia']:
        if pattern in name_lower:
            return True
    
    # Check plugin directories
    for plugin in unwanted_plugins:
        if plugin in name_lower:
            return True
    
    return False

# Filter binaries - remove unwanted Qt plugins and DLLs
a.binaries = [b for b in a.binaries if not should_exclude_binary(b[0])]

# Filter datas - remove unwanted QML files, translations, etc.
a.datas = [d for d in a.datas if not should_exclude_data(d[0])]

# =============================================================================
# BUILD EXECUTABLES
# =============================================================================

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
    icon='icons/app_icon.ico',  # Windows application icon
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
