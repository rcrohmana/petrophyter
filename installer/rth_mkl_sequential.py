# PyInstaller runtime hook: runs before main.py in the frozen app.
# Select MKL's sequential threading layer, so the bundled mkl_sequential DLL
# is used and mkl_intel_thread/libiomp5md do not have to ship.
import os

os.environ.setdefault("MKL_THREADING_LAYER", "SEQUENTIAL")
