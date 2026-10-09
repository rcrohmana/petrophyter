"""Docs must describe the current UI (menus, window, Data Browser), not the removed sidebar."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "user-guide.md"
README = ROOT / "README.md"
MAIN_WINDOW = ROOT / "ui" / "main_window.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _guide_shortcuts() -> list[str]:
    """First-column values of the guide's `## Keyboard shortcuts` table."""
    text = _read(GUIDE)
    section = re.search(r"^## Keyboard shortcuts\s*$(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert section, "user-guide.md has no 'Keyboard shortcuts' section"
    shortcuts = []
    for line in section.group(1).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.strip().startswith("|") or not cells:
            continue
        first = cells[0].strip("`").strip()
        if first.lower() == "shortcut" or set(first) <= {"-", ":", " "}:
            continue
        shortcuts.append(first)
    return shortcuts


def test_docs_do_not_mention_removed_sidebar():
    for path in (GUIDE, README):
        assert "sidebar" not in _read(path).lower(), f"{path.name} still mentions the sidebar"


def test_guide_shortcut_table_is_not_empty():
    assert len(_guide_shortcuts()) >= 5


def test_every_documented_shortcut_exists_in_main_window():
    source = _read(MAIN_WINDOW)
    missing = [s for s in _guide_shortcuts() if f'"{s}"' not in source]
    assert not missing, f"shortcuts documented but not defined in ui/main_window.py: {missing}"
