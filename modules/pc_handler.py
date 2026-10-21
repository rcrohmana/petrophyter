"""
Capillary pressure (Pc) data handler for Petrophyter.

Reads a table of laboratory capillary pressure points (one row per point, rows of one
sample form one curve) into one frame in fixed units: Pc in psi, Sw as a fraction,
porosity as a fraction, permeability in mD, depth in feet. Pure and Qt-free.

The handler is a twin of :class:`~modules.core_handler.CoreDataHandler`: it offers the
same duck-typed surface the multi-well import plan and dialog read (``excluded_rows`` with
file line numbers, ``split_by_well``, ``porosity_scales``, ``depth_is_tvd``, ...).
"""

import copy
import logging
import re
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from modules.core_handler import (
    _FEET_TOKENS, _METER_TOKENS, _cell_text, _is_blank, _resolve_override, _tokenize,
)
from modules.las_utils import COMMON_NULL_VALUES
from modules.perm_calibration import PAIR_TOLERANCE_FT
from modules.table_reader import read_table
from modules.well_matching import (
    find_well_column, fill_down_wells, group_key, group_well_names,
    merged_cell_pattern_applies,
)

logger = logging.getLogger(__name__)

M_TO_FT = 3.28084

# Pressure units a file may use, as psi per unit.
PC_UNITS_TO_PSI: Dict[str, float] = {
    "psi": 1.0, "kpa": 0.1450377, "mpa": 145.0377, "bar": 14.50377, "atm": 14.69595,
}
PC_UNIT_LABELS: Dict[str, str] = {
    "psi": "psi", "kpa": "kPa", "mpa": "MPa", "bar": "bar", "atm": "atm",
}
_PC_UNIT_TOKENS = {"psi": "psi", "psia": "psi", "kpa": "kpa", "mpa": "mpa",
                   "bar": "bar", "atm": "atm"}

# Laboratory fluid systems and their default (sigma dyne/cm, theta degrees).
LAB_SYSTEMS: Dict[str, Tuple[float, float]] = {
    "air-brine": (72.0, 0.0),
    "hg-air": (480.0, 140.0),
    "oil-brine": (48.0, 30.0),
}
SYSTEM_LABELS: Dict[str, str] = {
    "air-brine": "Air-brine", "hg-air": "Hg-air (MICP)", "oil-brine": "Oil-brine",
}
_SYSTEM_ALIASES = {
    "airbrine": "air-brine", "airwater": "air-brine", "gasbrine": "air-brine",
    "hgair": "hg-air", "hg": "hg-air", "mercury": "hg-air", "micp": "hg-air",
    "mercuryair": "hg-air", "mercuryinjection": "hg-air",
    "oilbrine": "oil-brine", "oilwater": "oil-brine",
}

PC_COLUMNS = ["SAMPLE", "WELL", "DEPTH", "PHI", "K", "PC_PSI", "SW", "SYSTEM",
              "ROCK_TYPE", "SIGMA_COS_LAB"]

_SW_TOLERANCE = 1e-6


def normalize_system(text) -> Optional[str]:
    """Canonical system name (``air-brine`` / ``hg-air`` / ``oil-brine``) or None."""
    if text is None:
        return None
    key = re.sub(r"[^a-z]+", "", str(text).lower())
    if not key:
        return None
    canon = re.sub(r"[^a-z]+", "", key)
    for name in LAB_SYSTEMS:
        if canon == re.sub(r"[^a-z]+", "", name):
            return name
    return _SYSTEM_ALIASES.get(canon)


def sigma_cos(system: Optional[str], sigma: float = np.nan, theta: float = np.nan) -> float:
    """``sigma * |cos(theta)|`` in dyne/cm; a missing sigma or theta falls back to the system default."""
    if system not in LAB_SYSTEMS:
        return float("nan")
    d_sigma, d_theta = LAB_SYSTEMS[system]
    s = float(sigma) if np.isfinite(sigma) else d_sigma
    t = float(theta) if np.isfinite(theta) else d_theta
    return float(s * abs(np.cos(np.radians(t))))


class PcDataHandler:
    """Loads capillary pressure points.

    ``data`` has one row per Pc point with the columns ``SAMPLE``, ``WELL``, ``DEPTH`` (ft),
    ``PHI`` (fraction), ``K`` (mD), ``PC_PSI``, ``SW`` (fraction), ``SYSTEM``, ``ROCK_TYPE``
    and ``SIGMA_COS_LAB`` (dyne/cm). Porosity and permeability left blank are completed from
    core data by :meth:`complete_from_core`; a sample that stays without them is excluded
    there.
    """

    DEPTH_ALIASES = ['depth', 'tvd', 'tvdss', 'md']
    POROSITY_ALIASES = ['porosity', 'por', 'phi', 'core porosity', 'helium porosity']
    PERM_ALIASES = ['permeability', 'perm', 'kair', 'klink', 'klinkenberg', 'kinf', 'kh', 'k']
    SAMPLE_ALIASES = ['sample', 'sample id', 'sample no', 'plug', 'plug id', 'plug no',
                      'id', 'number', 'no']
    PC_ALIASES = ['pc', 'capillary pressure', 'pressure', 'pcap']
    SW_ALIASES = ['sw', 's_w', 'water saturation', 'brine saturation', 'wetting saturation']
    SHG_ALIASES = ['shg', 's_hg', 'hg saturation', 'mercury saturation', 'snw', 's_nw',
                   'nonwetting saturation']
    SYSTEM_ALIASES = ['system', 'fluid system', 'fluids']
    ROCK_TYPE_ALIASES = ['rock type', 'rocktype', 'rt', 'facies']
    SIGMA_ALIASES = ['sigma', 'ift', 'interfacial tension']
    THETA_ALIASES = ['theta', 'contact angle']
    M_TO_FT = M_TO_FT

    def __init__(self):
        self.data: Optional[pd.DataFrame] = None
        self.depth_col: Optional[str] = None
        self.porosity_col: Optional[str] = None
        self.perm_col: Optional[str] = None
        self.well_col: Optional[str] = None
        self.well_kind: str = 'name'
        self.depth_unit: str = 'FT'
        self.depth_unit_detected: bool = False
        self.depth_unit_warning: Optional[str] = None
        self.converted_to_feet: bool = False
        self.porosity_converted: bool = False
        self.pc_unit: Optional[str] = None            # resolved: chosen, else detected
        self.pc_unit_detected: Optional[str] = None   # from the Pc header, None if absent
        self.system: Optional[str] = None             # the one default for rows without a system
        self.system_in_file: bool = False
        self.system_needed: bool = False
        self.sw_is_hg: bool = False                   # the file holds Hg (non-wetting) saturation
        self.sw_scales: Dict[str, str] = {}
        self.last_error: Optional[str] = None
        self.excluded_rows: List[Tuple[Optional[int], str]] = []
        self.blank_well_rows: List[int] = []
        self.filled_rows: List[int] = []
        self.fill_down: bool = False
        self.fill_down_applicable: bool = False
        self.notes: List[str] = []
        self.spellings: List[str] = []
        self.table_read = None
        self.columns_detected: Dict[str, Optional[str]] = {}
        self.excluded_row_wells: Dict[int, str] = {}
        self.completed_samples: int = 0
        self._columns_override: Optional[dict] = None
        self._override_error: Optional[str] = None
        self.depth_is_tvd: bool = False
        self.tvd_warning: Optional[str] = None
        self.porosity_scale: Optional[str] = None
        self.porosity_scales: Dict[str, str] = {}
        self.porosity_scale_mixed: bool = False
        self.porosity_warning: Optional[str] = None
        self._scales_by_group: Dict[str, str] = {}
        self._por_raw: Optional[np.ndarray] = None
        self._row_lines: np.ndarray = np.array([], dtype=int)

    def _reset(self):
        """Clear everything a previous file left behind."""
        self.__init__()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def read_pc_from_buffer(self, file_buffer, separator: Optional[str] = None,
                            depth_unit: str = 'Auto', *, fill_down: bool = False,
                            porosity_scale=None, sheet=0, columns: Optional[dict] = None,
                            pc_unit: Optional[str] = None,
                            system: Optional[str] = None) -> bool:
        """Read Pc data from a file buffer.

        Args:
            separator: preferred delimiter (None = detect)
            depth_unit: 'Auto', 'M' or 'FT'
            fill_down: blank well cells continue the well above
            porosity_scale: None (decide per well by the median), 'percent' / 'fraction'
                for every well, or ``{well: scale}``
            columns: explicit column override ``{role: header name or None}`` with roles
                well, sample, depth, porosity, permeability, pc, sw, system, rock_type,
                sigma, theta
            pc_unit: 'psi', 'kpa', 'mpa', 'bar' or 'atm'; used when the header names no unit
                (and overrides the header when given)
            system: 'air-brine', 'hg-air' or 'oil-brine' for rows without a system

        Returns:
            True if successful; otherwise ``last_error`` says why.
        """
        return self._read(file_buffer, separator, depth_unit, fill_down, porosity_scale,
                          sheet, columns, pc_unit, system)

    def read_pc_file(self, file_path: str, separator: Optional[str] = None,
                     depth_unit: str = 'Auto', *, fill_down: bool = False,
                     porosity_scale=None, sheet=0, columns: Optional[dict] = None,
                     pc_unit: Optional[str] = None, system: Optional[str] = None) -> bool:
        """Read Pc data from a path (delimited text or .xlsx); see ``read_pc_from_buffer``."""
        return self._read(file_path, separator, depth_unit, fill_down, porosity_scale,
                          sheet, columns, pc_unit, system)

    def _read(self, source, separator, depth_unit, fill_down, porosity_scale, sheet,
              columns, pc_unit, system) -> bool:
        self._reset()
        self._columns_override = columns
        try:
            chosen_unit = None
            if pc_unit:
                chosen_unit = _PC_UNIT_TOKENS.get(str(pc_unit).strip().lower())
                if chosen_unit is None:
                    raise ValueError(f"Unknown Pc unit {pc_unit!r}")
            chosen_system = None
            if system:
                chosen_system = normalize_system(system)
                if chosen_system is None:
                    raise ValueError(f"Unknown fluid system {system!r}")
            table = read_table(source, self._columns_found, sheet=sheet, delimiter=separator)
            return self._build_from_table(table, depth_unit, fill_down, porosity_scale,
                                          chosen_unit, chosen_system)
        except Exception as e:
            self.last_error = self._override_error or str(e)
            logger.error("Error reading Pc data: %s", e)
            return False

    # ------------------------------------------------------------------
    # Column detection
    # ------------------------------------------------------------------
    def _find_column(self, df: pd.DataFrame, aliases: List[str]) -> Optional[str]:
        """First column holding every token of an alias (whole-token match), alias order."""
        col_tokens = {col: set(_tokenize(str(col))) for col in df.columns}
        for alias in aliases:
            alias_tokens = _tokenize(alias)
            if not alias_tokens:
                continue
            for col in df.columns:
                if all(tok in col_tokens[col] for tok in alias_tokens):
                    return col
        return None

    def _detect_columns(self, df: pd.DataFrame) -> dict:
        ov = _resolve_override(self._columns_override, df.columns)
        used: List = []

        def pick(role, aliases):
            if role in ov:
                col = ov[role]
            else:
                left = df[[c for c in df.columns if c not in used]]
                col = self._find_column(left, aliases)
            if col is not None:
                used.append(col)
            return col

        cols: dict = {}
        if 'well' in ov:
            well_col, well_kind = ov['well'], 'name'
            if well_col is not None:
                found, kind = find_well_column(df[[well_col]], self._find_column)
                well_kind = kind if found is not None else 'name'
        else:
            well_col, well_kind = find_well_column(df, self._find_column)
        if well_col is not None:
            used.append(well_col)
        cols['well'], cols['well_kind'] = well_col, well_kind
        cols['pc'] = pick('pc', self.PC_ALIASES)
        sw = pick('sw', self.SW_ALIASES)
        hg = False
        if sw is None:
            sw = pick('sw', self.SHG_ALIASES)
        if sw is not None:
            hg = bool(set(_tokenize(str(sw))) & {'shg', 'snw', 'hg', 'nw', 'mercury',
                                                  'nonwetting'})
        cols['sw'], cols['sw_is_hg'] = sw, hg
        # Permeability before depth: "Perm (mD)" must not be taken for an "MD" depth.
        for role, aliases in (('sample', self.SAMPLE_ALIASES),
                              ('porosity', self.POROSITY_ALIASES),
                              ('permeability', self.PERM_ALIASES),
                              ('depth', self.DEPTH_ALIASES),
                              ('system', self.SYSTEM_ALIASES),
                              ('rock_type', self.ROCK_TYPE_ALIASES),
                              ('sigma', self.SIGMA_ALIASES), ('theta', self.THETA_ALIASES)):
            cols[role] = pick(role, aliases)
        return cols

    def _columns_found(self, df: pd.DataFrame) -> bool:
        """Predicate for ``read_table``: Pc, saturation and a sample or depth column."""
        try:
            cols = self._detect_columns(df)
        except ValueError as e:
            self._override_error = str(e)
            return False
        return (cols['pc'] is not None and cols['sw'] is not None
                and (cols['sample'] is not None or cols['depth'] is not None))

    # ------------------------------------------------------------------
    # Building the frame
    # ------------------------------------------------------------------
    def _group_keys_of(self, wells) -> np.ndarray:
        if not self.well_col:
            return np.full(len(wells), '', dtype=object)
        return np.array([group_key(w, self.well_kind) for w in wells], dtype=object)

    def _build_from_table(self, table, depth_unit, fill_down, porosity_scale,
                          chosen_unit, chosen_system) -> bool:
        self.table_read = replace(table, frame=None)
        self.notes = list(table.notes)
        df = table.frame.copy()
        lines = list(table.line_numbers) or list(range(2, len(df) + 2))
        if df.empty:
            self.last_error = "Empty Pc file"
            return False

        original = {}
        for col in df.columns:
            original.setdefault(str(col).strip().lower(), col)
        df.columns = df.columns.str.strip().str.lower()
        try:
            cols = self._detect_columns(df)
        except ValueError as e:
            self.last_error = str(e)
            return False
        pc_col, sw_col = cols['pc'], cols['sw']
        if pc_col is None:
            self.last_error = f"Could not find a Pc column. Columns found: {list(df.columns)}"
            return False
        if sw_col is None:
            self.last_error = ("Could not find a saturation column (Sw or Hg saturation). "
                               f"Columns found: {list(df.columns)}")
            return False
        if cols['sample'] is None and cols['depth'] is None:
            self.last_error = ("The file needs a sample column or a depth column to group "
                               f"points into curves. Columns found: {list(df.columns)}")
            return False
        sample_col, depth_col = cols['sample'], cols['depth']
        por_col, perm_col = cols['porosity'], cols['permeability']
        system_col, rt_col = cols['system'], cols['rock_type']
        sigma_col, theta_col = cols['sigma'], cols['theta']
        self.sw_is_hg = bool(cols['sw_is_hg'])
        self.well_col, self.well_kind = cols['well'], cols['well_kind']
        self.depth_col = 'DEPTH' if depth_col else None
        self.porosity_col = 'PHI' if por_col else None
        self.perm_col = 'K' if perm_col else None

        # Pressure unit: the user's choice, else the header token.
        detected = None
        for tok in _tokenize(str(pc_col)):
            if tok in _PC_UNIT_TOKENS:
                detected = _PC_UNIT_TOKENS[tok]
                break
        self.pc_unit_detected = detected
        self.pc_unit = chosen_unit or detected
        factor = PC_UNITS_TO_PSI.get(self.pc_unit, 1.0)
        self.system = chosen_system

        if depth_col and set(_tokenize(str(depth_col))) & {'tvd', 'tvdss'}:
            self.depth_is_tvd = True
            self.tvd_warning = (
                f"Pc depths look like TVD (column '{depth_col}'); logs are on MD. "
                "Import only if the well is vertical or the logs are on TVD.")
            logger.warning(self.tvd_warning)

        n = len(df)
        wells_txt: List[str] = []
        if self.well_col:
            wells_txt = [_cell_text(v) for v in df[self.well_col]]
            if not any(wells_txt):
                self.notes.append(f"Well column '{self.well_col}' is empty; it was ignored.")
                self.well_col, self.well_kind = None, 'name'
                wells_txt = []
        self.columns_detected = {
            role: (original.get(col) if col else None)
            for role, col in (('well', self.well_col), ('sample', sample_col),
                              ('depth', depth_col), ('pc', pc_col), ('sw', sw_col),
                              ('porosity', por_col), ('permeability', perm_col),
                              ('system', system_col), ('rock_type', rt_col),
                              ('sigma', sigma_col), ('theta', theta_col))}

        def num(col):
            if not col:
                return np.full(n, np.nan)
            return pd.to_numeric(df[col], errors='coerce').to_numpy(dtype=float)

        pc, sw = num(pc_col), num(sw_col)
        depth, phi, perm = num(depth_col), num(por_col), num(perm_col)
        sigma, theta = num(sigma_col), num(theta_col)

        if self.well_col:
            depth_for_fill = depth if depth_col else pc
            self.fill_down_applicable = merged_cell_pattern_applies(
                wells_txt, depth_for_fill.tolist())
            self.fill_down = bool(fill_down)
            if fill_down:
                filled = fill_down_wells(wells_txt)
                self.filled_rows = [lines[i] for i, w in enumerate(wells_txt)
                                    if not w and filled[i]]
                wells_txt = [f or '' for f in filled]

        nulls = np.asarray(COMMON_NULL_VALUES, dtype=float)
        sys_txt = [_cell_text(v) for v in df[system_col]] if system_col else [''] * n
        sys_norm: List[Optional[str]] = [normalize_system(t) if t else None for t in sys_txt]

        keep = np.ones(n, dtype=bool)

        def drop(i, reason):
            keep[i] = False
            self.excluded_rows.append((lines[i], reason))
            self.excluded_row_wells[lines[i]] = wells_txt[i] if self.well_col else ''

        for i in range(n):
            if self.well_col and not wells_txt[i]:
                self.blank_well_rows.append(lines[i])
                drop(i, "no well (blank well cell)")
            elif not np.isfinite(pc[i]):
                raw = df[pc_col].iloc[i]
                drop(i, "missing Pc" if _is_blank(raw) else f"non-numeric Pc {str(raw)!r}")
            elif np.isin(pc[i], nulls):
                drop(i, "null sentinel in Pc")
            elif pc[i] <= 0:
                drop(i, "Pc not positive")
            elif not np.isfinite(sw[i]):
                raw = df[sw_col].iloc[i]
                drop(i, "missing saturation" if _is_blank(raw)
                     else f"non-numeric saturation {str(raw)!r}")
            elif np.isin(sw[i], nulls):
                drop(i, "null sentinel in saturation")
            elif depth_col and not np.isfinite(depth[i]) and not _is_blank(df[depth_col].iloc[i]):
                drop(i, f"non-numeric depth {str(df[depth_col].iloc[i])!r}")
            elif sys_txt[i] and sys_norm[i] is None:
                drop(i, f"unknown system {sys_txt[i]!r}")

        # Null sentinels and non-physical values in the optional numbers: blank the value.
        counts: Dict[str, int] = {}

        def blank(arr, mask, label, key):
            mask = mask & keep
            if not mask.any():
                return
            for i in np.flatnonzero(mask):
                self.excluded_rows.append((lines[i], f"{label} (value excluded)"))
                self.excluded_row_wells[lines[i]] = wells_txt[i] if self.well_col else ''
            counts[key] = counts.get(key, 0) + int(mask.sum())
            arr[mask] = np.nan

        for arr, name in ((depth, 'depth'), (phi, 'porosity'), (perm, 'permeability')):
            if (name == 'depth' and depth_col) or (name == 'porosity' and por_col) \
                    or (name == 'permeability' and perm_col):
                blank(arr, np.isin(arr, nulls), f"null sentinel in {name}", 'null_sentinel')
        if por_col:
            blank(phi, np.isfinite(phi) & (phi < 0), "negative porosity", 'negative_porosity')
        if perm_col:
            blank(perm, np.isfinite(perm) & (perm <= 0), "permeability not positive",
                  'nonpositive_perm')
        labels = {'null_sentinel': "null sentinel value(s)",
                  'negative_porosity': "negative porosity value(s)",
                  'nonpositive_perm': "non-positive permeability value(s)"}
        for reason, cnt in counts.items():
            self.notes.append(f"{cnt} {labels[reason]} excluded.")

        # Saturation: percent or fraction per well by the median; Sw = 1 - S_Hg.
        wkeys = self._group_keys_of(wells_txt if self.well_col else [''] * n)
        sw_frac = sw.copy()
        sw_scales: Dict[str, str] = {}
        for key in dict.fromkeys(wkeys[keep]):
            mask = (wkeys == key) & keep
            finite = sw[mask][np.isfinite(sw[mask])]
            median = float(np.median(finite)) if len(finite) else 0.0
            scale = 'percent' if median > 1.0 else 'fraction'
            sw_scales[key] = scale
            if scale == 'percent':
                sw_frac[mask] = sw[mask] / 100.0
        if self.sw_is_hg:
            sw_frac = 1.0 - sw_frac
        bad = keep & ((sw_frac < -_SW_TOLERANCE) | (sw_frac > 1.0 + _SW_TOLERANCE))
        for i in np.flatnonzero(bad):
            drop(i, f"Sw {sw[i]:g} out of range")
        sw_frac = np.clip(sw_frac, 0.0, 1.0)
        self.sw_scales = sw_scales

        if not keep.any():
            self.last_error = "No valid Pc data after cleaning"
            logger.warning("No valid Pc data after cleaning")
            return False

        # Porosity: percent or fraction per well, like core.
        por_scales: Dict[str, str] = {}
        phi_frac = phi.copy()
        por_raw = phi.copy()
        if por_col:
            forced: Dict[str, str] = {}
            if isinstance(porosity_scale, dict):
                forced = {group_key(k, self.well_kind): v for k, v in porosity_scale.items()}
            elif porosity_scale in ('percent', 'fraction'):
                forced = {k: porosity_scale for k in set(wkeys[keep])}
            for key in dict.fromkeys(wkeys[keep]):
                mask = (wkeys == key) & keep
                finite = phi[mask][np.isfinite(phi[mask])]
                median = float(np.median(finite)) if len(finite) else 0.0
                scale = forced.get(key) or ('percent' if median > 1.0 else 'fraction')
                por_scales[key] = scale
                if scale == 'percent':
                    phi_frac[mask] = phi[mask] / 100.0
            over = keep & np.isfinite(phi_frac) & (phi_frac > 1.0)
            for i in np.flatnonzero(over):
                self.excluded_rows.append(
                    (lines[i], f"porosity {phi[i]:g} out of range (value excluded)"))
                self.excluded_row_wells[lines[i]] = wells_txt[i] if self.well_col else ''
            phi_frac[over] = np.nan
        self._scales_by_group = por_scales

        # Sample names. Within a well the id column groups the points; without it
        # (or for a blank id) points of equal depth, porosity and permeability form a curve.
        samp_txt = ([_cell_text(v) for v in df[sample_col]] if sample_col else [''] * n)
        names: Dict[tuple, str] = {}
        counters: Dict[str, int] = {}
        used = {(wkeys[i], samp_txt[i]) for i in range(n) if keep[i] and samp_txt[i]}
        sample_of = [''] * n
        for i in np.flatnonzero(keep):
            wk = wkeys[i]
            if samp_txt[i]:
                sample_of[i] = samp_txt[i]
                continue
            ident = (wk, None if not np.isfinite(depth[i]) else float(depth[i]),
                     None if not np.isfinite(phi[i]) else float(phi[i]),
                     None if not np.isfinite(perm[i]) else float(perm[i]))
            if ident not in names:
                while True:
                    counters[wk] = counters.get(wk, 0) + 1
                    cand = f"S{counters[wk]}"
                    if (wk, cand) not in used:
                        break
                names[ident] = cand
                used.add((wk, cand))
            sample_of[i] = names[ident]

        system_default = chosen_system
        system_col_vals = []
        need = False
        for i in range(n):
            val = sys_norm[i] or system_default
            if keep[i] and val is None:
                need = True
            system_col_vals.append(val or '')
        self.system_in_file = any(sys_norm[i] for i in np.flatnonzero(keep))
        self.system_needed = need

        well_text_col = ([wells_txt[i] for i in range(n)] if self.well_col else [''] * n)
        sig_cos = [sigma_cos(system_col_vals[i] or None, sigma[i], theta[i]) for i in range(n)]
        rt_txt = [_cell_text(v) for v in df[rt_col]] if rt_col else [''] * n

        out = pd.DataFrame({
            'SAMPLE': sample_of, 'WELL': well_text_col,
            'DEPTH': depth, 'PHI': phi_frac, 'K': perm,
            'PC_PSI': pc * factor, 'SW': sw_frac,
            'SYSTEM': system_col_vals, 'ROCK_TYPE': rt_txt, 'SIGMA_COS_LAB': sig_cos,
        })
        out['__wk__'] = wkeys
        out['__line__'] = lines
        out['__por_raw__'] = por_raw
        out = out[keep].reset_index(drop=True)

        # A value the sample has on any of its rows applies to all of them.
        group = out.groupby(['__wk__', 'SAMPLE'], sort=False)
        for col in ('DEPTH', 'PHI', 'K', '__por_raw__'):
            out[col] = out[col].fillna(group[col].transform('first'))
        rt_first = group['ROCK_TYPE'].transform(
            lambda s: next((v for v in s if v), ''))
        out['ROCK_TYPE'] = rt_first

        order = np.argsort(out['DEPTH'].to_numpy(dtype=float), kind='stable')
        out = out.iloc[order].reset_index(drop=True)
        self._row_lines = out.pop('__line__').to_numpy(dtype=int)
        self._por_raw = out.pop('__por_raw__').to_numpy(dtype=float)
        out.pop('__wk__')
        self.data = out[PC_COLUMNS].copy()
        if not self.well_col:
            self.data['WELL'] = ''
        self._publish_scales()

        if self.sw_is_hg:
            self.notes.append("Saturation is mercury (non-wetting); Sw = 1 - S_Hg was used.")
        self._set_depth_unit(depth_unit, table, depth_col)
        return True

    def _set_depth_unit(self, depth_unit, table, depth_col):
        if not self.depth_col:
            # No depth column: nothing to convert and nothing to ask.
            self.depth_unit, self.depth_unit_detected = 'FT', True
            return
        if depth_unit != 'Auto':
            self.depth_unit = str(depth_unit).upper()
            self.depth_unit_detected = True
        else:
            tokens = set(_tokenize(str(depth_col)))
            if tokens & _FEET_TOKENS:
                self.depth_unit, self.depth_unit_detected = 'FT', True
            elif tokens & _METER_TOKENS:
                self.depth_unit, self.depth_unit_detected = 'M', True
            elif table.unit_row_unit in ('FT', 'M'):
                self.depth_unit, self.depth_unit_detected = table.unit_row_unit, True
            else:
                self.depth_unit, self.depth_unit_detected = 'FT', False
                self.depth_unit_warning = (
                    "Pc depth unit could not be determined from the column "
                    f"name '{depth_col}'; depths were left unchanged "
                    "(assumed feet). Set the depth unit manually if this is wrong.")
        if self.depth_unit == 'M':
            self.convert_depth_to_feet()

    def convert_depth_to_feet(self):
        """Convert depth from meters to feet to match log data."""
        if self.data is None or self.converted_to_feet or not self.depth_col:
            return
        self.data['DEPTH'] = self.data['DEPTH'] * M_TO_FT
        self.depth_unit = 'FT'
        self.converted_to_feet = True

    # ------------------------------------------------------------------
    # Porosity scale (same behaviour as core)
    # ------------------------------------------------------------------
    def _group_keys(self, df: pd.DataFrame) -> np.ndarray:
        return self._group_keys_of(df['WELL'] if self.well_col else [''] * len(df))

    def _publish_scales(self):
        data = self.data
        labels: Dict[str, str] = {}
        if self.well_col and data is not None:
            for w in data['WELL']:
                labels.setdefault(group_key(w, self.well_kind), str(w))
        self.porosity_scales = {labels.get(k, k or ''): v
                                for k, v in self._scales_by_group.items()}
        distinct = set(self._scales_by_group.values())
        self.porosity_converted = 'percent' in distinct
        self.porosity_scale_mixed = len(distinct) > 1
        self.porosity_scale = next(iter(distinct)) if len(distinct) == 1 else None
        if self.porosity_scale_mixed:
            parts = ", ".join(f"{name}: {scale}" for name, scale in self.porosity_scales.items())
            self.porosity_warning = (
                f"Porosity scale differs between wells ({parts}). Check each well.")
        else:
            self.porosity_warning = None

    def set_porosity_scale(self, scale: str, well: Optional[str] = None) -> int:
        """Override the porosity scale ('percent' or 'fraction') of this part.

        Re-derives the porosity from the values as read (``well`` limits the change to one
        well). Values above 1 after conversion become NaN. Returns how many became invalid.
        """
        if scale not in ('percent', 'fraction'):
            raise ValueError("scale must be 'percent' or 'fraction'")
        if self.data is None or self.porosity_col is None or self._por_raw is None:
            return 0
        keys = self._group_keys(self.data)
        mask = np.ones(len(keys), dtype=bool)
        if well is not None:
            mask = keys == group_key(well, self.well_kind)
        raw = self._por_raw[mask]
        new = raw / 100.0 if scale == 'percent' else raw
        invalid = np.isfinite(new) & (new > 1.0)
        new = np.where(invalid, np.nan, new)
        values = self.data['PHI'].to_numpy(dtype=float).copy()
        values[mask] = new
        self.data['PHI'] = values
        for key in set(keys[mask]):
            self._scales_by_group[key] = scale
        self._publish_scales()
        return int(invalid.sum())

    # ------------------------------------------------------------------
    # Samples, completion from core
    # ------------------------------------------------------------------
    def _sample_frames(self):
        """``[(well label, sample, index array)]`` in order of first appearance."""
        if self.data is None or self.data.empty:
            return []
        keys = self._group_keys(self.data)
        out = []
        seen: Dict[tuple, List[int]] = {}
        for i, (k, s) in enumerate(zip(keys, self.data['SAMPLE'])):
            seen.setdefault((k, s), []).append(i)
        for (k, s), idx in seen.items():
            out.append((str(self.data['WELL'].iloc[idx[0]]), s, np.asarray(idx)))
        return out

    def incomplete_samples(self) -> List[str]:
        """Samples that lack porosity or permeability."""
        names = []
        phi = self.data['PHI'].to_numpy(dtype=float) if self.data is not None else []
        perm = self.data['K'].to_numpy(dtype=float) if self.data is not None else []
        for _well, sample, idx in self._sample_frames():
            if not np.isfinite(phi[idx]).any() or not np.isfinite(perm[idx]).any():
                names.append(sample)
        return names

    def complete_from_core(self, core=None) -> int:
        """Fill missing porosity and permeability from core data, then drop what stays blank.

        ``core`` is a :class:`~modules.core_handler.CoreDataHandler` (depths in feet) of the
        well these samples belong to, or None. A sample's blank porosity or permeability
        is taken from the nearest core value within ``PAIR_TOLERANCE_FT`` of the sample
        depth. Samples that still lack either are excluded as a whole with the reason
        "no porosity / permeability". Call it on a single-well part; calling it twice
        changes nothing the second time.

        Returns:
            The number of samples completed from core.
        """
        if self.data is None or self.data.empty:
            return 0
        por_d = por_v = perm_d = perm_v = np.array([])
        if core is not None:
            try:
                por_d, por_v = core.get_core_porosity()
                perm_d, perm_v = core.get_core_permeability()
            except Exception:
                logger.exception("Could not read core data to complete Pc samples")
        data = self.data.copy()
        phi = data['PHI'].to_numpy(dtype=float).copy()
        perm = data['K'].to_numpy(dtype=float).copy()
        depth = data['DEPTH'].to_numpy(dtype=float)

        def nearest(depths, values, target):
            if len(depths) == 0 or not np.isfinite(target):
                return np.nan
            j = int(np.argmin(np.abs(depths - target)))
            return float(values[j]) if abs(depths[j] - target) < PAIR_TOLERANCE_FT else np.nan

        completed = 0
        drop = np.zeros(len(data), dtype=bool)
        for _well, _sample, idx in self._sample_frames():
            has_phi = np.isfinite(phi[idx]).any()
            has_perm = np.isfinite(perm[idx]).any()
            if has_phi and has_perm:
                continue
            finite_depth = depth[idx][np.isfinite(depth[idx])]
            at = float(np.median(finite_depth)) if len(finite_depth) else np.nan
            if not has_phi:
                v = nearest(por_d, por_v, at)
                if np.isfinite(v):
                    phi[idx], has_phi = v, True
            if not has_perm:
                v = nearest(perm_d, perm_v, at)
                if np.isfinite(v):
                    perm[idx], has_perm = v, True
            if has_phi and has_perm:
                completed += 1
            else:
                drop[idx] = True
        data['PHI'], data['K'] = phi, perm
        wells = data['WELL'].to_numpy()
        for i in np.flatnonzero(drop):
            line = int(self._row_lines[i])
            self.excluded_rows.append((line, "no porosity / permeability"))
            self.excluded_row_wells[line] = str(wells[i])
        if drop.any():
            keep = ~drop
            self._row_lines = self._row_lines[keep]
            if self._por_raw is not None:
                self._por_raw = self._por_raw[keep]
            data = data[keep].reset_index(drop=True)
            self.notes.append(f"{len(set(zip(wells[drop], self.data['SAMPLE'][drop])))} "
                              "sample(s) without porosity / permeability excluded.")
        self.data = data
        self.completed_samples += completed
        if completed:
            self.notes.append(f"{completed} sample(s) completed from core data.")
        return completed

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------
    def curves(self) -> Dict[str, pd.DataFrame]:
        """One frame per sample, points sorted by Pc.

        Keyed by the sample id; when two wells of one handler use the same id the key is
        ``"WELL / SAMPLE"``.
        """
        if self.data is None or self.data.empty:
            return {}
        multi = len({group_key(n, self.well_kind) for n in self.well_names()}) > 1
        out: Dict[str, pd.DataFrame] = {}
        for well, sample, idx in self._sample_frames():
            frame = self.data.iloc[idx].sort_values('PC_PSI').reset_index(drop=True)
            key = f"{well} / {sample}" if multi and well else sample
            out[key] = frame
        return out

    def n_points(self) -> int:
        return 0 if self.data is None else len(self.data)

    # ------------------------------------------------------------------
    # Multi-well files
    # ------------------------------------------------------------------
    def well_names(self) -> List[str]:
        """Well names in the file's well column, in order of first appearance."""
        if self.data is None or not self.well_col:
            return []
        values = self.data['WELL'].dropna().astype(str).str.strip()
        return [v for v in dict.fromkeys(values) if v]

    def _make_part(self, idx: np.ndarray, spellings: List[str]) -> 'PcDataHandler':
        part = copy.copy(self)
        part.data = self.data.iloc[idx].reset_index(drop=True)
        part.spellings = list(spellings)
        part._row_lines = self._row_lines[idx]
        part.excluded_rows = list(self.excluded_rows)
        part.notes = list(self.notes)
        if self._por_raw is not None:
            part._por_raw = self._por_raw[idx]
        keys = {group_key(s, self.well_kind) for s in spellings}
        part._scales_by_group = {k: v for k, v in self._scales_by_group.items() if k in keys}
        part._publish_scales()
        return part

    def split_by_well(self, group: bool = False) -> Dict[str, 'PcDataHandler']:
        """One PcDataHandler per well (that well's points).

        With ``group=False`` the parts are keyed by the raw well string. With ``group=True``
        spellings of one well form one part, keyed by the first spelling seen;
        ``part.spellings`` lists all of them.
        """
        parts: Dict[str, PcDataHandler] = {}
        names = self.well_names()
        if not names:
            return parts
        labels = self.data['WELL'].astype(str).str.strip().to_numpy()
        if not group:
            for name in names:
                parts[name] = self._make_part(np.flatnonzero(labels == name), [name])
            return parts
        depths = self.data['DEPTH'].to_numpy(dtype=float)
        for _key, spellings in group_well_names(names, self.well_kind).items():
            idx = np.flatnonzero(np.isin(labels, spellings))
            idx = idx[np.argsort(depths[idx], kind='stable')]
            parts[spellings[0]] = self._make_part(idx, spellings)
        return parts

    def to_dataframe(self) -> pd.DataFrame:
        """The Pc points as a DataFrame copy."""
        if self.data is None:
            return pd.DataFrame(columns=PC_COLUMNS)
        return self.data.copy()
