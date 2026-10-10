"""Phase 5 exit criterion: 10 wells x 10k samples, default methods, run-all < 3 s."""

import io
import time

import numpy as np
import pandas as pd

from modules import param_scopes as ps
from modules.formation_tops import FormationTops
from modules.pipeline import PARAM_DEFAULTS, run_pipeline
from tests.golden.cases import FULL_MAPPING

N_WELLS, N_SAMPLES = 10, 10_000


def _well(seed):
    rng = np.random.default_rng(seed)
    depth = 1000.0 + np.arange(N_SAMPLES) * 0.5
    return pd.DataFrame({
        "DEPTH": depth,
        "GR": rng.uniform(20, 140, N_SAMPLES),
        "RHOB": rng.uniform(2.1, 2.65, N_SAMPLES),
        "NPHI": rng.uniform(0.05, 0.4, N_SAMPLES),
        "DT": rng.uniform(60, 110, N_SAMPLES),
        "RT": rng.uniform(1, 200, N_SAMPLES),
    })


def _tops():
    rows = "\n".join(f"Zone {i}\t{1000 + i * 500}\t{1500 + i * 500}" for i in range(10))
    tops = FormationTops()
    assert tops.read_tops_from_buffer(io.StringIO("Formation\tTop (ft)\tBottom (ft)\n" + rows))
    return tops


def test_ten_wells_default_methods_under_three_seconds():
    wells = [_well(seed) for seed in range(N_WELLS)]
    start = time.perf_counter()
    for data in wells:
        run_pipeline(data, FULL_MAPPING, {})
    assert time.perf_counter() - start < 3.0


def test_ten_zoned_wells_all_sw_models_stay_fast():
    wells = [_well(seed) for seed in range(N_WELLS)]
    tops = _tops()
    zones = [ps.normalize_zone(f"Zone {i}") for i in range(10)]
    zone_params = {z: {"m": ps.make_entry(ps.MANUAL, 1.8 + 0.02 * i)} for i, z in enumerate(zones)}
    params = {
        "sw_methods": ["Archie", "Indonesian", "Simandoux", "Waxman-Smits", "Dual-Water"],
        "zone_plan": ps.zone_plan(dict(PARAM_DEFAULTS), None, zone_params, None, zones),
    }
    start = time.perf_counter()
    for data in wells:
        _, summary = run_pipeline(data, FULL_MAPPING, params, formation_tops=tops)
    elapsed = time.perf_counter() - start
    assert len(summary["zones"]) == 10
    assert elapsed < 6.0
