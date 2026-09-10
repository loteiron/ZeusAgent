"""Render ZeusAgent's geometric storm/copper mark. Requires Pillow.

The SVG and native icon sizes share these coordinates; no inherited artwork
or font files are used. Run from any directory: python scripts/generate_brand_assets.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
POLYGONS = [
    ("#92B9DD", [(54, 56), (202, 56), (202, 86), (54, 86)]),
    ("#E6AB80", [(170, 86), (202, 86), (86, 170), (54, 170)]),
    ("#92B9DD", [(54, 170), (202, 170), (202, 200), (54, 200)]),
]


def mark(size: int) -> Image.Image:
    scale = 8
    canvas = Image.new("RGBA", (256 * scale, 256 * scale))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((0, 0, 256 * scale - 1, 256 * scale - 1), 44 * scale, fill="#162743")
    draw.rounded_rectangle((12 * scale, 12 * scale, 244 * scale, 244 * scale), 34 * scale,
                           outline="#315B83", width=2 * scale)
    for color, points in POLYGONS:
        draw.polygon([(x * scale, y * scale) for x, y in points], fill=color)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    shapes = "\n".join(
        f'  <polygon points="{" ".join(f"{x},{y}" for x, y in points)}" fill="{color}"/>'
        for color, points in POLYGONS
    )
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img" aria-label="ZeusAgent">\n'
        '  <rect width="256" height="256" rx="44" fill="#162743"/>\n'
        '  <rect x="12" y="12" width="232" height="232" rx="34" fill="none" stroke="#315B83" stroke-width="2"/>\n'
        f'{shapes}\n</svg>\n'
    )
    for folder in ["assets", "apps/desktop/public", "web/public", "apps/bootstrap-installer/public"]:
        (ROOT / folder / "zeus-mark.svg").write_text(svg, encoding="utf-8")

    native = mark(1024)
    desktop = ROOT / "apps/desktop/assets"
    bootstrap = ROOT / "apps/bootstrap-installer/src-tauri/icons"
    native.save(desktop / "icon.png")
    for folder in [desktop, bootstrap]:
        native.save(folder / "icon.ico", sizes=[(s, s) for s in [16, 24, 32, 48, 64, 128, 256]])
        native.save(folder / "icon.icns")
    for filename, size in [("32x32.png", 32), ("128x128.png", 128), ("128x128@2x.png", 256)]:
        mark(size).save(bootstrap / filename)
    mark(180).save(ROOT / "apps/desktop/public/apple-touch-icon.png")
    native.save(ROOT / "web/public/favicon.ico", sizes=[(s, s) for s in [16, 32, 48, 64, 128, 256]])
    print("Generated SVG marks and native desktop, web and installer icons.")


if __name__ == "__main__":
    main()
