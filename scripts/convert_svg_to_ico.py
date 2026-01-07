#!/usr/bin/env python3
"""
Convert icon to ICO format for Windows installer.

This script converts the application icon to ICO format with multiple sizes
required for Windows applications (16, 24, 32, 48, 64, 128, 256 pixels).

The script supports two input sources:
1. PNG file (preferred - no extra dependencies)
2. SVG file (requires cairosvg which needs Cairo library)

Requirements:
    pip install Pillow

Usage:
    python scripts/convert_svg_to_ico.py
"""

import sys
from pathlib import Path


def convert_png_to_ico(png_path: Path, ico_path: Path, sizes=None):
    """
    Convert PNG file to ICO with multiple sizes.

    Args:
        png_path: Path to input PNG file
        ico_path: Path to output ICO file
        sizes: List of icon sizes (default: [16, 24, 32, 48, 64, 128, 256])
    """
    from PIL import Image

    if sizes is None:
        sizes = [16, 24, 32, 48, 64, 128, 256]

    print(f"Converting: {png_path}")
    print(f"Output: {ico_path}")
    print(f"Sizes: {sizes}")

    # Load the source PNG
    source_img = Image.open(png_path)
    print(f"  Source size: {source_img.width}x{source_img.height}")

    # Ensure RGBA mode for transparency
    if source_img.mode != "RGBA":
        source_img = source_img.convert("RGBA")

    images = []
    for size in sizes:
        print(f"  Generating {size}x{size}...", end=" ")

        # Resize with high-quality resampling
        img = source_img.copy()
        img.thumbnail((size, size), Image.Resampling.LANCZOS)

        # Create exact size canvas (in case aspect ratio differs)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        # Center the image
        offset = ((size - img.width) // 2, (size - img.height) // 2)
        canvas.paste(img, offset)

        images.append(canvas)
        print("OK")

    # Save as ICO with all sizes embedded
    # Pillow requires the largest image first for proper ICO creation
    print(f"  Saving ICO with {len(images)} sizes...", end=" ")

    # Reverse so largest is first (256, 128, 64, 48, 32, 24, 16)
    images_reversed = list(reversed(images))

    # Save with proper ICO format
    images_reversed[0].save(
        ico_path,
        format="ICO",
        append_images=images_reversed[1:],
        sizes=[(img.width, img.height) for img in images_reversed],
    )
    print("OK")

    # Verify output
    file_size = ico_path.stat().st_size / 1024
    print(f"\nSuccess! Created {ico_path.name} ({file_size:.1f} KB)")


def convert_svg_to_ico(svg_path: Path, ico_path: Path, sizes=None):
    """
    Convert SVG file to ICO with multiple sizes.
    Requires cairosvg (which needs Cairo library installed).

    Args:
        svg_path: Path to input SVG file
        ico_path: Path to output ICO file
        sizes: List of icon sizes (default: [16, 24, 32, 48, 64, 128, 256])
    """
    import cairosvg
    from PIL import Image
    import io

    if sizes is None:
        sizes = [16, 24, 32, 48, 64, 128, 256]

    print(f"Converting: {svg_path}")
    print(f"Output: {ico_path}")
    print(f"Sizes: {sizes}")

    images = []
    for size in sizes:
        print(f"  Generating {size}x{size}...", end=" ")

        # Convert SVG to PNG at target size
        png_data = cairosvg.svg2png(
            url=str(svg_path), output_width=size, output_height=size
        )

        # Load PNG into PIL Image
        img = Image.open(io.BytesIO(png_data))

        # Ensure RGBA mode for transparency
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        images.append(img)
        print("OK")

    # Save as ICO
    print(f"  Saving ICO with {len(images)} sizes...", end=" ")
    images[0].save(
        ico_path,
        format="ICO",
        sizes=[(img.width, img.height) for img in images],
        append_images=images[1:],
    )
    print("OK")

    # Verify output
    file_size = ico_path.stat().st_size / 1024
    print(f"\nSuccess! Created {ico_path.name} ({file_size:.1f} KB)")


def main():
    """Main entry point."""
    # Check Pillow is available (required for both methods)
    try:
        from PIL import Image

        print(f"Pillow version: {Image.__version__}")
    except ImportError:
        print("Error: Pillow is required. Install with: pip install Pillow")
        sys.exit(1)

    # Determine paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent  # petrophyter_pyqt/
    repo_root = project_root.parent  # petrophyter/

    ico_path = project_root / "icons" / "app_icon.ico"

    # Try PNG first (easier, no Cairo dependency)
    png_path = repo_root / "petropyhter icon.png"
    svg_path = project_root / "icons" / "app_icon.svg"

    if png_path.exists():
        print("Found PNG source (recommended for Windows)")
        print("")
        convert_png_to_ico(png_path, ico_path)
    elif svg_path.exists():
        print("PNG not found, trying SVG source...")
        print("Note: SVG conversion requires Cairo library installed")
        print("")

        # Check if cairosvg works
        try:
            import cairosvg

            convert_svg_to_ico(svg_path, ico_path)
        except ImportError:
            print("Error: cairosvg not installed. Install with: pip install cairosvg")
            sys.exit(1)
        except OSError as e:
            print(f"Error: Cairo library not found: {e}")
            print("")
            print("Solutions:")
            print("  1. Place a PNG file at: petropyhter icon.png (in repo root)")
            print("  2. Or install Cairo library:")
            print("     - Windows: conda install -c conda-forge cairo")
            print("     - Or use GTK installer from https://gtk.org")
            sys.exit(1)
    else:
        print(f"Error: No source icon found.")
        print(f"  Checked PNG: {png_path}")
        print(f"  Checked SVG: {svg_path}")
        sys.exit(1)

    print("")
    print("Next steps:")
    print("  1. The ICO file is ready for use in PyInstaller and Inno Setup")
    print("  2. Run: .\\scripts\\build-installer.ps1")


if __name__ == "__main__":
    main()
