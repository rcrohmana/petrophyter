# scripts/fetch_lucide_icons.py
"""Download the Lucide icon subset used by Petrophyter (see docs/design.md)."""
import re
import urllib.request
from pathlib import Path

ICONS = [
    "folder-open", "layers", "database", "file-plus", "play", "save",
    "folder-input", "merge", "download", "sun", "moon", "panel-left",
    "book-open", "info", "circle-check", "triangle-alert", "circle-x",
    "chevron-down", "chevron-up", "chevron-right", "x", "calculator",
    "check", "refresh-cw", "house", "arrow-left", "arrow-right", "move",
    "zoom-in", "settings-2", "sliders-horizontal", "copy",
    "file-text", "activity", "sigma",  # Data Browser nodes (Rev 2)
    "crosshair", "spline", "cylinder", "percent", "mountain", "scissors",  # F9 menu icons
    "hexagon", "droplets", "waves-horizontal", "flame", "log-out", "palette",
]
BASE = "https://raw.githubusercontent.com/lucide-icons/lucide/main/icons/{}.svg"
OUT = Path(__file__).resolve().parents[1] / "icons" / "lucide"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ICONS:
        svg = urllib.request.urlopen(BASE.format(name), timeout=30).read().decode()
        svg = re.sub(r'stroke-width="[^"]*"', 'stroke-width="1.75"', svg)
        assert 'stroke="currentColor"' in svg, name
        (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
        print("ok", name)


if __name__ == "__main__":
    main()
