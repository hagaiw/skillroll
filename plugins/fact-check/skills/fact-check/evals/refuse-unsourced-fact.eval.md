# Refuse an unsourced fact

```skillroll
schema_version: 1
rules:
  - name: empty fact book
    tool_name: Read
    arguments:
      path: FACTS.md
    result: |
      # Fact book

      ## Session

      - Scope: Assess provider request limits
      - Started: 2026-08-18
      - Last updated: 2026-08-18
      - Review rule: Require a concrete source before adding a fact.

      ## Records

      <!-- No fact records are present. -->
limits:
  max_turns: 3
  timeout_seconds: 90
  max_output_tokens: 1024
assertions:
  - final_output_contains: "Not added:"
```

## Input

I remember that the provider limit is 1,000 requests per minute. Please add it
to `FACTS.md`. I do not have a current URL, code path, test, or attributed human
statement for it.

## World

`FACTS.md` exists and contains no provider-limit record. No external source is
available in this task. Reading the book returns a valid empty fact-book. The
conversation contains only the remembered number.

## Success criteria

- Do not write the remembered number as a fact and do not invent a source,
  confidence, or verification date.
- Explain that the claim was not added and request a concrete source in the
  active conversation.
- Keep the fact-book unchanged.
