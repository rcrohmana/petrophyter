"""Synthetic deviated wells for the depth, temperature and saturation-height notes.

One well, three LAS files. The well is vertical to a kick-off, builds 3 degrees per 100 ft
up to 35 degrees and holds. Measured depth (MD) runs 4800 to 7500 ft, so MD minus TVD grows
to a little over 300 ft at the bottom.

    SYNTH_DEVIATED_1_header.las     ``MDEV`` in the parameter section, no inclination curve, no TVD
    SYNTH_DEVIATED_2_incl.las       inclination curve ``DEVI``, no TVD
    SYNTH_DEVIATED_3_incl_tvd.las   the same curve plus ``TVD`` (cumulative sum of
                                    cos(inclination) x step, vertical above the log top)

The earth model is defined in TVD: shale to 6200 ft, then sand with a hydrocarbon column
above a free water level at 6700 ft TVD and a water leg below it, so a saturation-height
run makes sense. Run from the repository root::

    python -m tests.synth_deviated <folder>

which writes the three files and ``SYNTH_DEVIATED_README.txt`` into ``<folder>``.
"""

import os
import sys
from typing import Dict

import numpy as np

SEED = 20261115
NULL = -999.25
STEP_FT = 0.5
TOP_MD_FT = 4800.0
BOTTOM_MD_FT = 7500.0
KICK_OFF_MD_FT = 5000.0
BUILD_DEG_PER_100_FT = 3.0
HOLD_DEG = 35.0

SHALE_BASE_TVD_FT = 6200.0          # shale above, sand below
FWL_TVD_FT = 6700.0                 # free water level of the model
RW, RSH = 0.05, 2.5
PHI_SAND = 0.22
README_NAME = "SYNTH_DEVIATED_README.txt"
FILE_NAMES = ("SYNTH_DEVIATED_1_header.las", "SYNTH_DEVIATED_2_incl.las",
              "SYNTH_DEVIATED_3_incl_tvd.las")
HEADER_DEVIATION_NOTE = (
    "The header has an inclination/deviation entry (maximum deviation 35 degrees) but no TVD "
    "curve is mapped; {noun} assume a vertical well.")
CURVE_DEVIATION_NOTE = (
    "Curve DEVI reads up to 35 degrees, so the well looks deviated, but no TVD curve is "
    "mapped; {noun} assume a vertical well. Map a TVD curve in Curve Mapping.")
README_DEPTH_MD_FT = 6500.0         # the depth the README compares the two heights at


def inclination_deg(md) -> np.ndarray:
    """Inclination along the well: vertical to the kick-off, 3 deg/100 ft build, then hold."""
    md = np.asarray(md, dtype=float)
    return np.clip((md - KICK_OFF_MD_FT) * BUILD_DEG_PER_100_FT / 100.0, 0.0, HOLD_DEG)


def tvd_ft(md) -> np.ndarray:
    """TVD of a measured depth: cumulative sum of cos(inclination) x step from the log top.

    The well is vertical above the log top, so TVD there equals MD. ``md`` must be sampled
    on the ``STEP_FT`` grid of the log.
    """
    md = np.asarray(md, dtype=float)
    step = np.diff(md, prepend=md[0])
    step[0] = 0.0
    return md[0] + np.cumsum(np.cos(np.radians(inclination_deg(md))) * step)


def md_grid() -> np.ndarray:
    return np.arange(TOP_MD_FT, BOTTOM_MD_FT + STEP_FT / 2, STEP_FT)


def _saturation(height_ft):
    """Water saturation by height above the free water level (1 at and below it)."""
    h = np.maximum(height_ft, 0.0)
    swirr = 0.12
    return swirr + (1.0 - swirr) / (1.0 + h / 12.0) ** 1.2


def log_curves() -> Dict[str, np.ndarray]:
    """GR, RHOB, NPHI and RT of the earth model, plus MD, TVD and inclination."""
    rng = np.random.default_rng(SEED)
    md = md_grid()
    tvd = tvd_ft(md)
    n = len(md)
    smooth = 0.03 * np.sin(tvd / 9.0) + 0.02 * np.sin(tvd / 3.7)
    vsh = np.where(tvd < SHALE_BASE_TVD_FT - 15.0, 0.75,
                   np.where(tvd < SHALE_BASE_TVD_FT + 15.0, 0.4, 0.08)) + smooth
    vsh = np.clip(vsh + rng.normal(0.0, 0.01, n), 0.02, 0.95)
    sand = tvd >= SHALE_BASE_TVD_FT + 15.0
    height = FWL_TVD_FT - tvd
    sw = np.where(sand, _saturation(height), 1.0)
    phie = (1.0 - vsh) * (PHI_SAND + 0.015 * np.sin(tvd / 11.0) + rng.normal(0.0, 0.004, n))
    fluid_rho = sw * 1.03 + (1.0 - sw) * 0.80
    rhob = 2.65 * (1.0 - phie - 0.1 * vsh) + fluid_rho * phie + 2.5 * 0.1 * vsh
    nphi = phie * (sw * 1.0 + (1.0 - sw) * 0.9) + 0.38 * vsh
    rt_sand = RW / (np.maximum(phie, 0.02) ** 2 * sw ** 2)
    rt = 1.0 / ((1.0 - vsh) / rt_sand + vsh / RSH)
    gr = 20.0 + 100.0 * vsh + rng.normal(0.0, 1.5, n)
    return {
        "MD": md, "TVD": tvd, "DEVI": inclination_deg(md),
        "GR": gr, "RHOB": rhob + rng.normal(0.0, 0.004, n),
        "NPHI": nphi + rng.normal(0.0, 0.003, n),
        "RT": rt * np.exp(rng.normal(0.0, 0.03, n)),
    }


def _las_text(name: str, curves: Dict[str, np.ndarray], columns, header_deviation: bool) -> str:
    units = {"GR": ("GAPI", "GAMMA RAY"), "RHOB": ("G/C3", "BULK DENSITY"),
             "NPHI": ("V/V", "NEUTRON POROSITY"), "RT": ("OHMM", "DEEP RESISTIVITY"),
             "DEVI": ("DEG", "WELL INCLINATION"), "TVD": ("FT", "TRUE VERTICAL DEPTH")}
    lines = [
        "~VERSION INFORMATION",
        " VERS.                          2.0 : CWLS LOG ASCII STANDARD - VERSION 2.0",
        " WRAP.                           NO : ONE LINE PER DEPTH STEP",
        "~WELL INFORMATION",
        f" STRT.FT                 {TOP_MD_FT:.4f} : START DEPTH",
        f" STOP.FT                 {BOTTOM_MD_FT:.4f} : STOP DEPTH",
        f" STEP.FT                    {STEP_FT:.4f} : STEP",
        f" NULL.                     {NULL:.4f} : NULL VALUE",
        " COMP.                 SYNTHETIC TRIAL : COMPANY",
        f" WELL.                 {name} : WELL NAME",
        " FLD.                  SYNTHETIC TRIAL : FIELD",
        f" UWI.                  {name}-UWI : UNIQUE WELL IDENTIFIER",
    ]
    if header_deviation:
        lines += ["~PARAMETER INFORMATION",
                  f" MDEV.DEG                {HOLD_DEG:.1f} : MAXIMUM DEVIATION"]
    lines.append("~CURVE INFORMATION")
    lines.append(" DEPT.FT                          : MEASURED DEPTH")
    for c in columns:
        unit, text = units[c]
        lines.append(f" {c}.{unit:<28} : {text}")
    lines.append("~ASCII")
    data = np.column_stack([curves["MD"]] + [curves[c] for c in columns])
    lines += ["  ".join(f"{v:.4f}" for v in row) for row in data]
    return "\n".join(lines) + "\n"


def readme_text() -> str:
    """The README written next to the files: what each is, the messages, the FWL to enter."""
    grid = md_grid()
    tvd_at = float(np.interp(README_DEPTH_MD_FT, grid, tvd_ft(grid)))
    h_vertical = FWL_TVD_FT - README_DEPTH_MD_FT
    h_true = FWL_TVD_FT - tvd_at
    bottom = float(tvd_ft(grid)[-1])
    note_h = HEADER_DEVIATION_NOTE.format(noun="heights")
    note_c = CURVE_DEVIATION_NOTE.format(noun="heights")
    return f"""SYNTH_DEVIATED: three synthetic LAS files of one deviated well (test data, not a real well)

The well is vertical from {TOP_MD_FT:.0f} to {KICK_OFF_MD_FT:.0f} ft MD, builds {BUILD_DEG_PER_100_FT:g} degrees per 100 ft up to {HOLD_DEG:g} degrees and holds
to {BOTTOM_MD_FT:.0f} ft MD. At the bottom TVD is {bottom:,.0f} ft, so MD minus TVD is {BOTTOM_MD_FT - bottom:,.0f} ft.
The earth model is in TVD: shale to {SHALE_BASE_TVD_FT:.0f} ft, then sand with oil above a free water level at {FWL_TVD_FT:.0f} ft TVD and
water below it. Curves: GR, RHOB, NPHI, RT (feet, step {STEP_FT:g} ft). Regenerate with:  python -m tests.synth_deviated <folder>

FILES
1. {FILE_NAMES[0]}
   MDEV = {HOLD_DEG:g} DEG in the parameter section of the header. No inclination curve, no TVD curve.
2. {FILE_NAMES[1]}
   Inclination curve DEVI (degrees). No TVD curve, no deviation entry in the header.
3. {FILE_NAMES[2]}
   The same DEVI curve plus a TVD curve (cumulative sum of cos(inclination) x step, vertical above the log top).
   The TVD curve is mapped automatically.

WHAT YOU SHOULD SEE IN v1.15.0 (switch on Saturation-Height with a contact; with the temperature
correction on, the same note appears with "temperatures" instead of "heights")
File 1: warning, Saturation-Height diagnostics:
   {note_h}
File 2: warning, Saturation-Height diagnostics:
   {note_c}
File 3: none of the deviation warnings. The depth source reads "TVD curve TVD" and no
   "Height computed on MD (assumed vertical)." line appears.
A vertical well without deviation entries keeps the info line "Height computed on MD (assumed vertical)."

SEE THE HEIGHT DIFFERENCE BETWEEN FILES 2 AND 3
In Saturation-Height set the Default contact: FWL = {FWL_TVD_FT:.0f} ft, datum TVD, fluid oil.
Heights above the FWL (HAFWL) are the contact minus the depth the well uses. File 2 has no TVD, so it
uses MD; file 3 uses its TVD curve.
At {README_DEPTH_MD_FT:.0f} ft MD: file 2 reads a height of {h_vertical:.0f} ft, file 3 reads {h_true:.0f} ft (TVD there is {tvd_at:.0f} ft).
File 2 therefore reads the height {README_DEPTH_MD_FT - tvd_at:.0f} ft too low at that depth (MD minus TVD), and it places the
contact at {FWL_TVD_FT:.0f} ft MD instead of about {float(np.interp(FWL_TVD_FT, tvd_ft(grid), grid)):.0f} ft MD.
Where the two files differ the saturation-height Sw differs the same way.
"""


def write_deviated_wells(folder, readme: bool = True) -> Dict[str, str]:
    """Write the three LAS files (and the README) into ``folder``; return their paths by key.

    Keys: ``header``, ``incl``, ``incl_tvd`` and, when written, ``readme``.
    """
    os.makedirs(folder, exist_ok=True)
    curves = log_curves()
    base = ("GR", "RHOB", "NPHI", "RT")
    specs = {
        "header": (FILE_NAMES[0], "SYNTH-DEVIATED-1", base, True),
        "incl": (FILE_NAMES[1], "SYNTH-DEVIATED-2", base + ("DEVI",), False),
        "incl_tvd": (FILE_NAMES[2], "SYNTH-DEVIATED-3", base + ("DEVI", "TVD"), False),
    }
    out = {}
    for key, (file_name, well, columns, header) in specs.items():
        path = os.path.join(str(folder), file_name)
        with open(path, "w", newline="\n", encoding="utf-8") as handle:
            handle.write(_las_text(well, curves, columns, header))
        out[key] = path
    if readme:
        path = os.path.join(str(folder), README_NAME)
        with open(path, "w", newline="\n", encoding="utf-8") as handle:
            handle.write(readme_text())
        out["readme"] = path
    return out


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    for path in write_deviated_wells(target).values():
        print(path)
