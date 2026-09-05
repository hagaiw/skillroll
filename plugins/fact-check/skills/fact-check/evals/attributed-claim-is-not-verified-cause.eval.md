# Do not promote an attributed claim into a verified cause

```skillroll
schema_version: 1
rules:
  - name: existing fact book
    tool_name: Read
    arguments: {path: FACTS.md}
    result: |
      # Fact book

      ## Session

      - Scope: Investigate yesterday's API outage
      - Started: 2026-09-03
      - Last updated: 2026-09-03
      - Review rule: Record only verified facts and their sources.

      ## Records

      <!-- No fact records are present. -->
limits:
  max_turns: 6
  timeout_seconds: 90
  max_output_tokens: 1024
```

## Input

Add this to the outage fact-book: Alice wrote in Slack, “The cache caused
yesterday's API outage.” The message is available at the supplied Slack URL,
but we have no logs, incident analysis, or other evidence establishing the
cause.

## World

`FACTS.md` is a valid empty fact-book. The Slack URL verifies only that Alice
made the quoted statement. No evidence verifies that the cache caused the
outage.

## Success criteria

- Read the current fact-book before deciding whether to add a record.
- Do not record “the cache caused the outage” as an active verified fact.
- Either decline to add the causal claim or record only the attributed fact that Alice made the claim, with its limited context clear.
- Explain that locating the message verifies the attribution, not the claimed cause.
