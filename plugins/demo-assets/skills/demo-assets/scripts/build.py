"""Build all Pillow-based README demo assets in one command."""

from render_cards import render_report_card
from render_terminal_demo import render_gif
from visuals import ASSETS


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    render_gif()
    render_report_card()


if __name__ == "__main__":
    main()
