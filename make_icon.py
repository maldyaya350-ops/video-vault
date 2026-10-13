"""Generate assets/icon.ico (rounded blue tile with a play triangle and a lock notch).

Replace assets/icon.ico with your own .ico before building if you want a custom icon.
"""
from pathlib import Path

from PIL import Image, ImageDraw

SIZES = [16, 24, 32, 48, 64, 128, 256]


def draw(size: int) -> Image.Image:
    s = size * 4  # supersample for smooth edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([s * 0.04, s * 0.04, s * 0.96, s * 0.96], radius=s * 0.22, fill=(61, 90, 254, 255))
    d.polygon([(s * 0.38, s * 0.28), (s * 0.38, s * 0.72), (s * 0.74, s * 0.5)], fill=(255, 255, 255, 255))
    # small padlock badge, bottom-right
    cx, cy, r = s * 0.74, s * 0.74, s * 0.15
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(20, 22, 28, 255))
    d.rectangle([cx - r * 0.45, cy - r * 0.1, cx + r * 0.45, cy + r * 0.5], fill=(255, 255, 255, 255))
    d.arc([cx - r * 0.35, cy - r * 0.65, cx + r * 0.35, cy + r * 0.15], 180, 360, fill=(255, 255, 255, 255),
          width=max(1, int(s * 0.025)))
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "assets"
    out.mkdir(exist_ok=True)
    big = draw(256)
    big.save(out / "icon.ico", sizes=[(n, n) for n in SIZES])
    print("wrote", out / "icon.ico")
