# Initialize a scoped fact-book

```skillroll
schema_version: 1
rules:
  - name: initialize command succeeds
    tool_name: Shell
    arguments:
      command: python3 scripts/fact_book.py init FACTS.md --scope "investigate intermittent API timeouts"
    result: "Initialized FACTS.md for scope: investigate intermittent API timeouts."
limits:
  max_turns: 4
  timeout_seconds: 90
  max_output_tokens: 1024
assertions:
  - final_output_contains: "FACTS.md"
checks:
  - name: fact-book helper self-test
    command: python3 plugins/fact-check/skills/fact-check/scripts/fact_book.py self-test
    covers:
      - scripts/fact_book.py
```

## Input

Start a fact-book for the ongoing debugging task “investigate intermittent API
timeouts”. There is no fact-book yet. Initialize it in the workspace as
`FACTS.md` and tell me what it is ready to hold.

## World

No `FACTS.md` exists. No claim has been verified yet. The selected skill's
bundled template and `fact_book.py` helper are readable. File and shell actions
are available through the agent's normal tools and are simulated by SkillRoll.

## Success criteria

- Create or initialize one scoped `FACTS.md` without inventing a fact.
- Include session scope and date metadata, and explain that only verified facts
  with sources will be written there.
- Do not overwrite an existing file or create a deterministic search index.
