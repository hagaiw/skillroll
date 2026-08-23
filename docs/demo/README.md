# SkillRoll demo assets

The README demo assumes SkillRoll is already configured in the current skills
repository. An existing `ship-pr` skill needs a durable check against merging
while required CI is still running. The author creates `wait-for-ci`, fills
`Input`, `World`, and `Success criteria` in a terminal editor, and runs the case
successfully. Provider setup is intentionally outside the story.

The animation uses SkillRoll's real command names and result wording. The run
identifier, incident text, and report excerpt are illustrative so the asset can
be rendered deterministically without credentials or paid inference. Do not use
the animation as evidence of a model's behavior.

Regenerate the assets from the repository root:

```shell
uvx --with pillow python plugins/demo-assets/skills/demo-assets/scripts/build.py
```

The script writes:

- `docs/assets/skillroll-demo.gif`: README product tour; and
- `docs/assets/evidence-report.png`: dark evidence summary for the same story.

The dogfooded [`demo-assets`](../../plugins/demo-assets/skills/demo-assets/SKILL.md)
skill owns the storytelling guidance and deterministic renderers. Its
[asset-pipeline reference](../../plugins/demo-assets/skills/demo-assets/references/asset-pipeline.md)
documents focused commands for individual assets.

The terminal-native mascot is generated with Chafa through the skill script:

```shell
python plugins/demo-assets/skills/demo-assets/scripts/render_ansi.py \
  docs/assets/skillroll-mascot-closeup-ansi-source.png \
  docs/assets/skillroll-mascot-closeup.ansi

cat docs/assets/skillroll-mascot-closeup.ansi
```

`skillroll-mascot.png` is the user-provided SkillRoll otter artwork and is
intentionally not overwritten by the renderer.
