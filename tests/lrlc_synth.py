"""A synthetic well with known answers for the whole LRLC chain (``tests/test_lrlc_chain_e2e.py``).

Depth 1000 to 1900 ft in 0.5 ft steps, three zones.

``THIN``  clean thin sands (6 to 8 ft, 1.5 to 2 times the response width) between shales. The true
          Rt of every bed is known. By default the zone has no Thomas-Stieber end-points; with
          them the guard leaves the resolved shale beds out and does not class it laminated, so
          the deconvolution still runs. The deep curve is built by applying, in reverse physical order: connected pyrite (parallel
          conductance), a small constant laminated shale fraction (parallel mixing with the shale
          resistivity), a one-step invasion profile (``forward_ra`` of the invasion tool) and, last, a
          Gaussian vertical response of 4 ft FWHM with 2 percent multiplicative noise. ``RM`` and
          ``RS`` carry the invasion at bed level (1 ft response), ``RXO`` is the flushed-zone
          resistivity read at 1 ft and serves as the reference curve for the bed boundaries.
``LAM``   sub-resolution laminations (Vlam 0.12 to 0.48, on the laminar line of the
          Thomas-Stieber triangle). Archie Sw of the sand laminae is 0.30.
``GOFF``  the same laminations, shifted in depth; the run that switches the shoulder-bed guard off
          reads this zone.

Only numpy and pandas; the invasion forward function and the vertical response are those of the
modules under test, so the truth uses the same physics as the inversions (the point is the chain,
not the physics).
"""
import io
from dataclasses import dataclass, field
from typing import Dict

import numpy as np
import pandas as pd

from modules.formation_tops import FormationTops
from modules.lrlc.config import AUX_ROLES, LRLC_PARAM_DEFAULTS
from modules.lrlc.decon import response_weights
from modules.lrlc.invasion import GENERIC_TOOLS, forward_ra
from tests.golden.cases import FULL_MAPPING

STEP_FT = 0.5
FWHM_FT = 4.0
NOISE = 0.02
RW, RSH, A, M, N = 0.05, 2.0, 1.0, 2.0, 2.0
PHI_MAX, PHI_SH, SW_LAM = 0.30, 0.08, 0.30
PHI_SAND_THIN = 0.30
GR_SAND, GR_SHALE = 25.0, 120.0
RT_SHALE = 3.0
VLAM_THIN, VPYR_THIN, PYR_F, PYR_RPY = 0.02, 0.015, 0.002, 0.01
RXO_RATIO = 0.5
ZONES = (("THIN", 1000.0, 1400.0), ("LAM", 1400.0, 1700.0), ("GOFF", 1700.0, 1900.0))
TOPS_TEXT = "Formation\tTop (ft)\tBottom (ft)\n" + "".join(
    f"{name.title()}\t{top:g}\t{bottom:g}\n" for name, top, bottom in ZONES)

PARAMS = {
    "vsh_baseline_method": "Custom (Manual)", "gr_min_manual": 20.0, "gr_max_manual": 120.0,
    "sw_methods": ["Archie"], "sw_primary_method": "Archie",
    "rw": RW, "rw_mode": "manual", "rsh": RSH, "rsh_mode": "manual",
    "a": A, "m": M, "n": N,
}
CURVES = {**{role: None for role in AUX_ROLES}, "RS": "RS", "RM": "RM", "RXO": "RXO"}


@dataclass
class ChainWell:
    data: pd.DataFrame
    mapping: dict
    tops: FormationTops
    rt_true: np.ndarray            # true Rt of the sands and shales (THIN), sand-lamina Rt (LAM, GOFF)
    rt_level: np.ndarray           # THIN: the deep reading before the vertical response (invasion affected)
    beds: list = field(default_factory=list)      # THIN sands: (top, bottom, true Rt)
    vlam: np.ndarray = None
    stages: dict = field(default_factory=dict)   # THIN: the Rt after each undone effect, by step name

    def zone_mask(self, name):
        lo, hi = {n: (t, b) for n, t, b in ZONES}[name]
        depth = self.data["DEPTH"].to_numpy()
        return (depth >= lo) & (depth < hi)

    def sand_interior(self, margin=1.0):
        """THIN samples at least ``margin`` ft inside a sand bed."""
        depth = self.data["DEPTH"].to_numpy()
        keep = np.zeros(len(depth), dtype=bool)
        for top, bottom, _ in self.beds:
            keep |= (depth >= top + margin) & (depth <= bottom - margin)
        return keep


def bed_blur(depth, bed_tops, bed_bottoms, bed_values, fwhm_ft):
    """Conductivity-domain vertical response of a blocky profile (the forward model of the step).

    A sample at depth ``z`` stands for the interval ``z - step / 2`` to ``z + step / 2``, so the bed
    edges sit half a step above the first and last sample of the bed.
    """
    tops = np.asarray(bed_tops, dtype=float) - STEP_FT / 2.0
    bottoms = np.asarray(bed_bottoms, dtype=float) - STEP_FT / 2.0
    tops[0], bottoms[-1] = -1.0e4, 1.0e4
    return 1.0 / (response_weights(depth, tops, bottoms, fwhm_ft) @ (1.0 / np.asarray(bed_values)))


def _thin_profile(rng, depth):
    """Bed table of the THIN zone: shale, then sand, repeated; ``(top, bottom, rt, is_sand)``."""
    beds, z = [], depth[0]
    zone_end = ZONES[0][2]
    while z < zone_end - 12.0:
        shale = float(rng.choice([8.0, 10.0, 12.0]))
        beds.append((z, z + shale, RT_SHALE, False))
        z += shale
        sand = float(rng.choice([6.0, 7.0, 8.0]))
        beds.append((z, z + sand, float(rng.choice([12.0, 16.0, 20.0, 24.0])), True))
        z += sand
    beds.append((z, zone_end, RT_SHALE, False))
    return beds


def _laminated(depth, shift):
    """Sand laminae with shale laminae: sample-level truth of ``LAM`` / ``GOFF``."""
    vlam = 0.12 + 0.36 * (0.5 + 0.5 * np.sin((depth + shift) / 3.0))
    phit = (1 - vlam) * PHI_MAX + vlam * PHI_SH
    rsand = A * RW / (PHI_MAX ** M * SW_LAM ** N)
    rt = 1.0 / ((1 - vlam) / rsand + vlam / RSH)
    return vlam, phit, rsand, rt


def build_chain_well(seed: int = 20261115) -> ChainWell:
    rng = np.random.default_rng(seed)
    depth = np.arange(ZONES[0][1], ZONES[-1][2], STEP_FT)
    n = len(depth)
    thin = (depth >= ZONES[0][1]) & (depth < ZONES[0][2])
    tool = GENERIC_TOOLS["generic_induction"]
    r50 = (tool["deep"], tool["medium"], tool["shallow"])

    gr, phit = np.full(n, GR_SHALE), np.full(n, 0.08)
    rt_true = np.full(n, RT_SHALE)
    sand = np.zeros(n, dtype=bool)
    di = np.full(n, 40.0)
    beds, table = [], _thin_profile(rng, depth[thin])
    for top, bottom, rt, is_sand in table:
        sel = (depth >= top) & (depth < bottom)
        rt_true[sel] = rt
        if is_sand:
            sand[sel] = True
            di[sel] = float(rng.choice([30.0, 40.0, 50.0]))
            beds.append((top, bottom, rt))
    sand &= thin
    gr[sand], phit[sand] = GR_SAND, PHI_SAND_THIN

    # forward chain in reverse physical order (THIN): pyrite, laminated shale, invasion, response
    rt_a = 1.0 / (1.0 / rt_true + np.where(thin, PYR_F * VPYR_THIN / PYR_RPY, 0.0))
    rt_b = np.where(sand, 1.0 / ((1 - VLAM_THIN) / rt_a + VLAM_THIN / RSH), rt_a)
    rxo = np.where(sand, RXO_RATIO * rt_b, rt_b)
    ra = forward_ra(rt_b, rxo, di, r50, tool["p"])
    level = np.where(thin, ra[:, 0], np.nan)
    rt = np.empty(n)
    first = [int(np.searchsorted(depth, top)) for top, _, _, _ in table]
    bed_tops, bed_bottoms = [b[0] for b in table], [b[1] for b in table]
    dz = depth[thin]

    def blurred(values, fwhm):
        return bed_blur(dz, bed_tops, bed_bottoms, values[first], fwhm)

    rt[thin] = blurred(ra[:, 0], FWHM_FT) * (1.0 + NOISE * rng.standard_normal(thin.sum()))
    rm, rs, rxo_log = (np.full(n, np.nan) for _ in range(3))
    rm[thin], rs[thin] = blurred(ra[:, 1], 1.0), blurred(ra[:, 2], 1.0)
    rxo_log[thin] = blurred(rxo, 1.0)

    # the density and gamma ray logs have a vertical resolution well below the beds: sharp steps
    # laminated zones
    vlam = np.zeros(n)
    for name, shift in (("LAM", 0.0), ("GOFF", 7.0)):
        lo, hi = {z: (t, b) for z, t, b in ZONES}[name]
        sel = (depth >= lo) & (depth < hi)
        v, p, rsand, r = _laminated(depth[sel], shift)
        vlam[sel], phit[sel], rt[sel] = v, p, r
        gr[sel] = 20.0 + 100.0 * v
        rt_true[sel] = rsand
        rm[sel] = rs[sel] = rxo_log[sel] = r

    data = pd.DataFrame({
        "DEPTH": depth, "GR": gr, "RHOB": 2.65 - 1.65 * phit,
        "NPHI": np.where(thin, 0.2, 0.2), "DT": 90.0 - 40.0 * phit,
        "RT": rt, "RM": rm, "RS": rs, "RXO": rxo_log})
    tops = FormationTops()
    assert tops.read_tops_from_buffer(io.StringIO(TOPS_TEXT))
    return ChainWell(data=data, mapping=dict(FULL_MAPPING), tops=tops, rt_true=rt_true,
                     rt_level=level, beds=beds, vlam=vlam,
                     stages={"decon": level, "invasion": rt_b, "laminated": rt_a, "pyrite": rt_true})


def lrlc_params(steps: Dict[str, list], fallback="nan", guard=True, marked=False,
                decon: dict = None, extra_default: dict = None, thin_endpoints=False) -> dict:
    """The ``params["lrlc"]`` payload (as ``AppModel._lrlc_params`` builds it) for the chain well.

    ``steps`` maps zone name to its ``rt_steps``. By default THIN has no Thomas-Stieber end-points
    (so the guard does not classify it); ``thin_endpoints=True`` gives it the well end-points, and
    the guard then classifies it from its resolved shale beds. THIN reads a constant laminated
    fraction and pyrite volume; LAM and GOFF read Vlam from the Thomas-Stieber split.
    """
    default = {**LRLC_PARAM_DEFAULTS, "rt_fallback": fallback, "phi_max": PHI_MAX,
               "phi_sh": PHI_SH, "dec_hires_source": "RXO", "dec_fwhm_ft": FWHM_FT,
               "dec_tool": "custom", "dec_noise_rel": NOISE, "dec_max_ratio": 20.0,
               **(decon or {}), **(extra_default or {})}
    zones = {}
    for name, _, _ in ZONES:
        row = {**default, "rt_steps": list(steps.get(name, []))}
        if name == "THIN":
            row.update(vlam_source="constant", vlam_const=VLAM_THIN, pyr_method="manual",
                       pyr_vpyr=VPYR_THIN, pyr_f=PYR_F, pyr_rpy=PYR_RPY)
            if not thin_endpoints:
                row.update(phi_max=None, phi_sh=None)
        zones[name] = row
    curves = {**CURVES, **({"RT_SBC": "RT"} if marked else {})}
    lrlc = {"enabled": True, "screening": {"use_gas_flag": True, "use_rs": True},
            "rt_cutoff": {"enabled": False}, "movable": {"swirr_column": "SWIRR"},
            "curves": curves, "thomas_stieber": {"enabled": True},
            "resolved": {"default": {**default, "rt_steps": []}, "zones": zones}}
    if not guard:
        lrlc["guard"] = {"enabled": False}
    return lrlc
