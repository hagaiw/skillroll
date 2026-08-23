"""Prepare a high-contrast, reduced-palette source for terminal conversion."""

import argparse
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance


def crop_black_canvas(source: Image.Image, *, padding: int = 28) -> Image.Image:
    rgb = source.convert("RGB")
    difference = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (0, 0, 0)))
    bounds = (
        difference.convert("L").point(lambda value: 255 if value > 10 else 0).getbbox()
    )
    if bounds is None:
        return rgb
    left, top, right, bottom = bounds
    return rgb.crop(
        (
            max(0, left - padding),
            max(0, top - padding),
            min(rgb.width, right + padding),
            min(rgb.height, bottom + padding),
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    source = crop_black_canvas(Image.open(arguments.source))
    prepared = ImageEnhance.Contrast(source).enhance(1.08)
    arguments.destination.parent.mkdir(parents=True, exist_ok=True)
    prepared.save(arguments.destination, optimize=True)


if __name__ == "__main__":
    main()
