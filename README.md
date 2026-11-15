<h1 align="center">skillroll</h1>

<p align="center">
  <strong>Test what your AI assistant does with your skills.</strong><br>
  Describe a situation in Markdown. Let a Dungeon Master play the world.<br>
  See which actions it took and why the test passed or failed.
</p>

<p align="center">
  <a href="docs/case-study-testing-skill-decisions.md"><strong>Read the case study</strong></a> ·
  <a href="examples/release-gate-comparison/README.md#run-the-example">Run the demo</a> ·
  <a href="#quickstart">Test your own skill</a> ·
  <a href="docs/index.md">Documentation</a>
</p>

<p align="center">
  <img src="docs/assets/skillroll-mascot.png" width="540" alt="skillroll mascot: a hooded otter holding a twenty-sided die and field guide">
</p>

An [Agent Skill](https://agentskills.io/) is a set of reusable instructions
that teaches an AI assistant how to do a job. If you write or maintain skills,
**skillroll helps you test whether those instructions lead to the decisions
you intended.**

Give your skill a request, describe the situation around it, and say what good
behavior looks like. skillroll runs it with a model, simulates the tools it
uses, and records its actions. Read the report, change the instructions, and
run the same test again.

## Check the project before you deploy

In a simulated test, a deployment skill was asked to publish a website preview.
The user named one project, but old settings pointed to another. The assistant
sometimes published to the wrong project before sorting out the conflict. Its
commands succeeded; its decision was wrong.

The repair was small: check which project the user meant **before** deploying.
We ran the same case again. The repaired skill avoided the wrong project in
all 32 recorded runs of this case. No real project was changed.

[Read the case study](docs/case-study-testing-skill-decisions.md) for the
original results, the prompt change, and what the repaired runs still missed.
No setup or API key needed.

To try SkillRoll yourself, the separate
[release-skill demo](examples/release-gate-comparison/README.md#run-the-example)
includes runnable cases and recorded evidence. Follow the guide with Git,
Python 3.12+, and `uv` on macOS, Linux, or WSL. The file check runs offline.
To run the skill, you’ll need an OpenRouter API key with credits for the
configured models. Live results can vary.

## Describe the world. Test one decision.

An **eval** is a test for one important behavior. It is a Markdown file beside
your skill with three parts. For the preview example, the case describes:

| Part | What it supplies |
| --- | --- |
| `Input` | The user's request to preview the website in the intended project. |
| `World` | Conflicting project settings, a way to check the intended target, and what happens when the assistant deploys. |
| `Success criteria` | Confirm the target before creating a preview; do not deploy to the wrong project. |

The **Dungeon Master** plays the World. When the assistant reads a file,
checks an account, or tries a command, it returns a result consistent with
your description. The assistant discovers the situation through those actions;
it cannot read the World or the success criteria.

You write the situation in prose instead of building mock services or a new
test harness for each skill. The simulated actions cannot change your real
files or services. A model-based judge checks the recorded actions and final
answer against your criteria, then explains the verdict.

Start with one decision that matters. A useful case can stay with the skill
and catch the same mistake after a later edit. The
[eval-writing guide](docs/writing-evals.md) shows a complete Markdown case;
the [authoring guide](docs/authoring.md) covers skills and evals together.

## Quickstart

You'll need Python 3.12 or later, [`uv`](https://docs.astral.sh/uv/), and a
repository containing an existing skill. Install the command-line tool:

```shell
uv tool install skillroll
```

From your skills repository, run the interactive setup:

```shell
cd /path/to/repository
skillroll init
```

This creates `skillroll.toml`, identifies the skills folder, and helps you
configure a model endpoint. Running a skill requires an API key for an
OpenAI-compatible endpoint with tool calling and structured outputs. See
[model setup](#model-setup) below if you need a configuration.

Create one case. Replace `my-skill` with your existing skill's folder name and
`check-before-acting` with a name for the behavior you want to test:

```shell
skillroll new my-skill check-before-acting
```

Edit `my-skill/evals/check-before-acting.eval.md` under the skills folder.
Fill in `Input`, `World`, and `Success criteria`, following the
[eval-writing guide](docs/writing-evals.md). Then check the files offline:

```shell
skillroll validate
```

Validation checks structure. To see how the skill behaves, make your provider
key available in the current shell, check the connection, and run the case.
These model calls may incur provider charges:

```shell
export SKILLROLL_API_KEY="your-key"
skillroll doctor
skillroll eval --case my-skill/evals/check-before-acting.eval.md
```

Open `report.md` in the printed `.skillroll/runs/` directory. It explains the
verdict and the evidence behind it. Once you have more cases, `skillroll eval`
runs the cases under your current working directory.

### Model setup

If you configured a model during `init`, its settings are already in
`skillroll.toml`. Otherwise add them now. For example, this is the repository's
existing OpenRouter evaluator baseline:

```toml
[inference]
base_url = "https://openrouter.ai/api/v1"
model = "openai/gpt-5.6-luna-pro"
api_key_env = "SKILLROLL_API_KEY"
```

OpenRouter requires an API key and credits for the chosen model. You can use
another compatible provider. By default, the configured model runs the skill,
the Dungeon Master, and the judge.

The [configuration guide](docs/configuration.md) covers provider compatibility,
separate skill models, and optional cost estimates. Cost depends on the model,
prompt size, actions, and output length; skillroll records usage when the
provider supplies it.

## Read the evidence. Fix the prompt. Roll again.

A failed case gives you something concrete to work on. Read the action record:
did the skill skip a check, act on the wrong information, or claim success
without doing the work? Fix the responsible instruction, rerun the same case,
and compare the evidence. Keep the case to catch the failure if it returns.

| Outcome | What it means |
| --- | --- |
| `PASS` | The observed behavior met the case. |
| `FAIL` | The observed behavior missed a success criterion. |
| `INCOMPLETE` | A required repository check did not run. |
| `ERROR` | skillroll could not produce a trustworthy verdict. |

Sometimes the case or the judge needs attention instead of the skill. Check
that the request is realistic, the World describes the intended situation,
and the criteria allow reasonable ways to succeed. Repeat important cases:
one pass is evidence for one run, not proof that the skill is correct.

The [results guide](docs/results.md) explains diagnosis and the saved evidence:
`report.md` for review, `transcript.jsonl` for the full action history, and
`result.json` for automation. Use ordinary tests for scripts and real artifact
checks; simulated success does not prove that a real command works.

## Take useful cases further

**Compare models.** Once you have useful cases, test whether a less expensive
model can run your skill well. `skillroll compare` runs the same cases with
candidate skill models while keeping the Dungeon Master and judge fixed. Read
the [comparison guide](docs/comparing-models.md) for commands, cost reporting,
and the limits of what a comparison can show.

**Catch regressions in pull requests.** After creating `skillroll.toml`, run:

```shell
skillroll init --github-workflow
```

This generates an advisory workflow without replacing an existing file.
Pull requests validate changed skills and evals without a model key. Follow
the [GitHub Actions guide](docs/github-actions.md) to review the workflow and
enable model-backed runs. Fork pull requests never receive the key. Start
with advisory results while you learn which cases give useful feedback.

## Local, open source, and explicit about trust

- No SkillRoll account, hosted service, telemetry, analytics, or model tracing.
- Model requests go to the endpoint you configure. Selected skill and case
  text are disclosed to that provider.
- API keys stay in environment variables, outside configuration and artifacts.
- Reports stay in local `.skillroll/` directories. They can contain case text
  and model output; review them before sharing.
- The Dungeon Master cannot access your real filesystem, shell, network, or
  services. Optional repository commands run on your host only after explicit
  opt-in; they are not sandboxed.
- The code and prompts are public under the [MIT License](LICENSE).

Read the [security model](docs/security.md) for the full boundaries. skillroll
is an early project: local evals and advisory GitHub checks work today; expect
the interface to change between minor releases.

## Keep exploring

- [Author skills and evals](docs/authoring.md), including optional authoring guidance for Claude Code
- [Write an eval](docs/writing-evals.md)
- [Configure models and cost](docs/configuration.md)
- [Read results and fix problems](docs/results.md)
- [Compare skill models](docs/comparing-models.md)
- [Add advisory GitHub checks](docs/github-actions.md)

The [documentation index](docs/index.md) organizes the guides by task. For help,
see [SUPPORT.md](.github/SUPPORT.md). To contribute, start with
[PRINCIPLES.md](PRINCIPLES.md) and [CONTRIBUTING.md](.github/CONTRIBUTING.md).
Security reporting and project governance are in
[SECURITY.md](.github/SECURITY.md) and [GOVERNANCE.md](.github/GOVERNANCE.md).
