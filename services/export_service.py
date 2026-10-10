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


def _summary_frame(summary: dict) -> pd.DataFrame:
    """Serialize summary values into Excel-safe key/value rows."""
    if not isinstance(summary, dict):
        raise ValueError("summary must be a dictionary")

    rows = []
    for key, value in summary.items():
        if isinstance(value, (dict, list, tuple, set)):
            value = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
        elif value is None:
            value = ""
        rows.append((str(key), value))
    return pd.DataFrame(rows, columns=["Parameter", "Value"])


def _validate_results(results: pd.DataFrame) -> None:
    if not isinstance(results, pd.DataFrame):
        raise ValueError("results must be a pandas DataFrame")


# ---------------------------------------------------------------------------
# Multi-well helpers (spec 2026-10-10 section 4.8): pure functions over a list
# of WellDataset objects, shared by the Summary tab and the exporters.
# ---------------------------------------------------------------------------
SUMMARY_SHEET = "Summary"
ZONES_SHEET = "Zones"
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


def wells_summary_frame(wells) -> pd.DataFrame:
    """One row per well plus a ``Field total`` row (when any well has a summary).

    Field total: Gross, Net and HCPV are sums over wells that have a summary
    (run or out of date; not-run and error wells are excluded). N/G is
    total Net / total Gross. Avg PHIE and Avg Sw are weighted by each well's
    net pay thickness (sum(avg_i * net_i) / sum(net_i), skipping wells whose
    average is undefined). Not-run wells show their status with blank numbers.
    """
    rows = []
    for ds in wells:
        row = {c: _NAN for c in WELL_COLUMNS}
        row.update({"Well": well_label(ds),
                    "Status": STATUS_LABELS.get(ds.status, ds.status),
                    "Rw source": "", "Rsh source": ""})
        summary = ds.summary if ds.summary and ds.calculated else None
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
    if len(df) and len(included):
        net = included["Net"].fillna(0.0)

        def weighted(column):
            valid = included[column].notna() & (net > 0)
            weight = net[valid].sum()
            if weight <= 0:
                return _NAN
            return float((included.loc[valid, column] * net[valid]).sum() / weight)

        gross_total = float(included["Gross"].fillna(0.0).sum())
        net_total = float(net.sum())
        total = {c: _NAN for c in WELL_COLUMNS}
        total.update({
            "Well": FIELD_TOTAL_LABEL, "Status": f"{len(included)} wells",
            "Gross": gross_total, "Net": net_total,
            "N/G": net_total / gross_total if gross_total > 0 else _NAN,
            "Avg PHIE": weighted("Avg PHIE"), "Avg Sw": weighted("Avg Sw"),
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
        summary = ds.summary if ds.summary and ds.calculated else None
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


def combined_results(wells) -> pd.DataFrame:
    """All wells' results stacked, with the well's display name as first column ``WELL``."""
    frames = []
    for ds in wells_with_results(wells):
        frame = ds.results.copy()
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


def _export_wells_excel(wells, file_path):
    ready = wells_with_results(wells)
    if not ready:
        raise ValueError("no well has results to export")
    names = unique_names([well_label(ds) for ds in ready], 31,
                         reserved=(SUMMARY_SHEET, ZONES_SHEET))
    zones = zones_frame(ready)
    with _atomic_target(file_path, ".xlsx") as temporary_path:
        with pd.ExcelWriter(temporary_path, engine="openpyxl") as writer:
            wells_summary_frame(wells).to_excel(
                writer, sheet_name=SUMMARY_SHEET, index=False)
            if len(zones):
                zones.to_excel(writer, sheet_name=ZONES_SHEET, index=False)
            for ds, sheet in zip(ready, names):
                ds.results.to_excel(writer, sheet_name=sheet, index=False)


class ExportService(QObject):
    """
    Service for exporting analysis results.
    """
    
    export_complete = pyqtSignal(str)  # success message
    export_error = pyqtSignal(str)  # error message
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    def export_csv(self, results: pd.DataFrame, file_path: str) -> bool:
        """Export results to CSV file without corrupting an existing target."""
        try:
            _validate_results(results)
            with _atomic_target(file_path) as temporary_path:
                results.to_csv(temporary_path, index=False)
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

    def export_excel(self, results: pd.DataFrame, summary: dict, file_path: str) -> bool:
        """Export results and a nested-value-safe summary to Excel."""
        try:
            _validate_results(results)
            summary_df = _summary_frame(summary)
            with _atomic_target(file_path, ".xlsx") as temporary_path:
                with pd.ExcelWriter(temporary_path, engine="openpyxl") as writer:
                    results.to_excel(writer, sheet_name="Results", index=False)
                    summary_df.to_excel(writer, sheet_name="Summary", index=False)
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

    def export_las(self, merged_df: pd.DataFrame, well_info: dict, file_path: str) -> bool:
        """Export merged data to LAS using UTF-8 and an atomic target."""
        try:
            if not isinstance(merged_df, pd.DataFrame):
                raise ValueError("merged_df must be a pandas DataFrame")
            las_content = export_merged_las(merged_df, well_info)
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

    def export_csv_wells(self, wells, file_path: str) -> bool:
        """One CSV with every well's results stacked and a ``WELL`` column first."""
        try:
            frame = combined_results(wells)
            with _atomic_target(file_path) as temporary_path:
                frame.to_csv(temporary_path, index=False)
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

    def export_excel_wells(self, wells, file_path: str) -> bool:
        """Workbook: Summary sheet, Zones sheet (when present), one sheet per well."""
        try:
            _export_wells_excel(wells, file_path)
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

    def export_las_wells(self, wells, directory: str) -> bool:
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
                las_content = export_merged_las(las_frame(ds), ds.well_info)
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

    def get_csv_string(self, results: pd.DataFrame) -> str:
        """Get CSV data as string."""
        _validate_results(results)
        buffer = io.StringIO()
        results.to_csv(buffer, index=False)
        return buffer.getvalue()

    def get_excel_bytes(self, results: pd.DataFrame, summary: dict) -> bytes:
        """Get Excel data as bytes using the same summary schema as file export."""
        _validate_results(results)
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            results.to_excel(writer, sheet_name="Results", index=False)
            _summary_frame(summary).to_excel(writer, sheet_name="Summary", index=False)
        return buffer.getvalue()
