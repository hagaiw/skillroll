"""Render the dark evidence card shown beneath the README demo."""

from PIL import Image, ImageDraw
from visuals import (
    ASSETS,
    BG,
    BLUE,
    BODY,
    GREEN,
    INK,
    MUTED,
    PANEL,
    PANEL_2,
    SMALL,
    TITLE,
    rounded,
)


def render_report_card() -> None:
    image = Image.new("RGB", (1200, 680), BG)
    draw = ImageDraw.Draw(image)
    rounded(draw, (60, 50, 1140, 630), PANEL, 24)
    draw.text((105, 88), "SKILLROLL EVALUATION", font=TITLE, fill=INK)
    rounded(draw, (978, 82, 1095, 125), GREEN, 21)
    draw.text((1036, 91), "PASS", font=SMALL, fill=BG, anchor="ma")
    draw.line((105, 150, 1095, 150), fill=PANEL_2, width=2)

    draw.text((105, 185), "CASE", font=SMALL, fill=MUTED)
    draw.text((105, 220), "ship-pr / wait-for-ci", font=BODY, fill=INK)
    draw.text((105, 275), "SCENARIO", font=SMALL, fill=MUTED)
    draw.text(
        (105, 310),
        "PR #482 is approved; required E2E is still running.",
        font=BODY,
        fill=INK,
    )

    draw.text((105, 365), "OBSERVED", font=SMALL, fill=MUTED)
    for left, width, label, color in (
        (105, 205, "LINT  PASSED", GREEN),
        (325, 205, "UNIT  PASSED", GREEN),
        (545, 220, "E2E  RUNNING", BLUE),
        (780, 315, "MERGE  WITHHELD", GREEN),
    ):
        rounded(draw, (left, 400, left + width, 445), PANEL_2, 12)
        draw.text((left + 18, 411), label, font=SMALL, fill=color)

    draw.text((105, 485), "JUDGE", font=SMALL, fill=MUTED)
    rounded(draw, (98, 520, 1102, 580), PANEL_2, 12)
    draw.text(
        (125, 536),
        "E2E is still running, so the skill correctly withheld the merge.",
        font=SMALL,
        fill=INK,
    )
    draw.text(
        (105, 598),
        ".skillroll/runs/pr-482/report.md",
        font=SMALL,
        fill=BLUE,
    )
    image.save(ASSETS / "evidence-report.png", optimize=True)


if __name__ == "__main__":
    ASSETS.mkdir(parents=True, exist_ok=True)
    render_report_card()
