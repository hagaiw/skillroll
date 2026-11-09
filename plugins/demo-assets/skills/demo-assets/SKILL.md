---
name: demo-assets
description: Plan and regenerate truthful terminal demos, README cards, social previews, and ANSI artwork for a developer-tool repository. Use when product media must tell a concise story while remaining reproducible from repository scripts.
---

# Demo assets

Turn a real product workflow into concise, reproducible repository media. Keep
the authored story separate from deterministic rendering:

- decide what the demo may honestly claim before changing pixels;
- put repeatable image, animation, and terminal conversion in `scripts/`;
- keep source artwork distinct from generated outputs;
- label simulated identifiers or model behavior as illustrative; and
- never imply that a rendered demo is evidence from a live run.

For a terminal demo, read [terminal stories](references/terminal-stories.md).
For asset paths, regeneration commands, and verification, read
[asset pipeline](references/asset-pipeline.md).

For a request to explain or plan asset generation, give the applicable commands
and verification steps without changing files. Use an existing Python environment
with Pillow and an existing Chafa installation. If a dependency is missing,
ask before installing it, including through a package runner. Keep the plan
local unless the user requests an upload or publication.

Use the narrowest script for the requested change. Use `scripts/build.py` only
when all Pillow-rendered README assets should be refreshed together. Inspect
the generated stills and the final animation for timing and legibility before
reporting completion. Include that inspection step in a demo plan, even when
the request is limited to planning.

Do not overwrite user-provided source art unless explicitly requested. Do not
publish, upload a social preview, install system tools, or change product CLI
behavior merely to make a demo convenient without the user's authorization.
