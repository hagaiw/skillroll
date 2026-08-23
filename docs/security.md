# Security model

SkillRoll reads skill repositories, sends selected text to a configured model
endpoint, and can run repository commands after explicit opt-in. It is not a
sandbox for arbitrary repository code.

## Boundaries

- Untrusted pull requests receive secretless validation. Forks never receive
  the inference key.
- The API key named in `skillroll.toml` is used only for inference. It is not
  passed to repository checks, artifacts, CLI arguments, or diagnostics.
- Skill file reads stay inside the selected skill root and reject symlink
  escapes. Simulated World actions cannot access the real repository, network,
  shell, services, or other skills.
- Model input excludes eval content, hidden paths, bytecode, and common
  generated or dependency directories.
- Repository checks are ordinary host commands. They run only with
  `--run-commands` or the corresponding reviewed workflow option. The generated
  pull-request workflow does not run them automatically.
- Evidence can contain Input, World text, model output, action results, and
  bounded command output. SkillRoll removes the configured inference key,
  provider headers, and absolute local paths, but cannot make arbitrary content
  safe to publish. Review evidence before sharing it.

For GitHub automation, review the exact revision before manually enabling live
evaluation or repository checks. Keep artifact uploads off for sensitive
repositories or use the shortest useful retention.

See [SECURITY.md](../SECURITY.md) to report a vulnerability privately. Do not
open a public issue containing a key, exploit, private path, or sensitive
artifact.
