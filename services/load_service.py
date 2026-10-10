"""
Load Service for Petrophyter PyQt
Parses LAS files off the GUI thread, groups them by well identity and builds
one :class:`WellDataset` per group.
"""

import copy
import logging
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from models.project import WellDataset, display_name_for, make_well_key
from modules.las_parser import LASParser
from modules.las_utils import same_well, well_key
from modules.param_scopes import default_well_overrides
from modules.qc_module import QCModule

logger = logging.getLogger(__name__)

CURVE_TYPES = ("GR", "RHOB", "NPHI", "DT", "RT")


def sanitize_error_detail(detail, max_length: int = 240) -> str:
    """Keep actionable first-line errors while removing secrets and paths."""
    if detail is None:
        return ""
    first_line = next(
        (line.strip() for line in str(detail).splitlines() if line.strip()), ""
    )
    first_line = re.sub(
        r"(?i)\b(password|token|secret|api[_ -]?key)\b\s*[:=]\s*\S+",
        r"\1=[redacted]",
        first_line,
    )
    first_line = re.sub(r"(?i)(?:[A-Za-z]:[\\/]|/)[^\s)]+", "<path>", first_line)
    return first_line[:max_length]


@dataclass
class ParsedFile:
    """One LAS file after parsing: the parser, or the reason it failed."""

    path: str
    name: str
    parser: Optional[object] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.parser is not None and self.error is None

    @property
    def well_info(self) -> Dict:
        return dict(getattr(self.parser, "well_info", None) or {})


def parse_file(path: str) -> ParsedFile:
    """Parse one LAS file; never raises (a failure becomes ``error``)."""
    name = os.path.basename(str(path))
    parser = LASParser()
    try:
        with open(path, "r") as handle:
            success = parser.read_las_from_buffer(handle)
    except Exception as exc:
        logger.exception("Unexpected failure parsing LAS file %s", path)
        return ParsedFile(path, name, None, sanitize_error_detail(exc) or "Could not read file")
    if success and parser.data is not None:
        return ParsedFile(path, name, parser, None)
    detail = getattr(parser, "last_error", None)
    logger.error("Failed to load LAS file %s: %s", path, detail)
    return ParsedFile(path, name, None, sanitize_error_detail(detail) or "Could not parse file")


class LoadSignals(QObject):
    progress = pyqtSignal(str, int)
    completed = pyqtSignal(list)  # list[ParsedFile], in input order
    error = pyqtSignal(str)


class LoadWorker(QRunnable):
    """Parse several LAS files on a pool thread."""

    def __init__(self, paths: List[str]):
        super().__init__()
        self.paths = list(paths)
        self.signals = LoadSignals()

    def run(self):
        try:
            total = max(len(self.paths), 1)
            parsed = []
            for index, path in enumerate(self.paths):
                self.signals.progress.emit(
                    f"Reading {os.path.basename(str(path))}...", int(90 * index / total)
                )
                parsed.append(parse_file(path))
            self.signals.progress.emit("Files read", 100)
            self.signals.completed.emit(parsed)
        except Exception as exc:
            logger.exception("Reading LAS files failed")
            self.signals.error.emit(f"Failed to read LAS files: {sanitize_error_detail(exc)}")


def group_files(parsed: List[ParsedFile]) -> List[List[ParsedFile]]:
    """Propose well groups for parsed files (pure; input order is kept).

    A file joins an existing group only when its identity is definitively the
    same as the group's first identified member (``same_well`` is True).
    Unidentified files each get a group of their own. Files that failed to
    parse are left out.
    """
    groups: List[List[ParsedFile]] = []
    for item in parsed:
        if not item.ok:
            continue
        info = item.well_info
        if not well_key(info)[1]:
            groups.append([item])
            continue
        for group in groups:
            anchor = next((g for g in group if well_key(g.well_info)[1]), None)
            if anchor is not None and same_well(anchor.well_info, info) is True:
                group.append(item)
                break
        else:
            groups.append([item])
    return groups


def _detect_mapping(parser) -> Dict[str, str]:
    detected = {}
    for ctype in CURVE_TYPES:
        found = parser.find_curve_by_type(ctype)
        detected[ctype] = found if found else "None"
    return detected


def build_well(files: List[ParsedFile], merge_result=None) -> WellDataset:
    """Build a WellDataset from one file, or from a merged group.

    ``merge_result`` is the dict from ``LASHandler.merge_las_files`` (or a
    ``(merged_df, merge_report)`` pair); it is required for 2+ files.
    """
    if not files:
        raise ValueError("No files to build a well from")
    sources = [
        {
            "name": f.name,
            "path": f.path,
            "rows": 0 if getattr(f.parser, "data", None) is None else len(f.parser.data),
        }
        for f in files
    ]
    merge_report = None
    if len(files) == 1 and merge_result is None:
        parser = files[0].parser
        data = parser.data
        las_filename = files[0].path
        merged = False
    else:
        if isinstance(merge_result, dict):
            data, merge_report = merge_result["merged_df"], merge_result["merge_report"]
        else:
            data, merge_report = merge_result
        # A shallow copy keeps the first source parser's own data intact.
        parser = copy.copy(files[0].parser)
        parser.data = data
        well_info = getattr(merge_report, "well_info", None)
        if well_info:
            parser.well_info = dict(well_info)
        curve_info = getattr(merge_report, "curve_info", None)
        if curve_info:
            parser.curve_info = dict(curve_info)
        las_filename = f"MERGED_{len(files)}_files"
        merged = True

    well_info = dict(getattr(parser, "well_info", None) or {})
    fallback = files[0].path
    ds = WellDataset(
        key=make_well_key(well_info, fallback),
        display_name=display_name_for(well_info, fallback),
    )
    ds.identity = well_info
    ds.sources = sources
    ds.merged = merged
    ds.las_parser = parser
    ds.las_data = data
    ds.las_filename = las_filename
    ds.merge_report = merge_report
    ds.curve_mapping = _detect_mapping(parser)
    ds.qc_report = QCModule(data, ds.display_name).run_qc()
    # New wells estimate Rw, Rsh and the GR baseline from their own data
    # (spec §4.3), so no value calibrated on another well leaks in.
    ds.overrides = default_well_overrides(ds.well_info)
    return ds
