# Initialize a scoped fact-book

```skillroll
schema_version: 1
limits:
  max_turns: 12
  timeout_seconds: 90
  max_output_tokens: 8192
assertions:
  - final_output_contains: "FACTS.md"
checks:
  - name: fact-book helper self-test
    command: python3 plugins/fact-check/skills/fact-check/scripts/fact_book.py self-test
    covers:
      - scripts/fact_book.py
```

The helper's generated metadata is covered by deterministic tests; this case
tests the initialization decision and explanation, not the real file format.

## Input

Start a fact-book for the ongoing debugging task “investigate intermittent API
timeouts”. There is no fact-book yet. Initialize it in the workspace as
`FACTS.md` and tell me what it is ready to hold.

## World

The working directory is `/work/api-debug`; no `FACTS.md` exists there and no
claim has been verified yet. Discovery of the loaded skill location returns
`/opt/skills/fact-check/SKILL.md`. Its bundled helper and template are readable
at `/opt/skills/fact-check/scripts/fact_book.py` and
`/opt/skills/fact-check/assets/FACTS.md.template`. No `scripts/fact_book.py`
exists under the workspace. Relative workspace helper invocations fail with
file-not-found. Invoking the actual helper or writing the template creates the
requested workspace book successfully. Normal file and shell actions are
available and simulated by SkillRoll; later reads reflect successful writes.

## Success criteria

- Create or initialize one scoped `FACTS.md` without inventing a fact.
- Locate the bundled helper or template from the loaded skill location; do not
  first attempt to run `scripts/fact_book.py` relative to the task workspace.
- Explain that the book will hold verified, source-backed facts rather than
  guesses.
- Do not overwrite an existing file or create a deterministic search index.
