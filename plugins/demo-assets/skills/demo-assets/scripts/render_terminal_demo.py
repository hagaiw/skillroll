"""Render the deterministic terminal-story GIF and poster frame.

Run with:
    uvx --with pillow python render_terminal_demo.py
"""

from __future__ import annotations

from PIL import Image
from visuals import ASSETS, BLUE, GREEN, INK, MUTED, editor, terminal


def render_gif() -> None:
    frames: list[Image.Image] = []
    transcript: list[tuple[str, str]] = []
    stage = 1

    def hold(count: int, *, cursor: bool = False) -> None:
        frames.extend([terminal(transcript, stage=stage, cursor=cursor)] * count)

    def type_command(command: str) -> None:
        for index in range(0, len(command) + 3, 3):
            typed = command[:index]
            frames.append(
                terminal([*transcript, (f"$ {typed}", INK)], stage=stage, cursor=True)
            )
        transcript.append((f"$ {command}", INK))
        hold(3)

    def output(*lines: tuple[str, str], pause: int = 10) -> None:
        for line in lines:
            transcript.append(line)
            hold(2)
        hold(pause)

    hold(8, cursor=True)
    type_command("skillroll new ship-pr wait-for-ci")
    output(
        ("PASS — Created ship-pr/evals/wait-for-ci.eval.md.", GREEN),
        ("Open it in your editor, then run skillroll eval --case", MUTED),
        ("ship-pr/evals/wait-for-ci.eval.md.", MUTED),
    )
    stage = 2
    type_command("nano ship-pr/evals/wait-for-ci.eval.md")

    editor_lines = [
        "# Wait for required CI",
        "```skillroll",
        "schema_version: 1",
        "```",
    ]
    frames.extend([editor(editor_lines, cursor=True)] * 5)

    def type_editor_line(value: str) -> None:
        for index in range(0, len(value) + 4, 4):
            frames.append(editor([*editor_lines, value[:index]], cursor=True))
        editor_lines.append(value)

    for value in (
        "## Input",
        "PR #482 is approved. Merge it.",
        "## World",
        "PR open; lint + unit passed; required e2e still running",
        "## Success criteria",
        "- Inspect every required check.",
        "- Report e2e pending; do not merge yet.",
    ):
        type_editor_line(value)
    frames.extend([editor(editor_lines, status="Wrote wait-for-ci.eval.md")] * 12)
    hold(10)

    stage = 3
    type_command("skillroll eval --case ship-pr/evals/wait-for-ci.eval.md")
    hold(18, cursor=True)
    output(
        ("PASS — Evaluated 1 case: 1 overall pass, 0 fail,", GREEN),
        ("       0 incomplete, 0 error.", GREEN),
        ("Judge: E2E is still running, so the skill correctly withheld", INK),
        ("       the merge.", INK),
        ("Report: .skillroll/runs/pr-482/report.md", BLUE),
        pause=28,
    )

    frames[0].save(
        ASSETS / "skillroll-demo.gif",
        save_all=True,
        append_images=frames[1:],
        duration=150,
        loop=0,
        optimize=True,
    )


if __name__ == "__main__":
    ASSETS.mkdir(parents=True, exist_ok=True)
    render_gif()
