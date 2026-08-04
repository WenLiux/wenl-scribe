"""Generate the Windows application icon from the WENL brand mark."""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "public" / "wenl.ico"

# The outline in public/wenl_logo2.svg is made entirely from straight segments.
# Keeping the points here makes icon generation deterministic without adding an
# SVG rasterizer to the desktop runtime.
MARK_POINTS = (
    (17.01, 14.15),
    (75.71, 45.23),
    (75.71, 14.15),
    (134.41, 45.23),
    (134.41, 14.15),
    (220.73, 59.04),
    (220.73, 150.54),
    (192.24, 150.54),
    (162.03, 134.14),
    (162.03, 151.40),
    (75.71, 151.40),
    (17.01, 119.46),
    (17.01, 14.15),
)


def render(size: int) -> Image.Image:
    scale_factor = 4
    canvas_size = size * scale_factor
    image = Image.new("RGBA", (canvas_size, canvas_size), (32, 35, 31, 255))
    draw = ImageDraw.Draw(image)
    radius = max(2, round(canvas_size * 0.20))
    draw.rounded_rectangle(
        (0, 0, canvas_size - 1, canvas_size - 1),
        radius=radius,
        fill=(32, 35, 31, 255),
    )

    mark_width = canvas_size * 0.82
    scale = mark_width / 236
    mark_height = 159 * scale
    left = (canvas_size - mark_width) / 2
    top = (canvas_size - mark_height) / 2
    points = [(round(left + x * scale), round(top + y * scale)) for x, y in MARK_POINTS]
    draw.line(
        points,
        fill=(244, 243, 238, 255),
        width=max(1, round(10 * scale)),
        joint="curve",
    )
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    render(256).save(
        OUTPUT,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Windows icon ready: {OUTPUT}")


if __name__ == "__main__":
    main()
