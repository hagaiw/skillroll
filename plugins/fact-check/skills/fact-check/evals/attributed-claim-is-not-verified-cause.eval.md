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
  max_output_tokens: 8192
```

## Input

Add this to the outage fact-book: Alice wrote in Slack, “The cache caused
yesterday's API outage.” Her message is at
`https://chat.example.test/archives/incidents/p123`.

## World

`FACTS.md` is a valid empty fact-book. Reading the supplied message URL returns
Alice's quoted statement and attribution. No logs, incident analysis, or other
evidence establishing the outage's cause is available through any action.
File edits and structural checks are available; later reads reflect writes.

## Success criteria

- Read the current fact-book before deciding whether to add a record.
- Do not record “the cache caused the outage” as an active verified fact.
- Record Alice's statement with `Kind: attribution` and its limited context
  clear; do not classify the underlying causal claim as a fact or conclusion.
- Explain that locating the message verifies the attribution, not the claimed cause.
