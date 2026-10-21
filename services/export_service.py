"""
Export Service for Petrophyter PyQt
Handles export functionality for results.
"""

from PyQt6.QtCore import QObject, pyqtSignal
import io
import json
import math
import os
import re
import tempfile
from contextlib import contextmanager

import pandas as pd

from modules.las_handler import export_merged_las
from services.issues import collect_issues, issue_counts
from version import APP_BUILD, APP_VERSION


@contextmanager
def _atomic_target(file_path: str, temporary_suffix: str = None):
    """Yield a same-directory temporary path and atomically publish it."""
    final_path = os.fspath(file_path)
    directory = os.path.dirname(os.path.abspath(final_path)) or "."
    prefix = f".{os.path.basename(final_path)}."
    suffix = temporary_suffix or os.path.splitext(final_path)[1] or ".tmp"
    fd, temporary_path = tempfile.mkstemp(
        prefix=prefix, suffix=suffix, dir=directory
    )
    os.close(fd)
    try:
        yield temporary_path
        os.replace(temporary_path, final_path)
    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


SUMMARY_COLUMNS = ["Parameter", "Scope", "Value", "Source"]


def _param_source_rows(param_sources: dict) -> list:
    """``summary["param_sources"]`` as (Parameter, Scope, Value, Source) rows.

    Scope is ``well``, the zone name or ``temperature``. Entries that hold a
    ``value`` and a ``source`` fill those columns; the flat temperature record
    gives one row per field with an empty Source.
    """
    rows = []
    for scope, table in (param_sources or {}).items():
        label = "well" if scope == "(well)" else str(scope)
        if not isinstance(table, dict):
            continue
        for name, entry in table.items():
            if isinstance(entry, dict) and ("value" in entry or "source" in entry):
                value, source = entry.get("value"), entry.get("source")
            else:
                value, source = entry, None
            if isinstance(value, (dict, list, tuple, set)):
                value = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
            rows.append((str(name), label, "" if value is None else value,
                         "" if source is None else str(source)))
    return rows


def _summary_frame(summary: dict) -> pd.DataFrame:
    """Serialize summary values into Excel-safe rows.

    Columns Parameter, Scope, Value, Source. Plain summary values have an
    empty Scope and Source; ``param_sources`` becomes one row per parameter
    and scope (well / zone name / temperature) instead of a JSON string.
    """
    if not isinstance(summary, dict):
        raise ValueError("summary must be a dictionary")

    rows, sources = [], []
    for key, value in summary.items():
        if key == "param_sources" and isinstance(value, dict):
            sources = _param_source_rows(value)
            continue
        if isinstance(value, (dict, list, tuple, set)):
            value = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
        elif value is None:
            value = ""
        rows.append((str(key), "", value, ""))
    return pd.DataFrame(rows + sources, columns=SUMMARY_COLUMNS)


def _validate_results(results: pd.DataFrame) -> None:
    if not isinstance(results, pd.DataFrame):
        raise ValueError("results must be a pandas DataFrame")
    _check_unique_columns(results)


def _check_unique_columns(df: pd.DataFrame) -> None:
    """Refuse a frame with duplicate column names (they break every writer)."""
    names = [str(c) for c in df.columns]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(
            "duplicate column names: " + ", ".join(duplicates)
            + " (rename or remove the duplicate curves before exporting)")


# H2: text a spreadsheet would read as a formula or command.
_RISKY_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _is_number_text(text: str) -> bool:
    try:
        float(text.strip())
    except ValueError:
        return False
    return True


def _csv_safe_text(value):
    """Prefix a risky text value with ``'`` unless it is just a number."""
    if (isinstance(value, str) and value.startswith(_RISKY_PREFIXES)
            and not _is_number_text(value)):
        return "'" + value
    return value


def spreadsheet_safe(df: pd.DataFrame, csv: bool = False) -> pd.DataFrame:
    """Copy of ``df`` whose text cells and headers cannot run as a formula.

    Only text cells and column headers are touched, never numeric columns.
    CSV (``csv=True``): risky text that is not a number gets a leading ``'``.
    Excel: the copy is unchanged here; :func:`_write_excel_sheet` marks cells
    that start with ``=`` as strings after ``to_excel`` so the visible text
    stays the same.
    """
    _check_unique_columns(df)
    out = df.copy()
    if not csv:
        return out
    for column in out.columns:
        if _is_text_column(out[column]):
            out[column] = out[column].map(_csv_safe_text)
    out.columns = [_csv_safe_text(c) if isinstance(c, str) else c
                   for c in out.columns]
    return out


def _is_text_column(series: pd.Series) -> bool:
    return series.dtype == object or pd.api.types.is_string_dtype(series)


def _write_excel_sheet(writer, df: pd.DataFrame, sheet_name: str,
                       startrow: int = 0, header: bool = True) -> None:
    """``to_excel`` with every ``=...`` header or text cell written as a literal string.

    openpyxl turns a string that starts with ``=`` into a formula; such cells
    are marked as strings after writing, so the visible text is unchanged.
    Only the header row and text columns are scanned (numeric columns cannot
    hold a formula), which keeps large result sheets fast. ``startrow`` writes
    below rows already on the sheet; ``header=False`` omits the column names.
    """
    safe = spreadsheet_safe(df)
    safe.to_excel(writer, sheet_name=sheet_name, index=False, startrow=startrow, header=header)
    sheet = writer.sheets[sheet_name]

    def literal(cell):
        if isinstance(cell.value, str) and cell.value.startswith("="):
            cell.data_type = "s"

    if header:
        for cell in sheet[startrow + 1]:
            literal(cell)
    first = startrow + (2 if header else 1)
    for index, column in enumerate(safe.columns, start=1):
        if _is_text_column(safe[column]):
            for (cell,) in sheet.iter_rows(min_row=first, min_col=index, max_col=index):
                literal(cell)


# ---------------------------------------------------------------------------
# Multi-well helpers (spec 2026-10-10 section 4.8): pure functions over a list
# of WellDataset objects, shared by the Summary tab and the exporters.
# ---------------------------------------------------------------------------
SUMMARY_SHEET = "Summary"
ZONES_SHEET = "Zones"
PROVENANCE_SHEET = "Provenance"
ROCKTYPES_SHEET = "Rock Types"
UNCERTAINTY_SHEET = "Uncertainty"
TORNADO_SHEET = "Tornado"
FIELD_TOTAL_LABEL = "Field total"

WELL_COLUMNS = [
    "Well", "Status", "Gross", "Net", "N/G", "Avg PHIE", "Avg Sw", "HCPV",
    "Rw", "Rw source", "Rsh", "Rsh source", "QC score",
]
ZONE_COLUMNS = [
    "Well", "Zone", "Top", "Bottom", "Gross", "Net", "N/G", "Avg PHIE",
    "Avg Sw", "HCPV", "a", "m", "n", "Rw", "Rsh", "Vsh cutoff", "Phi cutoff",
    "Sw cutoff", "Param sources",
]
STATUS_LABELS = {
    "run_ok": "Run", "stale": "Out of date", "error": "Error",
    "loaded": "Not run", "empty": "Empty",
}
_ILLEGAL_NAME_CHARS = re.compile(r'[\\/:*?"<>|\[\]\x00-\x1f]')
_NAN = float("nan")


def _num(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _NAN
    return number if math.isfinite(number) else _NAN


def sanitize_name(name, max_len: int = 0, fallback: str = "Well") -> str:
    """Make ``name`` safe for a sheet title / file name (illegal characters -> ``_``)."""
    text = _ILLEGAL_NAME_CHARS.sub("_", str(name or "")).strip().strip("'").strip(" .")
    if max_len:
        text = text[:max_len].rstrip(" .")
    return text or fallback


def unique_names(names, max_len: int = 0, reserved=()) -> list:
    """Sanitized, case-insensitively unique names (``X``, ``X (2)`` ...)."""
    used = {str(r).lower() for r in reserved}
    out = []
    for name in names:
        base = sanitize_name(name, max_len)
        candidate, n = base, 2
        while candidate.lower() in used:
            suffix = f" ({n})"
            candidate = (base[: max_len - len(suffix)] if max_len else base) + suffix
            n += 1
        used.add(candidate.lower())
        out.append(candidate)
    return out


def well_label(ds) -> str:
    return ds.display_name or ds.key


def wells_with_results(wells) -> list:
    return [ds for ds in wells
            if getattr(ds, "results", None) is not None and ds.calculated]


def qc_score(ds) -> float:
    report = getattr(ds, "qc_report", None)
    return _num(getattr(report, "overall_quality_score", None))


FIELD_TOTAL_RULE = (
    "The Field total adds up wells whose results are current or out of date. "
    "Wells whose latest run failed are left out of it."
)


def export_blockers(wells) -> dict:
    """The wells of an export scope by freshness (P0-UI/UX U3).

    ``ready`` (run, current), ``out_of_date`` (stale), ``failed`` (latest run
    failed, earlier results kept), ``failed_no_results`` (latest run failed,
    nothing to export) and ``no_results`` (never run). Each value is a list of
    datasets in the order given.
    """
    out = {"ready": [], "out_of_date": [], "failed": [],
           "failed_no_results": [], "no_results": []}
    for ds in wells:
        has_results = getattr(ds, "results", None) is not None and ds.calculated
        status = ds.status
        if status == "error":
            out["failed" if has_results else "failed_no_results"].append(ds)
        elif status == "stale" and has_results:
            out["out_of_date"].append(ds)
        elif status == "run_ok" and has_results:
            out["ready"].append(ds)
        else:
            out["no_results"].append(ds)
    return out


def _plural(n: int, word: str = "well") -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def blockers_text(blockers: dict, with_ready: bool = False) -> str:
    """``"2 wells out of date · 1 latest run failed"`` (empty when all is current)."""
    stale = len(blockers["out_of_date"])
    failed = len(blockers["failed"]) + len(blockers["failed_no_results"])
    parts = []
    if with_ready:
        parts.append(f"{_plural(len(blockers['ready']))} ready")
        if stale:
            parts.append(f"{stale} out of date")
    elif stale:
        parts.append(f"{_plural(stale)} out of date")
    if failed:
        parts.append(f"{failed} latest run failed")
    return " · ".join(parts)


# Status at export, as written in the provenance block.
PROVENANCE_STATUS = {
    "run_ok": "Current", "stale": "Out of date", "error": "Latest run failed",
    "loaded": "Not run", "empty": "Empty",
}


ALL_DEPTHS = "All depths"


def depth_interval_label(depth_range=None) -> str:
    """``"All depths"`` or ``"Selected interval (1000\u20131019 ft)"`` (U9)."""
    if not depth_range:
        return ALL_DEPTHS
    top, bottom = depth_range
    return f"Selected interval ({top:g}\u2013{bottom:g} ft)"


def apply_depth_range(df: pd.DataFrame, depth_range=None) -> pd.DataFrame:
    """Rows of ``df`` inside ``depth_range`` (inclusive); ``df`` itself when no interval."""
    if not depth_range or "DEPTH" not in df.columns:
        return df
    top, bottom = depth_range
    return df[(df["DEPTH"] >= top) & (df["DEPTH"] <= bottom)]


def library_versions() -> dict:
    """``{"numpy": "2.1.0", ...}`` for the libraries that shape the numbers."""
    from importlib import metadata

    versions = {}
    for name in ("numpy", "scipy", "pandas", "lasio"):
        try:
            versions[name] = metadata.version(name)
        except Exception:
            versions[name] = "not installed"
    return versions


def _source_summary(ds) -> str:
    """``a.las sha256:<hash> (123 bytes); b.las ...``, one entry per source file."""
    parts = []
    for source in getattr(ds, "sources", None) or []:
        name = source.get("name") or os.path.basename(str(source.get("path") or "")) or "file"
        text = f"{name} sha256:{source.get('sha256') or 'unknown'}"
        if source.get("size") is not None:
            text += f" ({source['size']} bytes)"
        parts.append(text)
    return "; ".join(parts) if parts else "unknown"


def _recipe_summary(ds) -> str:
    recipe = getattr(ds, "merge_recipe", None)
    if not recipe:
        return "single file" if not getattr(ds, "merged", False) else "unknown"
    return (f"step {recipe.get('step'):g} ft, gap limit {recipe.get('gap_limit'):g} ft, "
            f"policy {recipe.get('policy')}")


def _import_summary(path, sha) -> str:
    if not path:
        return "none"
    return f"{os.path.basename(str(path))} sha256:{sha or 'unknown'}"


def provenance_block(ds, depth_range=None) -> dict:
    """What produced a well's exported numbers (P0-UI/UX U3), as ordered key/value pairs.

    App version and build, the run time (UTC), the well's status at export,
    the parameter hash of the run, the issue counts of the last run and the
    depth interval of the exported rows (``depth_range`` or all depths, U9). This
    is also the run manifest (P0-Hardening H3): the source fingerprints, the merge
    recipe, the tops / core hashes and the versions of numpy, scipy, pandas and lasio.
    """
    counts = issue_counts(collect_issues(ds))
    return {
        "Well": well_label(ds),
        "App version": APP_VERSION,
        "Build": APP_BUILD,
        **library_versions(),
        "Source files": _source_summary(ds),
        "Merge recipe": _recipe_summary(ds),
        "Tops file": _import_summary(getattr(ds, "tops_path", None), getattr(ds, "tops_sha256", None)),
        "Core file": _import_summary(getattr(ds, "core_path", None), getattr(ds, "core_sha256", None)),
        "Run time": getattr(ds, "run_time", None) or "unknown",
        "Status at export": PROVENANCE_STATUS.get(ds.status, ds.status),
        "Parameter hash": getattr(ds, "run_params_hash", None) or "unknown",
        "Errors": counts["error"],
        "Warnings": counts["warning"],
        "Info": counts["info"],
        "Depth interval": depth_interval_label(depth_range),
    }


def provenance_lines(block: dict) -> list:
    """The block as plain ``Key: value`` lines (CSV sidecar and LAS ``~Other``)."""
    return [f"{key}: {value}" for key, value in block.items()]


def _las_other_lines(block: dict) -> list:
    return [
        f"Exported by Petrophyter {block['App version']} (Build {block['Build']})",
        f"Run time {block['Run time']} (UTC)",
        f"Status {block['Status at export']}",
        f"Param hash {block['Parameter hash']}",
        f"Sources {block['Source files']}",
        f"Merge recipe {block['Merge recipe']}",
        f"Tops {block['Tops file']}",
        f"Core {block['Core file']}",
        "Libraries " + ", ".join(f"{name} {block[name]}"
                                 for name in ("numpy", "scipy", "pandas", "lasio")),
        f"Issues {block['Errors']} errors, {block['Warnings']} warnings, {block['Info']} info",
        f"Depth interval {block.get('Depth interval', ALL_DEPTHS)}",
    ]


def _las_with_provenance(content: str, block: dict) -> str:
    """Insert a ``~OTHER`` section before the ``~A`` data section."""
    other = ["~OTHER INFORMATION"] + [f" {line}" for line in _las_other_lines(block)] + [""]
    match = re.search(r"^~A", content, re.MULTILINE)
    if match is None:
        return content + "\n" + "\n".join(other)
    return content[:match.start()] + "\n".join(other) + content[match.start():]


def _provenance_frame(block: dict) -> pd.DataFrame:
    """Key/value rows of one well's block (single-well Excel)."""
    return pd.DataFrame(list(block.items()), columns=["Item", "Value"])


def _write_sidecar(file_path: str, blocks: list) -> None:
    """``<name>.provenance.txt`` next to a CSV, written atomically."""
    stem = os.path.splitext(os.fspath(file_path))[0]
    target = stem + ".provenance.txt"
    lines = [f"Exported by Petrophyter {APP_VERSION} (Build {APP_BUILD})",
             f"Data file: {os.path.basename(os.fspath(file_path))}", ""]
    for block in blocks:
        lines.extend(provenance_lines(block))
        lines.append("")
    with _atomic_target(target, ".txt") as temporary_path:
        with open(temporary_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines))


def wells_summary_frame(wells) -> pd.DataFrame:
    """One row per well plus a ``Field total`` row (when any well has a summary).

    Field total rule: Gross, Net and HCPV are sums over wells whose results
    are current or out of date. Wells whose latest run failed are excluded,
    because their current settings produce no result and their earlier
    numbers stand for a configuration that no longer exists; they keep their
    row with the error and blank numbers, as do not-run wells with their
    status. The Field row's Status reads ``"4 wells (1 out of date)"``. N/G is
    total Net / total Gross. Avg PHIE is weighted by each well's net pay
    thickness (sum(avg_i * net_i) / sum(net_i), skipping wells whose average
    is undefined). Avg Sw is weighted by each well's pore thickness in pay,
    ``phih_pay`` = sum(phie * dz) (sum(avg_i * phih_i) / sum(phih_i)); without
    ``phih_pay`` in any summary it falls back to the net pay weights.
    """
    rows = []
    phih_pay = []
    for ds in wells:
        row = {c: _NAN for c in WELL_COLUMNS}
        status = STATUS_LABELS.get(ds.status, ds.status)
        if ds.status == "error" and ds.error:
            status = f"{status}: {' '.join(str(ds.error).split())[:120]}"
        row.update({"Well": well_label(ds), "Status": status,
                    "Rw source": "", "Rsh source": ""})
        summary = ds.summary if ds.summary and ds.calculated and ds.status != "error" else None
        phih_pay.append(_num(summary.get("phih_pay")) if summary else _NAN)
        if summary:
            row.update({
                "Gross": _num(summary.get("gross_sand")),
                "Net": _num(summary.get("net_pay")),
                "N/G": _num(summary.get("ng_pay")),
                "Avg PHIE": _num(summary.get("avg_phie_pay")),
                "Avg Sw": _num(summary.get("avg_sw_pay")),
                "HCPV": _num(summary.get("hcpv_net_pay")),
                "Rw": _num(summary.get("rw")),
                "Rw source": str(summary.get("rw_source") or ""),
                "Rsh": _num(summary.get("rsh")),
                "Rsh source": str(summary.get("rsh_source") or ""),
                "QC score": qc_score(ds),
            })
        rows.append(row)
    df = pd.DataFrame(rows, columns=WELL_COLUMNS)
    included = df[df["Gross"].notna() | df["Net"].notna()]
    n_stale = sum(1 for ds, keep in zip(wells, df.index.isin(included.index))
                  if keep and ds.status == "stale")
    if len(df) and len(included):
        net = included["Net"].fillna(0.0)

        phih = pd.Series(phih_pay, index=df.index).loc[included.index]

        def weighted(column, weights=net):
            valid = included[column].notna() & (weights > 0)
            weight = weights[valid].sum()
            if weight <= 0:
                return _NAN
            return float((included.loc[valid, column] * weights[valid]).sum() / weight)

        sw_weights = phih.fillna(0.0) if (phih > 0).any() else net

        gross_total = float(included["Gross"].fillna(0.0).sum())
        net_total = float(net.sum())
        total = {c: _NAN for c in WELL_COLUMNS}
        total.update({
            "Well": FIELD_TOTAL_LABEL,
            "Status": _plural(len(included)) + (
                f" ({n_stale} out of date)" if n_stale else ""),
            "Gross": gross_total, "Net": net_total,
            "N/G": net_total / gross_total if gross_total > 0 else _NAN,
            "Avg PHIE": weighted("Avg PHIE"), "Avg Sw": weighted("Avg Sw", sw_weights),
            "HCPV": float(included["HCPV"].fillna(0.0).sum()),
            "Rw source": "", "Rsh source": "",
        })
        df = pd.concat([df, pd.DataFrame([total], columns=WELL_COLUMNS)],
                       ignore_index=True)
    return df


def zones_frame(wells) -> pd.DataFrame:
    """Well x zone rows from each well's ``summary["zones"]`` (empty when none)."""
    rows = []
    for ds in wells:
        summary = ds.summary if ds.summary and ds.calculated and ds.status != "error" else None
        for zone in (summary or {}).get("zones") or []:
            params = zone.get("params") or {}

            def value(name, params=params):
                return _num((params.get(name) or {}).get("value"))

            sources = "; ".join(
                f"{name}={entry.get('source')}" for name, entry in params.items()
                if entry.get("source") not in (None, "", "project"))
            rows.append({
                "Well": well_label(ds), "Zone": zone.get("zone", ""),
                "Top": _num(zone.get("top")), "Bottom": _num(zone.get("bottom")),
                "Gross": _num(zone.get("gross_sand")),
                "Net": _num(zone.get("net_pay")),
                "N/G": _num(zone.get("ng_pay")),
                "Avg PHIE": _num(zone.get("avg_phie_pay")),
                "Avg Sw": _num(zone.get("avg_sw_pay")),
                "HCPV": _num(zone.get("hcpv_net_pay")),
                "a": value("a"), "m": value("m"), "n": value("n"),
                "Rw": value("rw"), "Rsh": value("rsh"),
                "Vsh cutoff": value("vsh_cutoff"), "Phi cutoff": value("phi_cutoff"),
                "Sw cutoff": value("sw_cutoff"), "Param sources": sources,
            })
    return pd.DataFrame(rows, columns=ZONE_COLUMNS)


# ---------------------------------------------------------------------------
# Rock types (P1): per-well rows from summary["rock_types"], a field total
# only when every contributing well shares the project-wide definitions.
# ---------------------------------------------------------------------------
ROCKTYPE_COLUMNS = [
    "Well", "Rock type", "Samples", "Gross", "Net reservoir", "Net pay", "N/G reservoir",
    "N/G pay", "Avg PHIE", "Avg Sw", "Avg Vsh", "PHIH", "HCPV", "Perm geomean", "FZI",
    "% core",
]
UNASSIGNED_LABEL = "Unassigned"
MIXED_DEFINITIONS = "mixed definitions"
# summary row key -> ROCKTYPE_COLUMNS name
_ROCKTYPE_FIELDS = {
    "samples": "Samples", "gross_sand": "Gross", "net_reservoir": "Net reservoir",
    "net_pay": "Net pay", "ng_reservoir": "N/G reservoir", "ng_pay": "N/G pay",
    "avg_phie_pay": "Avg PHIE", "avg_sw_pay": "Avg Sw", "avg_vsh_pay": "Avg Vsh",
    "phih_pay": "PHIH", "hcpv_net_pay": "HCPV", "perm_geomean": "Perm geomean",
    "fzi": "FZI", "pct_core": "% core",
}


def _rock_type_label(rt):
    return UNASSIGNED_LABEL if int(rt) == 0 else int(rt)


def _rock_type_row(well: str, row: dict) -> dict:
    out = {c: _NAN for c in ROCKTYPE_COLUMNS}
    out["Well"] = well
    out["Rock type"] = _rock_type_label(row.get("rt", 0))
    for key, column in _ROCKTYPE_FIELDS.items():
        out[column] = _num(row.get(key))
    return out


def well_rock_type_rows(rock_types: dict, well: str) -> list:
    """Rows of one well's ``summary["rock_types"]``: each rock type, then Unassigned when used."""
    rows = [_rock_type_row(well, r) for r in (rock_types or {}).get("by_rt") or []]
    unassigned = (rock_types or {}).get("unassigned")
    if unassigned and unassigned.get("samples"):
        rows.append(_rock_type_row(well, unassigned))
    return rows


def wells_with_rock_types(wells) -> list:
    """Wells whose current results carry ``summary["rock_types"]``."""
    return [ds for ds in wells
            if ds.summary and ds.calculated and ds.status != "error"
            and ds.summary.get("rock_types")]


def rock_type_field_total(wells) -> dict:
    """Field total per rock type over the wells that have ``summary["rock_types"]``.

    Returns ``{"state": "none" | "mixed" | "ok", "rows": [...]}``. The total exists
    only when every contributing well has ``fit_scope == "project"`` (one shared
    definition set); otherwise ``state`` is ``"mixed"`` and ``rows`` is empty.
    Thickness and HCPV are summed. Avg PHIE and Avg Vsh are weighted by net pay,
    Avg Sw by pore thickness in pay (``phih_pay``, else Avg PHIE x net pay), the
    permeability geomean by net pay. Rows are ``ROCKTYPE_COLUMNS`` rows with
    Well = ``Field total``; N/G is total net over total gross.
    """
    contributing = wells_with_rock_types(wells)
    if not contributing:
        return {"state": "none", "rows": []}
    if any(ds.summary["rock_types"].get("fit_scope") != "project" for ds in contributing):
        return {"state": "mixed", "rows": []}
    groups = {}
    for ds in contributing:
        rt = ds.summary["rock_types"]
        for row in list(rt.get("by_rt") or []) + [rt.get("unassigned") or {}]:
            if row and row.get("samples") is not None:
                groups.setdefault(int(row.get("rt", 0)), []).append(row)
    rows = []
    for code in sorted(c for c in groups if c > 0) + ([0] if 0 in groups else []):
        members = groups[code]
        if code == 0 and not sum(m.get("samples") or 0 for m in members):
            continue

        def total(key, members=members):
            return float(sum(v for v in (_num(m.get(key)) for m in members) if v == v))

        def weighted(key, weight, members=members):
            pairs = [(_num(m.get(key)), weight(m)) for m in members]
            pairs = [(v, w) for v, w in pairs if v == v and w == w and w > 0]
            denominator = sum(w for _, w in pairs)
            return sum(v * w for v, w in pairs) / denominator if denominator > 0 else _NAN

        def net(m):
            return _num(m.get("net_pay"))

        def pore(m):
            phih = _num(m.get("phih_pay"))
            return phih if phih == phih else _num(m.get("avg_phie_pay")) * net(m)

        gross, net_res, net_pay = total("gross_sand"), total("net_reservoir"), total("net_pay")
        samples = total("samples")
        geo = [(_num(m.get("perm_geomean")), net(m)) for m in members]
        geo = [(k, w) for k, w in geo if k == k and k > 0 and w == w and w > 0]
        fzi = next((v for v in (_num(m.get("fzi")) for m in members) if v == v), _NAN)
        core = sum(v * (m.get("samples") or 0) for m in members
                   for v in [_num(m.get("pct_core"))] if v == v)
        out = {c: _NAN for c in ROCKTYPE_COLUMNS}
        out.update({
            "Well": FIELD_TOTAL_LABEL, "Rock type": _rock_type_label(code),
            "Samples": samples, "Gross": gross, "Net reservoir": net_res, "Net pay": net_pay,
            "N/G reservoir": net_res / gross if gross > 0 else _NAN,
            "N/G pay": net_pay / gross if gross > 0 else _NAN,
            "Avg PHIE": weighted("avg_phie_pay", net), "Avg Sw": weighted("avg_sw_pay", pore),
            "Avg Vsh": weighted("avg_vsh_pay", net), "PHIH": total("phih_pay"),
            "HCPV": total("hcpv_net_pay"),
            "Perm geomean": (math.exp(sum(math.log(k) * w for k, w in geo)
                                      / sum(w for _, w in geo)) if geo else _NAN),
            "FZI": fzi, "% core": core / samples if samples > 0 else _NAN,
        })
        rows.append(out)
    return {"state": "ok", "rows": rows}


def rock_types_frame(wells) -> pd.DataFrame:
    """Well x rock type rows (plus Field total rows when definitions are project-wide)."""
    rows = []
    for ds in wells_with_rock_types(wells):
        rows.extend(well_rock_type_rows(ds.summary["rock_types"], well_label(ds)))
    rows.extend(rock_type_field_total(wells)["rows"])
    return pd.DataFrame(rows, columns=ROCKTYPE_COLUMNS)


DEFINITION_COLUMNS = [
    "Set", "Rock type", "Samples", "log10 FZI centre", "FZI", "Lower boundary",
    "Upper boundary", "k RMSE log10", "Method", "Fit scope", "Edited", "Basis",
]


def rock_type_definitions_frame(defs) -> pd.DataFrame:
    """The rock-type definitions (``Project.rock_types``) as one row per set and rock type.

    ``Set`` is ``Project`` for the pooled set (key ``*``), else the well or zone key.
    Boundaries are the cut points on log10(FZI): the lowest type has no lower and the
    highest no upper boundary (blank).
    """
    rows = []
    for key, rset in ((defs or {}).get("sets") or {}).items():
        n = int(rset.get("n_rt") or len(rset.get("fzi") or []))
        bounds = list(rset.get("boundaries") or [])
        for i in range(n):
            def pick(name, i=i, rset=rset):
                values = rset.get(name) or []
                return _num(values[i]) if i < len(values) else _NAN

            rows.append({
                "Set": "Project" if key == "*" else str(key), "Rock type": i + 1,
                "Samples": pick("n_samples"), "log10 FZI centre": pick("centers"),
                "FZI": pick("fzi"),
                "Lower boundary": _num(bounds[i - 1]) if 0 < i <= len(bounds) else _NAN,
                "Upper boundary": _num(bounds[i]) if i < len(bounds) else _NAN,
                "k RMSE log10": pick("k_rmse_log10"),
                "Method": str(defs.get("method") or ""),
                "Fit scope": str(defs.get("fit_scope") or ""),
                "Edited": "yes" if rset.get("edited") else "no",
                "Basis": str(rset.get("basis") or ""),
            })
    return pd.DataFrame(rows, columns=DEFINITION_COLUMNS)


def write_rock_type_definitions_csv(defs, file_path) -> int:
    """Write the definitions table to ``file_path`` (atomic); returns the number of rows."""
    frame = rock_type_definitions_frame(defs)
    if frame.empty:
        raise ValueError("no rock-type definitions to export")
    with _atomic_target(file_path, ".csv") as temporary_path:
        spreadsheet_safe(frame, csv=True).to_csv(temporary_path, index=False)
    return len(frame)


def combined_results(wells, depth_range=None) -> pd.DataFrame:
    """All wells' results stacked, with the well's display name as first column ``WELL``.

    ``depth_range`` keeps only rows inside the interval (U9).
    """
    frames = []
    for ds in wells_with_results(wells):
        frame = apply_depth_range(ds.results, depth_range).copy()
        frame.insert(0, "WELL", well_label(ds))
        frames.append(frame)
    if not frames:
        raise ValueError("no well has results to export")
    return pd.concat(frames, ignore_index=True)


def las_frame(ds) -> pd.DataFrame:
    """Curves for a well's LAS export: its results when analysed, else its log data.

    Only numeric curves are written; text columns such as ``ZONE`` or
    ``FLOW_UNIT`` may contain spaces, which would break the ~A section.
    """
    frame = ds.results if (ds.results is not None and ds.calculated) else ds.las_data
    numeric = [c for c in frame.columns
               if c == "DEPTH" or pd.api.types.is_numeric_dtype(frame[c])]
    return frame[numeric]


def default_file_stem(ds, prefix: str = "petrophyter_results") -> str:
    """``<prefix>_<well>`` for single-well default file names."""
    if ds is None:
        return prefix
    return f"{prefix}_{sanitize_name(well_label(ds), 60, 'well')}"


UNCERTAINTY_COLUMNS = ["Scope", "Well", "Zone", "Metric", "P90", "P50", "P10", "Mean", "Std",
                       "Min", "Max", "N valid", "P(zero)", "Deterministic"]
TORNADO_COLUMNS = ["Scope", "Well", "Zone", "Metric", "Parameter", "Mode", "Low input",
                   "High input", "Low input (text)", "High input (text)", "Output at low",
                   "Output at high", "Swing",
                   "Rank correlation (field)"]
P90_CONVENTION = "P90 = low case, exceeded with 90% probability"


def _uncertainty_scopes(result):
    """(scope key, kind, well name, zone) for the field, each well and each well zone."""
    out = [("field", "Field", "", "")]
    for w in result.wells:
        out.append((w["key"], "Well", w["name"], ""))
        for zone in (result.zones or {}).get(w["key"], []):
            out.append(((w["key"], zone), "Zone", w["name"], str(zone)))
    return out


def uncertainty_header_frame(result, stale: bool) -> pd.DataFrame:
    """Key/value block above the Uncertainty table."""
    from modules.uncertainty import NOT_VARIED

    rows = [
        ("Seed", int(result.seed)),
        ("N", int(result.n)),
        ("Sampling", str(result.sampling)),
        ("Convention", P90_CONVENTION),
        ("Not varied", NOT_VARIED),
        ("Stale", "Yes" if stale else "No"),
    ]
    return pd.DataFrame(rows, columns=["Item", "Value"])


def uncertainty_frame(result) -> pd.DataFrame:
    """One row per scope (field, well, well zone) and metric."""
    from modules.uncertainty import METRIC_LABELS, METRICS

    nan = float("nan")
    rows = []
    for scope, kind, well, zone in _uncertainty_scopes(result):
        for metric in METRICS:
            st = result.stats.get((scope, metric)) or {}
            det = result.deterministic.get((scope, metric))
            rows.append([
                kind, well, zone, METRIC_LABELS.get(metric, metric),
                st.get("p90", nan), st.get("p50", nan), st.get("p10", nan),
                st.get("mean", nan), st.get("std", nan), st.get("min", nan),
                st.get("max", nan), st.get("n_valid", nan), st.get("prob_zero", nan),
                det if det is not None else nan])
    return pd.DataFrame(rows, columns=UNCERTAINTY_COLUMNS)


def tornado_frame(result) -> pd.DataFrame:
    """One row per scope, tornado metric and parameter, largest swing first within each block.

    The rank correlation is the field-level one, so it is filled on field rows only.
    """
    from modules.uncertainty import METRIC_LABELS, format_offset

    nan = float("nan")
    dists = (result.config or {}).get("distributions", {})
    rows = []
    for scope, kind, well, zone in _uncertainty_scopes(result):
        for (sc, metric), entries in (result.tornado or {}).items():
            if sc != scope:
                continue
            rank = (result.rank_corr or {}).get(metric, {}) if scope == "field" else {}
            for e in sorted(entries, key=lambda e: -float(e["swing"])):
                rho = rank.get(e["name"])
                mode = (dists.get(e["name"]) or {}).get("mode", "")
                rows.append([
                    kind, well, zone, METRIC_LABELS.get(metric, metric), e["name"],
                    mode, e["low_input"], e["high_input"],
                    format_offset(e["name"], mode, e["low_input"]),
                    format_offset(e["name"], mode, e["high_input"]),
                    e["at_low_input"], e["at_high_input"],
                    e["swing"], float(rho) if rho is not None else nan])
    return pd.DataFrame(rows, columns=TORNADO_COLUMNS)


def _write_uncertainty_sheets(writer, uncertainty) -> None:
    result, stale = uncertainty["result"], bool(uncertainty.get("stale"))
    header = uncertainty_header_frame(result, stale)
    _write_excel_sheet(writer, header, UNCERTAINTY_SHEET, header=False)
    _write_excel_sheet(writer, uncertainty_frame(result), UNCERTAINTY_SHEET,
                       startrow=len(header) + 1)
    _write_excel_sheet(writer, tornado_frame(result), TORNADO_SHEET)


def _export_wells_excel(wells, file_path, depth_range=None, uncertainty=None):
    """``uncertainty`` is ``{"result": MCResult, "stale": bool}``; None writes no MC sheets."""
    ready = wells_with_results(wells)
    if not ready:
        raise ValueError("no well has results to export")
    names = unique_names([well_label(ds) for ds in ready], 31,
                         reserved=(SUMMARY_SHEET, ZONES_SHEET, PROVENANCE_SHEET,
                                   ROCKTYPES_SHEET, UNCERTAINTY_SHEET, TORNADO_SHEET))
    zones = zones_frame(ready)
    rock_types = rock_types_frame(ready)
    provenance = pd.DataFrame(
        [provenance_block(ds, depth_range) for ds in wells_with_results(wells)])
    with _atomic_target(file_path, ".xlsx") as temporary_path:
        with pd.ExcelWriter(temporary_path, engine="openpyxl") as writer:
            _write_excel_sheet(writer, wells_summary_frame(wells), SUMMARY_SHEET)
            if len(zones):
                _write_excel_sheet(writer, zones, ZONES_SHEET)
            if len(rock_types):
                _write_excel_sheet(writer, rock_types, ROCKTYPES_SHEET)
            if uncertainty is not None and uncertainty.get("result") is not None:
                _write_uncertainty_sheets(writer, uncertainty)
            _write_excel_sheet(writer, provenance, PROVENANCE_SHEET)
            for ds, sheet in zip(ready, names):
                _write_excel_sheet(writer, apply_depth_range(ds.results, depth_range), sheet)


class ExportService(QObject):
    """
    Service for exporting analysis results.
    """
    
    export_complete = pyqtSignal(str)  # success message
    export_error = pyqtSignal(str)  # error message
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def export_csv(self, results: pd.DataFrame, file_path: str, provenance: dict = None) -> bool:
        """Export results to CSV file without corrupting an existing target.

        With ``provenance`` (see :func:`provenance_block`) a sidecar
        ``<name>.provenance.txt`` is written next to the CSV; the CSV is unchanged.
        """
        try:
            _validate_results(results)
            with _atomic_target(file_path) as temporary_path:
                spreadsheet_safe(results, csv=True).to_csv(temporary_path, index=False)
            if provenance:
                _write_sidecar(file_path, [provenance])
            self.export_complete.emit(f"Exported to {file_path}")
            return True
        except PermissionError:
            self.export_error.emit(
                "CSV export failed: close the destination file and check folder permissions"
            )
            return False
        except Exception as e:
            self.export_error.emit(f"CSV export failed: {str(e)}")
            return False

    def export_excel(self, results: pd.DataFrame, summary: dict, file_path: str,
                     provenance: dict = None) -> bool:
        """Export results and a nested-value-safe summary to Excel.

        With ``provenance`` a ``Provenance`` sheet of key/value rows is added.
        """
        try:
            _validate_results(results)
            summary_df = _summary_frame(summary)
            with _atomic_target(file_path, ".xlsx") as temporary_path:
                with pd.ExcelWriter(temporary_path, engine="openpyxl") as writer:
                    _write_excel_sheet(writer, results, "Results")
                    _write_excel_sheet(writer, summary_df, "Summary")
                    if summary.get("rock_types"):
                        rows = well_rock_type_rows(summary["rock_types"],
                                                   (provenance or {}).get("Well", ""))
                        _write_excel_sheet(writer, pd.DataFrame(rows, columns=ROCKTYPE_COLUMNS),
                                           ROCKTYPES_SHEET)
                    if provenance:
                        _write_excel_sheet(writer, _provenance_frame(provenance),
                                           PROVENANCE_SHEET)
            self.export_complete.emit(f"Exported to {file_path}")
            return True
        except PermissionError:
            self.export_error.emit(
                "Excel export failed: close the destination file and check folder permissions"
            )
            return False
        except Exception as e:
            self.export_error.emit(f"Excel export failed: {str(e)}")
            return False

    def export_las(self, merged_df: pd.DataFrame, well_info: dict, file_path: str,
                   provenance: dict = None) -> bool:
        """Export merged data to LAS using UTF-8 and an atomic target.

        With ``provenance`` the file gets a ``~OTHER`` section before the data.
        """
        try:
            if not isinstance(merged_df, pd.DataFrame):
                raise ValueError("merged_df must be a pandas DataFrame")
            las_content = export_merged_las(merged_df, well_info)
            if provenance:
                las_content = _las_with_provenance(las_content, provenance)
            with _atomic_target(file_path) as temporary_path:
                with open(temporary_path, "w", encoding="utf-8") as handle:
                    handle.write(las_content)
            self.export_complete.emit(f"Exported to {file_path}")
            return True
        except PermissionError:
            self.export_error.emit(
                "LAS export failed: close the destination file and check folder permissions"
            )
            return False
        except Exception as e:
            self.export_error.emit(f"LAS export failed: {str(e)}")
            return False

    def export_csv_wells(self, wells, file_path: str, depth_range=None) -> bool:
        """One CSV with every well's results stacked and a ``WELL`` column first."""
        try:
            frame = combined_results(wells, depth_range)
            with _atomic_target(file_path) as temporary_path:
                spreadsheet_safe(frame, csv=True).to_csv(temporary_path, index=False)
            _write_sidecar(file_path, [provenance_block(ds, depth_range)
                                       for ds in wells_with_results(wells)])
            self.export_complete.emit(f"Exported to {file_path}")
            return True
        except PermissionError:
            self.export_error.emit(
                "CSV export failed: close the destination file and check folder permissions"
            )
            return False
        except Exception as e:
            self.export_error.emit(f"CSV export failed: {str(e)}")
            return False

    def export_excel_wells(self, wells, file_path: str, depth_range=None,
                           uncertainty=None) -> bool:
        """Workbook: Summary sheet, Zones sheet (when present), one sheet per well.

        ``uncertainty`` ({"result": MCResult, "stale": bool}) adds Uncertainty and Tornado sheets.
        """
        try:
            _export_wells_excel(wells, file_path, depth_range, uncertainty)
            self.export_complete.emit(f"Exported to {file_path}")
            return True
        except PermissionError:
            self.export_error.emit(
                "Excel export failed: close the destination file and check folder permissions"
            )
            return False
        except Exception as e:
            self.export_error.emit(f"Excel export failed: {str(e)}")
            return False

    def export_las_wells(self, wells, directory: str, depth_range=None) -> bool:
        """One LAS file per well in ``directory``, each with that well's own header.

        A well's file holds its results (input and computed curves) when it has
        been analysed, otherwise its log curves.
        """
        try:
            ready = [ds for ds in wells if ds.las_data is not None]
            if not ready:
                raise ValueError("no well has data to export")
            os.makedirs(directory, exist_ok=True)
            names = unique_names([well_label(ds) for ds in ready])
            for ds, name in zip(ready, names):
                las_content = _las_with_provenance(
                    export_merged_las(apply_depth_range(las_frame(ds), depth_range),
                                      ds.well_info),
                    provenance_block(ds, depth_range))
                with _atomic_target(os.path.join(directory, f"{name}.las")) as tmp:
                    with open(tmp, "w", encoding="utf-8") as handle:
                        handle.write(las_content)
            self.export_complete.emit(f"Exported {len(ready)} LAS files to {directory}")
            return True
        except PermissionError:
            self.export_error.emit(
                "LAS export failed: close the destination files and check folder permissions"
            )
            return False
        except Exception as e:
            self.export_error.emit(f"LAS export failed: {str(e)}")
            return False

    def export_rock_type_definitions(self, defs, file_path: str) -> bool:
        """Write the rock-type definitions table (``Project.rock_types``) to CSV."""
        try:
            write_rock_type_definitions_csv(defs, file_path)
            self.export_complete.emit(f"Exported to {file_path}")
            return True
        except PermissionError:
            self.export_error.emit(
                "CSV export failed: close the destination file and check folder permissions"
            )
            return False
        except Exception as e:
            self.export_error.emit(f"CSV export failed: {str(e)}")
            return False

    def get_csv_string(self, results: pd.DataFrame) -> str:
        """Get CSV data as string."""
        _validate_results(results)
        buffer = io.StringIO()
        spreadsheet_safe(results, csv=True).to_csv(buffer, index=False)
        return buffer.getvalue()

    def get_excel_bytes(self, results: pd.DataFrame, summary: dict,
                        provenance: dict = None) -> bytes:
        """Get Excel data as bytes using the same summary schema as file export."""
        _validate_results(results)
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            _write_excel_sheet(writer, results, "Results")
            _write_excel_sheet(writer, _summary_frame(summary), "Summary")
            if provenance:
                _write_excel_sheet(writer, _provenance_frame(provenance), PROVENANCE_SHEET)
        return buffer.getvalue()
