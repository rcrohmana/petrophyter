# tests/test_design_compliance.py
"""Design-system enforcement (docs/design.md §5 Prohibitions).

These tests scan source text. If one fails, fix the source — never widen
a whitelist without a design.md amendment.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_FILES = sorted((ROOT / "ui").rglob("*.py"))
SCAN_FILES = UI_FILES + [ROOT / "main.py"] + sorted((ROOT / "services").rglob("*.py"))

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u25A0-\u25FF\uFE0F"
    "\u2705\u274C\u2753\u2757]"
)
HEX_RE = re.compile(r"""["'][^"']*#[0-9A-Fa-f]{3,8}\b""")
NAMED_COLOR_RE = re.compile(r"color:\s*(green|orange|red|white|black|gray|grey|blue|yellow)\b")
FONT_SIZE_RE = re.compile(r"font-size")

SETSTYLESHEET_WHITELIST: set[str] = set()  # relative paths; keep empty


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _offending(files, pattern):
    hits = []
    for path in files:
        for i, line in enumerate(_read(path).splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if pattern.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{i}: {stripped[:80]}")
    return hits


def test_no_emoji():
    assert _offending(SCAN_FILES, EMOJI_RE) == []


def test_no_hex_colors_outside_tokens():
    assert _offending(SCAN_FILES, HEX_RE) == []


def test_no_named_css_colors():
    assert _offending(UI_FILES, NAMED_COLOR_RE) == []


def test_no_inline_stylesheets():
    hits = []
    for path in UI_FILES:
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        if rel in SETSTYLESHEET_WHITELIST:
            continue
        if "setStyleSheet(" in _read(path):
            hits.append(rel)
    assert hits == []


def test_no_information_messagebox():
    hits = [str(p.relative_to(ROOT)) for p in SCAN_FILES
            if "QMessageBox.information" in _read(p)]
    assert hits == []


def test_no_inline_font_sizes_in_ui():
    assert _offending(UI_FILES, FONT_SIZE_RE) == []


def test_icon_references_are_bundled():
    icon_dir = ROOT / "icons" / "lucide"
    call_re = re.compile(r"""get_icon\(\s*["']([a-z0-9-]+)["']""")
    missing = set()
    for path in UI_FILES + sorted((ROOT / "themes").rglob("*.py")):
        for name in call_re.findall(_read(path)):
            if not (icon_dir / f"{name}.svg").exists():
                missing.add(name)
    assert missing == set()


BROWSER_INPUT_RE = re.compile(
    r"\b(QComboBox|QSpinBox|QDoubleSpinBox|QLineEdit|QCheckBox|QRadioButton|"
    r"QSlider|QPushButton)\b|parameter_groups"
)


def test_data_browser_is_read_only():
    """Spec §2.4: the left panel shows data only, never a parameter control."""
    assert _offending([ROOT / "ui" / "data_browser.py"], BROWSER_INPUT_RE) == []


BOLD_WEIGHT_RE = re.compile(r"""(font)?weight\s*=\s*["']bold["']""")


def test_no_bold_chart_text():
    """Chart titles/labels use normal weight; sizes come from themes.colors constants."""
    assert _offending(UI_FILES, BOLD_WEIGHT_RE) == []
