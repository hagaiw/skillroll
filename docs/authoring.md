# Authoring skills and evals

SkillRoll treats skill design and eval design as related but separate work. A
skill supplies reusable operating guidance. An eval creates evidence about one
observable behavior without prescribing the prompt's wording or structure.

The canonical authoring standards live with the three skills in the optional
`skillroll-authoring` Claude Code plugin:

- [`skillroll-setup/SKILL.md`](../plugins/skillroll-authoring/skills/skillroll-setup/SKILL.md)
  gives the shortest safe path from an existing skills folder to a first
  SkillRoll eval. Its
  [setup context](../plugins/skillroll-authoring/skills/skillroll-setup/references/context.md)
  contains the command examples.
- [`skill-author/SKILL.md`](../plugins/skillroll-authoring/skills/skill-author/SKILL.md)
  covers creating, reviewing, auditing, and improving Agent Skills. Its
  [authoring context](../plugins/skillroll-authoring/skills/skill-author/references/context.md)
  explains scope, discovery, knowledge and capability boundaries, progressive
  disclosure, repair, and structural auditing.
- [`eval-author/SKILL.md`](../plugins/skillroll-authoring/skills/eval-author/SKILL.md)
  covers writing and reviewing SkillRoll cases. Its
  [eval context](../plugins/skillroll-authoring/skills/eval-author/references/context.md)
  explains realistic Input, private World state, observable criteria, knowledge
  boundaries, failure diagnosis, and evidence labels.

Use [Writing evals](writing-evals.md) for the CLI-oriented walkthrough. The
[project principles](../PRINCIPLES.md) state the shorter rules that changes to
SkillRoll itself must preserve.

## Install paths

SkillRoll has two separate, optional-to-combine pieces:

- The Python runner is installed with `uv tool install skillroll`. It provides
  the `skillroll` command for `init`, `validate`, `doctor`, and `eval`.
- The authoring guidance is a Claude Code plugin distributed with this source
  repository. It is not included in the Python package and is not installed by
  `uv tool install skillroll`.

The plugin is declared in
[`.claude-plugin/marketplace.json`](../.claude-plugin/marketplace.json) and
its manifest is
[`plugins/skillroll-authoring/.claude-plugin/plugin.json`](../plugins/skillroll-authoring/.claude-plugin/plugin.json).
The marketplace entry points to the three `skills/*/SKILL.md` files linked
above; there is no second installer or duplicate copy.

### Optional Claude Code installation

Claude Code's current `plugin marketplace add` command accepts a URL, local
path, or GitHub repository. The repository's public GitHub source is the
marketplace source for the commands below:

```shell
claude plugin marketplace add https://github.com/hagaiw/skillroll
claude plugin install skillroll-authoring@skillroll --scope user
claude plugin list --json
```

The first command adds the repository's checked-in marketplace metadata; it
does not claim that a separate marketplace registry publication exists. For a
local checkout, use its path instead:

```shell
claude plugin marketplace add /path/to/skillroll
```

Installing with `--scope user` changes Claude Code's user configuration. Run
these commands only when you want the optional plugin and have reviewed the
source. The install does not replace the Python runner: install that separately
with `uv tool install skillroll` when you need to run SkillRoll commands.

## Evidence boundary

A prompt review can find ambiguity, missing prerequisites, undefined absence
semantics, or a constraint far from the capability it governs. Those findings
justify a candidate repair or eval; they do not by themselves prove model
behavior.

Use the smallest appropriate evidence source:

| Claim | Evidence |
| --- | --- |
| A skill or eval has valid structure | Offline validation and review |
| A model follows a skill in a particular scenario | A completed model-backed eval |
| A script or exact invariant works | A deterministic test |
| A real command, service, or artifact works | A trusted external check |

Record what actually ran and keep setup errors, authoring defects, behavioral
failures, and external failures separate.
