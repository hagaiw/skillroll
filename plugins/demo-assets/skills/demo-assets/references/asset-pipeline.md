# Asset pipeline

Run commands from the repository root.

## Pillow-rendered media

```shell
uvx --with pillow python plugins/demo-assets/skills/demo-assets/scripts/build.py
```

The build orchestrator calls independent renderers for:

- `skillroll-demo.gif` (`render_terminal_demo.py`);
- `evidence-report.png` (`render_cards.py`).

Shared typography, colors, terminal chrome, and repository paths live in
`visuals.py`.

## ANSI mascot

Prepare a source image with reduced empty canvas and stronger contrast:

```shell
uvx --with pillow python \
  plugins/demo-assets/skills/demo-assets/scripts/prepare_mascot.py \
  SOURCE.png docs/assets/skillroll-mascot-closeup-ansi-source.png
```

Render it with Chafa:

```shell
python plugins/demo-assets/skills/demo-assets/scripts/render_ansi.py \
  docs/assets/skillroll-mascot-closeup-ansi-source.png \
  docs/assets/skillroll-mascot-closeup.ansi
```

Use `--colors 256` and a distinct destination for the portable variant. Copy a
chosen terminal asset into `src/skillroll/_assets/setup-mascot.ansi` only when
the product integration should change.

## Verification

- Open each PNG and inspect the GIF's final frame; check clipping and legibility.
- Confirm the GIF dimensions, duration, and loop behavior.
- Preview ANSI with `cat` in a compatible terminal.
- Run formatting, focused documentation/package tests, and `git diff --check`.
- Review `git status` so generated files and their sources are both accounted
  for.
