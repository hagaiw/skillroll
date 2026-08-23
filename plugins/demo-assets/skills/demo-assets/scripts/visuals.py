"""Shared visual system for SkillRoll's generated README media."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[5]
ASSETS = ROOT / "docs" / "assets"
WIDTH, HEIGHT = 1200, 760
BG = "#0b1020"
PANEL = "#11182b"
PANEL_2 = "#182238"
INK = "#f5f2e8"
MUTED = "#91a0b8"
BLUE = "#7aa2f7"
GREEN = "#75c88a"
RED = "#f17878"
AMBER = "#e7b766"


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = (
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/SFNSMono-Bold.ttf" if bold else "",
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(
                candidate,
                size=size,
                index=1 if bold and candidate.endswith(".ttc") else 0,
            )
    return ImageFont.load_default(size=size)


BODY = font(25)
SMALL = font(20)
TITLE = font(28, bold=True)
HERO = font(57, bold=True)
SUBHEAD = font(26)


def rounded(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    fill: str,
    radius: int = 18,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def chrome(draw: ImageDraw.ImageDraw, stage: int) -> None:
    draw.text((70, 54), "SKILLROLL", font=TITLE, fill=INK)
    draw.text((70, 96), "FROM SKILL TO REGRESSION CHECK", font=SMALL, fill=MUTED)
    for index, label in enumerate(("CREATE", "EDIT", "RUN"), start=1):
        x = 776 + (index - 1) * 122
        fill = GREEN if index < stage else BLUE if index == stage else PANEL_2
        text_color = BG if index <= stage else MUTED
        rounded(draw, (x, 57, x + 102, 91), fill, 17)
        draw.text((x + 51, 64), label, font=SMALL, fill=text_color, anchor="ma")
    rounded(draw, (64, 142, 1136, 700), PANEL)
    draw.ellipse((92, 169, 106, 183), fill=RED)
    draw.ellipse((116, 169, 130, 183), fill=AMBER)
    draw.ellipse((140, 169, 154, 183), fill=GREEN)


def terminal(
    lines: list[tuple[str, str]], *, stage: int, cursor: bool = False
) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    chrome(draw, stage)
    y = 220
    for index, (value, color) in enumerate(lines[-10:]):
        draw.text((96, y), value, font=BODY, fill=color)
        if cursor and index == len(lines[-10:]) - 1:
            cursor_x = 96 + int(draw.textlength(value, font=BODY)) + 3
            draw.rectangle((cursor_x, y + 5, cursor_x + 13, y + 31), fill=BLUE)
        y += 43
    return image


def editor(
    lines: list[str], *, cursor: bool = False, status: str | None = None
) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    chrome(draw, 2)
    draw.rectangle((78, 202, 1122, 244), fill="#d8deeb")
    draw.text(
        (600, 210),
        "GNU nano 8.0    ship-pr/evals/wait-for-ci.eval.md",
        font=SMALL,
        fill=BG,
        anchor="ma",
    )
    visible = lines[-9:]
    y = 264
    for index, value in enumerate(visible):
        color = BLUE if value.startswith(("# ", "## ")) else INK
        draw.text((96, y), value, font=SMALL, fill=color)
        if cursor and index == len(visible) - 1:
            cursor_x = 96 + int(draw.textlength(value, font=SMALL)) + 3
            draw.rectangle((cursor_x, y + 4, cursor_x + 11, y + 26), fill=BLUE)
        y += 40
    if status is not None:
        draw.text((600, 603), status, font=SMALL, fill=GREEN, anchor="ma")
    draw.rectangle((78, 632, 1122, 680), fill="#d8deeb")
    draw.text(
        (96, 645),
        "^G Help   ^O Write Out   ^W Search   ^K Cut   ^X Exit",
        font=SMALL,
        fill=BG,
    )
    return image
