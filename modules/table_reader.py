"""
Tolerant reader for tops and core tables (pure, no Qt).

``read_table`` turns a delimited text file (tab, comma, semicolon or pipe), a
text buffer or an ``.xlsx`` sheet into a DataFrame of *strings* (cells are not
type-converted; callers convert the numeric columns they use). It copes with
the things real exports do:

* encoding: ``utf-8-sig`` (strips a BOM), then ``cp1252``;
* delimiter: every candidate is tried and validated by whether the caller's
  required columns are found; ties go to the delimiter whose rows are most
  consistent, then to tab, comma, semicolon, pipe;
* leading ``#`` comment lines, blank lines and a preamble above the header
  (up to ten candidate header rows);
* a unit row under the header (``m`` / ``ft`` / ...), dropped and reported;
* decimal comma (``1000,5``) for any delimiter other than a comma.

Every returned row keeps its physical line number (Excel row number for
workbooks) in ``TableRead.line_numbers`` so callers can report excluded rows.
"""

import csv
import io
import os
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

CANDIDATE_DELIMITERS = ["\t", ",", ";", "|"]
MAX_HEADER_ROWS = 10

_FEET_TOKENS = {"ft", "feet", "foot"}
_METER_TOKENS = {"m", "meter", "meters", "metre", "metres", "mt"}
# Other unit words that make a row of text a "unit row" without implying a depth unit.
_OTHER_UNIT_TOKENS = {
    "%", "pct", "percent", "fraction", "frac", "v/v", "md", "mdarcy", "millidarcy",
    "g/cc", "g/cm3", "g/cm³", "gm/cc", "kg/m3", "pu", "ohm.m", "ohmm", "gapi",
}
_COMMA_NUMBER = re.compile(r"^[+-]?\d+,\d+$")
# "1,250" could be a thousands separator or a decimal comma with three decimals.
_THOUSANDS_NUMBER = re.compile(r"^[+-]?[1-9]\d{0,2}(,\d{3})+$")
_PLAIN_NUMBER = re.compile(r"^[+-]?\d+(,\d+)?$")


class TableReadError(ValueError):
    """The file could not be read as a table with the required columns.

    ``attempts`` lists ``(description, columns found)`` for each attempt so the
    message can show what each delimiter produced.
    """

    def __init__(self, message: str, attempts: Optional[list] = None):
        super().__init__(message)
        self.attempts = attempts or []


@dataclass
class TableRead:
    """Result of :func:`read_table`."""
    frame: pd.DataFrame
    delimiter: Optional[str] = None      # None for Excel
    decimal: str = "."
    encoding: str = ""
    sheet: Optional[str] = None
    skipped_lines: int = 0               # physical lines above the header line
    unit_row_unit: Optional[str] = None  # 'M' / 'FT' implied by a dropped unit row
    notes: List[str] = field(default_factory=list)
    line_numbers: List[int] = field(default_factory=list)  # one per frame row
    header_line: int = 1
    unit_row_dropped: bool = False
    sheets: List[str] = field(default_factory=list)


Required = Union[None, Callable[[pd.DataFrame], bool], Sequence[Sequence[str]]]


def _tokens(text) -> set:
    return {t for t in re.split(r"[^a-z0-9]+", str(text).lower()) if t}


def _columns_ok(required: Required, columns: Sequence[str]) -> bool:
    if required is None:
        return True
    if callable(required):
        return bool(required(pd.DataFrame(columns=list(columns))))
    col_tokens = [_tokens(c) for c in columns]
    for group in required:
        found = False
        for alias in group:
            at = _tokens(alias)
            if at and any(at <= ct for ct in col_tokens):
                found = True
                break
        if not found:
            return False
    return True


def list_sheets(source) -> List[str]:
    """Sheet names of an Excel workbook path (empty for anything else)."""
    if isinstance(source, (str, os.PathLike)) and str(source).lower().endswith((".xlsx", ".xlsm")):
        with pd.ExcelFile(source) as xl:
            return list(xl.sheet_names)
    return []


def _is_number(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (int, float, np.integer, np.floating)):
        return not (isinstance(value, float) and np.isnan(value))
    try:
        float(str(value).strip().replace(",", "."))
        return True
    except ValueError:
        return False


def _blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and np.isnan(value):
        return True
    return isinstance(value, str) and not value.strip()


def _decode(raw: bytes):
    try:
        return raw.decode("utf-8-sig"), "utf-8-sig"
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace"), "cp1252"


def _unique_headers(fields: Sequence) -> List[str]:
    out: List[str] = []
    seen: dict = {}
    for i, f in enumerate(fields):
        name = "" if f is None else str(f).strip()
        if not name:
            name = f"Unnamed: {i}"
        if name in seen:
            seen[name] += 1
            name = f"{name}.{seen[name]}"
        else:
            seen[name] = 0
        out.append(name)
    return out


def _split_line(line: str, delimiter: str) -> List[str]:
    try:
        return next(csv.reader([line], delimiter=delimiter))
    except (StopIteration, csv.Error):
        return line.split(delimiter)


def _clean_cell(value):
    if isinstance(value, str):
        value = value.strip()
        return np.nan if value == "" else value
    if value is None:
        return np.nan
    return value


def _unit_of(cell) -> Optional[str]:
    """'FT' / 'M' / 'other' / None for a unit-row cell."""
    if _blank(cell) or not isinstance(cell, str):
        return None
    token = cell.strip().strip("()[]").strip().lower()
    if token in _FEET_TOKENS:
        return "FT"
    if token in _METER_TOKENS:
        return "M"
    if token in _OTHER_UNIT_TOKENS:
        return "other"
    return None


def _detect_unit_row(rows: List[list]) -> Optional[Optional[str]]:
    """Return the unit implied by a unit row (or ``'other'``), ``None`` if there is none."""
    if len(rows) < 2:
        return None
    first, second = rows[0], rows[1]
    cells = [c for c in first if not _blank(c)]
    if not cells or any(_is_number(c) for c in cells):
        return None
    if not any(_is_number(c) for c in second):
        return None
    units = [_unit_of(c) for c in first]
    if not any(units):
        return None
    for u in units:
        if u in ("FT", "M"):
            return u
    return "other"


def _comma_columns(frame: pd.DataFrame) -> List[str]:
    """Columns of plain numbers (no dots) where at least one cell has a comma."""
    out = []
    for col in frame.columns:
        values = [v for v in frame[col] if not _blank(v)]
        strs = [v for v in values if isinstance(v, str)]
        if not strs or len(strs) != len(values):
            continue
        if any("." in v for v in strs):
            continue
        if not all(_PLAIN_NUMBER.match(v) or _THOUSANDS_NUMBER.match(v) for v in strs):
            continue
        if any("," in v for v in strs):
            out.append(col)
    return out


def _apply_decimal_comma(frame: pd.DataFrame) -> Optional[str]:
    """Normalise comma numbers in place; returns "decimal", "thousands" or None.

    The decision is per file: one cell that can only be a decimal comma
    ("0,215", "1234,5") makes every comma a decimal mark. When every comma
    cell also reads as a thousands group ("1,250", "12,000"), commas are taken
    as thousands separators, so a depth is never shrunk a thousandfold.
    """
    cols = _comma_columns(frame)
    if not cols:
        return None
    cells = [v for col in cols for v in frame[col] if isinstance(v, str) and "," in v]
    if all(_THOUSANDS_NUMBER.match(v) for v in cells):
        for col in cols:
            frame[col] = [v.replace(",", "") if isinstance(v, str) else v for v in frame[col]]
        return "thousands"
    for col in cols:
        frame[col] = [v.replace(",", ".") if isinstance(v, str) and _COMMA_NUMBER.match(v) else v
                      for v in frame[col]]
    return "decimal"


def _build(rows_with_lines, header_idx: int, fields_of: Callable[[object], list]):
    header = _unique_headers(fields_of(rows_with_lines[header_idx][1]))
    data, lines = [], []
    n = len(header)
    for lineno, raw in rows_with_lines[header_idx + 1:]:
        cells = [_clean_cell(c) for c in fields_of(raw)]
        if len(cells) < n:
            cells += [np.nan] * (n - len(cells))
        elif len(cells) > n:
            cells = cells[:n]
        if all(_blank(c) for c in cells):
            continue
        data.append(cells)
        lines.append(lineno)
    return header, data, lines


def read_table(source, required: Required = None, *, sheet=0,
               delimiter: Optional[str] = None) -> TableRead:
    """Read ``source`` (path, text/bytes buffer or ``.xlsx``) into a string table.

    Args:
        source: a path, or an object with ``read()`` (text or bytes buffer).
        required: ``None``, a predicate ``f(frame) -> bool`` called with a
            frame holding only the candidate header columns, or a list of
            alias groups (each group needs one token-matching column).
        sheet: sheet index or name for ``.xlsx`` workbooks.
        delimiter: preferred delimiter; still validated, others are tried if it fails.

    Raises:
        TableReadError: no delimiter/header yields the required columns (the
        message lists the columns each attempt found).
    """
    is_path = isinstance(source, (str, os.PathLike))
    path_str = os.fspath(source) if is_path else ""
    raw = None
    if is_path:
        if path_str.lower().endswith((".xlsx", ".xlsm")):
            return _read_excel(path_str, required, sheet)
        with open(path_str, "rb") as fh:
            raw = fh.read()
    else:
        raw = source.read()
        if hasattr(source, "seek"):
            try:
                source.seek(0)
            except Exception:  # pragma: no cover - non-seekable buffers
                pass
    if isinstance(raw, (bytes, bytearray)):
        if bytes(raw[:2]) == b"PK":
            return _read_excel(io.BytesIO(bytes(raw)), required, sheet)
        text, encoding = _decode(bytes(raw))
    else:
        text, encoding = str(raw), "text"
        if text.startswith("﻿"):
            text = text[1:]

    lines = re.split(r"\r\n|\n|\r", text)
    content = [(i + 1, ln) for i, ln in enumerate(lines)
               if ln.strip(" \t\r\n,;|") != "" and not ln.lstrip().startswith("#")]
    if not content:
        raise TableReadError("The file is empty.")

    candidates = list(CANDIDATE_DELIMITERS)
    if delimiter and delimiter in candidates:
        candidates.remove(delimiter)
        candidates.insert(0, delimiter)
    elif delimiter:
        candidates.insert(0, delimiter)

    attempts: list = []
    best = None  # (consistency, -priority, header_idx, delimiter)
    for h in range(min(MAX_HEADER_ROWS, len(content))):
        found = []
        for prio, d in enumerate(candidates):
            fields = _unique_headers(_split_line(content[h][1], d))
            if h == 0:
                attempts.append((f"delimiter {_delim_name(d)}", fields))
            if not _columns_ok(required, fields):
                continue
            n = len(fields)
            sample = content[h + 1:h + 51]
            if sample:
                same = sum(1 for _, ln in sample if len(_split_line(ln, d)) == n)
                consistency = same / len(sample)
            else:
                consistency = 1.0
            # A split that actually separates columns beats one that leaves a
            # single mega-column (its tokens could still match the aliases).
            found.append((n > 1, consistency, -prio, h, d))
        if found:
            best = max(found)
            break
    if best is None:
        detail = "; ".join(f"{name}: {cols}" for name, cols in attempts)
        raise TableReadError(
            "Could not find the required columns. Columns found per delimiter "
            f"(first row): {detail}", attempts)

    h, d = best[-2:]
    header, data, lines_no = _build(content, h, lambda ln: _split_line(ln, d))
    frame = pd.DataFrame(data, columns=header, dtype=object)
    result = TableRead(frame=frame, delimiter=d, encoding=encoding,
                       skipped_lines=content[h][0] - 1, header_line=content[h][0],
                       line_numbers=lines_no)
    _finish(result, data, d != ",")
    return result


def _delim_name(d: str) -> str:
    return {"\t": "tab", ",": "comma", ";": "semicolon", "|": "pipe"}.get(d, repr(d))


def _finish(result: TableRead, data: List[list], allow_decimal_comma: bool) -> None:
    """Unit row and decimal-comma handling, in place."""
    frame = result.frame
    unit = _detect_unit_row(data)
    if unit is not None:
        result.unit_row_dropped = True
        result.unit_row_unit = unit if unit in ("FT", "M") else None
        result.frame = frame = frame.iloc[1:].reset_index(drop=True)
        result.line_numbers = result.line_numbers[1:]
        what = f"depth unit {unit}" if result.unit_row_unit else "units"
        result.notes.append(f"Dropped a unit row under the header ({what}).")
    comma = _apply_decimal_comma(frame) if allow_decimal_comma else None
    if comma == "decimal":
        result.decimal = ","
        result.notes.append("Decimal comma detected; converted to decimal point.")
    elif comma == "thousands":
        result.notes.append(
            "Commas read as thousands separators (e.g. 1,250 = 1250); "
            "no value in the file can only be a decimal comma.")
    if result.skipped_lines:
        result.notes.append(f"Skipped {result.skipped_lines} line(s) above the header.")


def _read_excel(src, required: Required, sheet) -> TableRead:
    with pd.ExcelFile(src) as xl:
        names = list(xl.sheet_names)
        if isinstance(sheet, int):
            if not -len(names) <= sheet < len(names):
                raise TableReadError(f"Sheet {sheet} not found; available: {names}")
            sheet_name = names[sheet]
        else:
            sheet_name = sheet
        if sheet_name not in names:
            raise TableReadError(f"Sheet '{sheet}' not found; available: {names}")
        raw = xl.parse(sheet_name=sheet_name, header=None, dtype=object)
    rows = []
    for i, values in enumerate(raw.itertuples(index=False, name=None)):
        cells = [_clean_cell(v) for v in values]
        if all(_blank(c) for c in cells):
            continue
        if isinstance(cells[0], str) and cells[0].lstrip().startswith("#"):
            continue
        rows.append((i + 1, cells))
    if not rows:
        raise TableReadError("The sheet is empty.")
    found_cols = None
    for h in range(min(MAX_HEADER_ROWS, len(rows))):
        header = _unique_headers(rows[h][1])
        if h == 0:
            found_cols = header
        if _columns_ok(required, header):
            hdr, data, lines_no = _build(rows, h, lambda cells: list(cells))
            frame = pd.DataFrame(data, columns=hdr, dtype=object)
            result = TableRead(frame=frame, delimiter=None, encoding="xlsx", sheet=sheet_name,
                               skipped_lines=rows[h][0] - 1, header_line=rows[h][0],
                               line_numbers=lines_no, sheets=names)
            _finish(result, data, False)
            return result
    raise TableReadError(
        f"Could not find the required columns. Columns found in sheet '{sheet_name}' "
        f"(first row): {found_cols}", [(f"sheet {sheet_name}", found_cols)])
