"""Saturation-height stage of the pipeline (pure, no Qt).

``apply_shf`` turns the stored fits, the fluid contacts and the run's own columns into
``SW_SHF``, ``HAFWL`` and ``SW_SHF_RESID`` for one segment of a well. It takes plain
arrays and dicts, so the pipeline and a future service call the same code.
``shf_count_issues`` and ``shf_summary`` build the well-level notes and ``summary["shf"]``
from the counts the segments return.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from modules.param_scopes import UNZONED, normalize_zone
from modules.shf import ALL, BASIS_CORE, BASIS_LOG, ShfFit, sw_shf

# Water density accepted for a contact row (g/cc); outside it the row is refused.
WATER_DENSITY_RANGE = (0.95, 1.25)
K_FLOOR_MD = 0.001
PHI_FLOOR = 0.01
PERM_AUTO_ORDER = ("PERM_RT", "PERM_WR", "PERM_TIMUR")

_COUNT_KEYS = ("samples", "samples_no_contact", "samples_no_tvd", "water_leg_samples",
               "samples_no_kphi", "samples_unclassified", "samples_modelled",
               "pay_fallback_samples")
_COUNT_MAPS = ("unclassified_reasons", "samples_no_model", "samples_pooled")


def new_counts() -> dict:
    out = {k: 0 for k in _COUNT_KEYS}
    out.update({k: {} for k in _COUNT_MAPS})
    return out


def merge_counts(total: dict, part: dict) -> dict:
    """Add the counts of one segment to ``total`` (in place) and return it."""
    for key in _COUNT_KEYS:
        total[key] = int(total.get(key, 0)) + int(part.get(key, 0))
    for key in _COUNT_MAPS:
        into = total.setdefault(key, {})
        for name, n in (part.get(key) or {}).items():
            into[name] = int(into.get(name, 0)) + int(n)
    return total


@dataclass
class ShfStage:
    """Result of :func:`apply_shf` for one segment (all Series share the results index)."""
    sw_shf: pd.Series
    hafwl: pd.Series
    resid: pd.Series
    sw_pay: Optional[pd.Series]          # None unless SHF Sw is used for pay
    counts: dict
    fluids: Dict[str, dict]              # zone label -> densities and contact used
    issues: List[Tuple[str, str]] = field(default_factory=list)   # (code, text), run once per well
    perm_column: Optional[str] = None
    phie_column: Optional[str] = None
    pay_requested: bool = False
    pay_refused: bool = False


def _finite(value) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def fits_from_dicts(fits) -> Dict[str, ShfFit]:
    """Usable fits (status ok) keyed by rock-type text."""
    out = {}
    for key, d in (fits or {}).items():
        fit = ShfFit.from_dict(d)
        if fit.ok:
            out[str(key)] = fit
    return out


def fits_in_use(shf: dict, all_only: bool) -> Dict[str, ShfFit]:
    """The fits that can reach a sample: only ``"All"`` when rock types are not global."""
    usable = fits_from_dicts(shf.get("fits"))
    return {k: f for k, f in usable.items() if k == ALL} if all_only else usable


def fits_basis(fits) -> Optional[str]:
    """``"core_pc"``, ``"log"`` or ``"mixed"`` over the fits; None when there are none."""
    bases = {f.basis for f in fits.values()}
    if not bases:
        return None
    return next(iter(bases)) if len(bases) == 1 else "mixed"


def pay_refused_for(shf: dict, all_only: bool) -> bool:
    """True when SHF Sw may not be used for pay: some fit in use is log-derived."""
    return any(f.basis == BASIS_LOG for f in fits_in_use(shf, all_only).values())


def resolve_perm_column(shf: dict, results, primary_perm: Optional[str]) -> Optional[str]:
    """Permeability column: the chosen one, or for ``auto`` the primary then the first present."""
    choice = str(shf.get("perm_source") or "auto")
    if choice != "auto":
        return choice if choice in results.columns else None
    for name in (primary_perm,) + PERM_AUTO_ORDER:
        if name and name in results.columns:
            return name
    return None


def _contact(label, row, shf, kb, datum, issues):
    """``(fwl_tvd, fluid, water, fluid_density, delta_rho, sigma)`` of one row, or None."""
    fluid = str(row.get("fluid") or "oil").lower()
    fluids = shf.get("fluids") or {}
    sigma = (shf.get("sigma_cos_res") or {}).get(fluid)
    rho = fluids.get(fluid)
    if not _finite(rho) or not _finite(sigma):
        issues.append(("SHF_NO_CONTACT", f"{label}: no density or interfacial tension is set "
                       f"for {fluid}; saturation-height Sw is blank there."))
        return None
    water = row.get("water_density")
    if water is None or water == "":
        water = fluids.get("water")
    elif not (_finite(water) and WATER_DENSITY_RANGE[0] <= float(water) <= WATER_DENSITY_RANGE[1]):
        issues.append(("SHF_NO_CONTACT", f"{label}: water density {water} g/cc is outside "
                       f"{WATER_DENSITY_RANGE[0]:g}-{WATER_DENSITY_RANGE[1]:g} g/cc; the contact "
                       "is not used."))
        return None
    if not _finite(water) or float(water) - float(rho) <= 0:
        issues.append(("SHF_NO_CONTACT", f"{label}: water must be denser than {fluid}; "
                       "the contact is not used."))
        return None
    fwl = float(row["fwl"])
    if datum == "TVDSS":
        if not _finite(kb):
            issues.append(("SHF_NO_CONTACT", f"{label}: the contact is on TVDSS but no KB is set; "
                           "the contact is not used."))
            return None
        fwl += float(kb)
    return fwl, fluid, float(water), float(rho), float(water) - float(rho), float(sigma)


def _resolve_contacts(shf, zone_labels):
    """``({zone: contact or None}, issues)`` for the zones present in one segment."""
    contacts = shf.get("contacts") or {}
    datum = str(contacts.get("datum") or "TVD").upper()
    kb = contacts.get("kb_ft")
    rows = {normalize_zone(z): r for z, r in (contacts.get("zones") or {}).items()}
    default = contacts.get("default")
    out, issues, done = {}, [], {}

    def valid(row):
        return isinstance(row, dict) and _finite(row.get("fwl"))

    for z in zone_labels:
        if valid(rows.get(z)):
            key, row, label = ("zone", z), rows[z], f"Zone {z}"
        elif valid(default):
            key, row, label = ("default",), default, "Default contact"
        else:
            out[z] = None
            continue
        if key not in done:
            done[key] = _contact(label, row, shf, kb, datum, issues)
        out[z] = done[key] + (key[0],) if done[key] else None
    return out, issues


def zone_series(index, zone) -> pd.Series:
    """Normalised zone label per sample from a zone name, a labels Series or None."""
    if zone is None:
        return pd.Series(UNZONED, index=index, dtype=object)
    if isinstance(zone, str):
        return pd.Series(normalize_zone(zone) or UNZONED, index=index, dtype=object)
    lab = pd.Series(zone).reindex(index)
    return lab.map(lambda v: normalize_zone(v) if isinstance(v, str) and v.strip() else UNZONED)


def apply_shf(shf, results, tvd, zones, sw=None, primary_perm=None, all_only=False) -> ShfStage:
    """Saturation-height Sw, height above the FWL and the residual for one segment.

    ``shf`` is ``p["shf"]``; ``results`` the segment's result frame (``phie_source``, a
    permeability column, ``ROCK_TYPE``, ``ROCK_TYPE_SOURCE``); ``tvd`` TVD (ft) per sample;
    ``zones`` the normalised zone label per sample; ``sw`` the resistivity Sw. ``all_only``
    uses the ``"All"`` fit for every sample (rock types fitted per zone, or rock typing off).
    Samples are classified in the order contact, height, permeability and porosity, rock
    type, model; each lands in exactly one count. Pure: nothing is written to ``results``.
    """
    index = results.index
    n = len(index)
    counts = new_counts()
    counts["samples"] = n
    nan = np.full(n, np.nan)
    sw_a = nan if sw is None else np.asarray(sw, dtype=float)

    use_for_pay = bool(shf.get("use_for_pay"))
    refused = use_for_pay and pay_refused_for(shf, all_only)
    usable = fits_in_use(shf, all_only)
    perm_col = resolve_perm_column(shf, results, primary_perm)
    phie_col = str(shf.get("phie_source") or "PHIE")
    issues: List[Tuple[str, str]] = []
    if perm_col is None:
        issues.append(("SHF_NO_PERM_PHI", "The permeability column chosen for saturation height "
                       "is not in this run; saturation-height Sw is blank."))
    if phie_col not in results.columns:
        issues.append(("SHF_NO_PERM_PHI", f"The porosity column {phie_col} chosen for "
                       "saturation height is not in this run; saturation-height Sw is blank."))

    zl = np.asarray(zones, dtype=object)
    labels = list(dict.fromkeys(zl.tolist()))
    contacts, contact_issues = _resolve_contacts(shf, labels)
    issues.extend(contact_issues)
    fwl = nan.copy()
    drho, sig = nan.copy(), nan.copy()
    fluids = {}
    for z in labels:
        c = contacts.get(z)
        if c is None:
            continue
        m = zl == z
        fwl[m], drho[m], sig[m] = c[0], c[4], c[5]
        fluids[z] = {"fluid": c[1], "water_density": c[2], "fluid_density": c[3],
                     "delta_rho": c[4], "fwl_tvd": c[0], "contact": c[6]}

    tvd_a = np.asarray(tvd, dtype=float)
    h = fwl - tvd_a
    has_contact = np.isfinite(fwl)
    no_tvd = has_contact & ~np.isfinite(tvd_a)
    live = has_contact & ~no_tvd
    counts["samples_no_contact"] = int((~has_contact).sum())
    counts["samples_no_tvd"] = int(no_tvd.sum())

    out = nan.copy()
    water = live & (h <= 0)
    out[water] = 1.0
    counts["water_leg_samples"] = int(water.sum())
    live &= ~water

    k = (np.asarray(results[perm_col], dtype=float) if perm_col else nan)
    phi = (np.asarray(results[phie_col], dtype=float) if phie_col in results.columns else nan)
    bad = live & ~(np.isfinite(k) & (k > 0) & np.isfinite(phi) & (phi > 0))
    counts["samples_no_kphi"] = int(bad.sum())
    live &= ~bad

    if all_only or "ROCK_TYPE" not in results.columns:
        types = np.full(n, ALL, dtype=object)
    else:
        rt = np.nan_to_num(np.asarray(results["ROCK_TYPE"], dtype=float), nan=0.0).astype(int)
        unclassified = live & (rt <= 0)
        counts["samples_unclassified"] = int(unclassified.sum())
        if "ROCK_TYPE_SOURCE" in results.columns and unclassified.any():
            src = np.asarray(results["ROCK_TYPE_SOURCE"], dtype=object)[unclassified]
            for s in pd.Series(src).fillna("").map(lambda v: v or "log").value_counts().items():
                counts["unclassified_reasons"][str(s[0])] = int(s[1])
        live &= ~unclassified
        types = rt.astype(str).astype(object)

    use = np.full(n, "", dtype=object)       # fit key applied to each sample
    for key in dict.fromkeys(types[live].tolist()):
        m = live & (types == key)
        if key in usable:
            use[m] = key
        elif str(shf.get("fallback")) == "pooled" and ALL in usable:
            use[m] = ALL
            counts["samples_pooled"][key] = int(m.sum())
        else:
            counts["samples_no_model"][key] = int(m.sum())
    modelled = use != ""
    for fit_key in dict.fromkeys(use[modelled].tolist()):
        for z in labels:
            m = modelled & (use == fit_key) & (zl == z)
            if not m.any():
                continue
            out[m] = sw_shf(h[m], np.maximum(k[m], K_FLOOR_MD), np.maximum(phi[m], PHI_FLOOR),
                            usable[fit_key], float(drho[m][0]), float(sig[m][0]))
    counts["samples_modelled"] = int(np.isfinite(out).sum())

    sw_shf_s = pd.Series(out, index=index)
    sw_pay = None
    if use_for_pay and not refused:
        sw_pay = pd.Series(np.where(np.isfinite(out), out, sw_a), index=index)
        counts["pay_fallback_samples"] = int((~np.isfinite(out)).sum())
    return ShfStage(
        sw_shf=sw_shf_s, hafwl=pd.Series(np.where(np.isfinite(fwl), h, np.nan), index=index),
        resid=pd.Series(sw_a - out, index=index), sw_pay=sw_pay, counts=counts, fluids=fluids,
        issues=issues, perm_column=perm_col, phie_column=phie_col,
        pay_requested=use_for_pay, pay_refused=refused)


def shf_count_issues(counts: dict, pay_requested: bool, pay_refused: bool) -> List[Tuple[str, str, Optional[str]]]:
    """``(code, text, severity)`` notes from the merged counts of a well (severity None = default)."""
    out = []
    n = counts.get("samples_no_contact", 0)
    if n:
        out.append(("SHF_NO_CONTACT", f"Saturation height: {n} samples have no free water "
                    "level for their zone; their saturation-height Sw is blank.", None))
    n = counts.get("samples_no_tvd", 0)
    if n:
        out.append(("SHF_NO_CONTACT", f"Saturation height: {n} samples have no TVD; their "
                    "saturation-height Sw is blank.", None))
    n = counts.get("samples_no_kphi", 0)
    if n:
        out.append(("SHF_NO_PERM_PHI", f"Saturation height: {n} samples have no usable "
                    "permeability or porosity; their saturation-height Sw is blank.", None))
    n = counts.get("samples_unclassified", 0)
    if n:
        reasons = ", ".join(f"{k} {v}" for k, v in sorted(counts["unclassified_reasons"].items()))
        out.append(("SHF_UNCLASSIFIED", f"Saturation height: {n} samples have no rock type"
                    + (f" ({reasons})" if reasons else "") + "; their saturation-height Sw is "
                    "blank.", None))
    for key, v in sorted(counts.get("samples_no_model", {}).items()):
        out.append(("SHF_NO_MODEL", f"Saturation height: {v} samples of rock type {key} have no "
                    "fitted curve; their saturation-height Sw is blank.", None))
    for key, v in sorted(counts.get("samples_pooled", {}).items()):
        out.append(("SHF_NO_MODEL", f"Saturation height: {v} samples of rock type {key} use the "
                    "pooled curve.", "info"))
    if pay_refused:
        out.append(("SHF_PAY_REFUSED", "Saturation-height Sw is not used for pay in this well: "
                    "a log-derived fit is a cross-check only. Pay uses the resistivity Sw.", None))
    elif pay_requested and counts.get("pay_fallback_samples"):
        out.append(("SHF_PAY_FALLBACK", f"Pay Sw: saturation height, "
                    f"{counts['pay_fallback_samples']} samples from resistivity.", None))
    return out


def _stats(sw, sws, mask) -> dict:
    m = mask & np.isfinite(sw) & np.isfinite(sws)
    n = int(m.sum())
    if n == 0:
        return {"n": 0, "bias": None, "rmse": None, "mae": None, "r2": None}
    d = sw[m] - sws[m]
    sst = float(((sw[m] - sw[m].mean()) ** 2).sum())
    return {"n": n, "bias": float(d.mean()), "rmse": float(np.sqrt((d ** 2).mean())),
            "mae": float(np.abs(d).mean()),
            "r2": float(1.0 - (d ** 2).sum() / sst) if n > 1 and sst > 0 else None}


def shf_summary(shf, results, counts, fluids, tvd_label, perm_column, phie_column,
                pay_requested, pay_refused, all_only, contacts_used=None) -> dict:
    """``summary["shf"]`` from the finished results of a well and the merged stage outputs.

    Misfit statistics use the comparison mask: net reservoir, above the contact, finite
    ``SW`` and ``SW_SHF``; ``bias`` is the mean ``SW - SW_SHF``.
    """
    usable = fits_in_use(shf, all_only)
    sw = np.asarray(results["SW"], dtype=float) if "SW" in results else np.full(len(results), np.nan)
    sws = np.asarray(results["SW_SHF"], dtype=float)
    mask = (np.asarray(results["HAFWL"], dtype=float) > 0)
    if "NET_RES_FLAG" in results:
        mask &= np.asarray(results["NET_RES_FLAG"], dtype=float) == 1
    basis = fits_basis(usable)

    def basis_of(key):
        if all_only or str(key) not in usable:
            fit = usable.get(ALL) if (all_only or shf.get("fallback") == "pooled") else None
        else:
            fit = usable[str(key)]
        return None if fit is None else fit.basis

    zones = []
    if "ZONE" in results.columns:
        zl = results["ZONE"].astype(object).where(results["ZONE"].notna(), UNZONED).to_numpy()
        for z in dict.fromkeys(zl.tolist()):
            zones.append({"zone": str(z), **_stats(sw, sws, mask & (zl == z)), "basis": basis})
    rock_types = []
    if "ROCK_TYPE" in results.columns and not all_only:
        rt = np.nan_to_num(np.asarray(results["ROCK_TYPE"], dtype=float), nan=0.0).astype(int)
        for r in sorted(set(rt[rt > 0].tolist())):
            rock_types.append({"rock_type": int(r), **_stats(sw, sws, mask & (rt == r)),
                               "basis": basis_of(r)})
    return {
        "basis": basis,
        "use_for_pay": bool(pay_requested),
        "pay_active": bool(pay_requested and not pay_refused),
        "pay_refused": bool(pay_refused),
        "tvd_source": tvd_label,
        "perm_source": perm_column,
        "phie_source": phie_column,
        "rock_type_basis": "All" if all_only else "ROCK_TYPE",
        "fallback": str(shf.get("fallback") or "none"),
        "fits": {k: {"model": f.model, "basis": f.basis, "n_samples": f.n_samples}
                 for k, f in usable.items()},
        "fluids": {k: dict(v) for k, v in fluids.items()},
        "contacts": contacts_used or {},
        "counts": {k: (dict(v) if isinstance(v, dict) else v) for k, v in counts.items()},
        "stats": {"well": {**_stats(sw, sws, mask), "basis": basis},
                  "zones": zones, "rock_types": rock_types},
    }
