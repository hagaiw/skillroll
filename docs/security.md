# Security model

SkillRoll reads skill repositories, sends selected text to a configured model
endpoint, and can run repository commands after explicit opt-in. It is not a
sandbox for arbitrary repository code.

## What each role sees

- The skill runner receives `Input` and the selected skill bundle. It does not
  receive `World`, `Success criteria`, or other eval content.
- The Dungeon Master receives `World`, the requested action, and prior action
  results. It cannot access the real repository, filesystem, shell, network,
  services, or other skills.
- The judge receives `Input`, `Success criteria`, the completed action
  transcript, and the skill's final response. It does not execute the skill or
  interact with the World.

The configured model endpoint performs these separate roles. Treat all text
sent to it as disclosed to that endpoint.

## Telemetry

SkillRoll has no telemetry, analytics, tracking, or model tracing, and will not
add them. There is no SkillRoll service or account. Network traffic is limited
to model requests you start against the endpoint you configured.

The model provider is a separate trust boundary and may keep its own logs or
telemetry. Review that provider's policy before sending private repository
content.

## Boundaries

- Untrusted pull requests receive secretless validation. Forks never receive
  the inference key.
- The API key named in `skillroll.toml` is used only for model calls. It is not
  passed to repository checks, artifacts, CLI arguments, or diagnostics.
- Skill file reads stay inside the selected skill root and reject symlink
  escapes. The skill bundle excludes eval files, hidden paths, bytecode, and
  common generated or dependency directories.
- Repository checks are ordinary host commands. They run only with
  `--run-commands` or the corresponding reviewed workflow option. The
  generated pull-request workflow does not run them automatically.
- Evidence can contain Input, World text, model output, action results, and
  bounded command output. SkillRoll removes the configured inference key,
  provider headers, and absolute local paths, but cannot make arbitrary content
  safe to publish. Review evidence before sharing it.

For GitHub automation, review the exact revision before manually enabling
model-backed evaluation or repository checks. Keep artifact uploads off for
sensitive repositories or use the shortest useful retention.

See [SECURITY.md](../.github/SECURITY.md) to report a vulnerability privately.
Do not open a public issue containing a key, exploit, private path, or
sensitive artifact.
