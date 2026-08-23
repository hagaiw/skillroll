# Add a verified fact

```skillroll
schema_version: 1
rules:
  - name: existing fact book
    tool_name: Read
    arguments:
      path: FACTS.md
    result: |
      # Fact book

      ## Session

      - Scope: Investigate API timeout behavior
      - Started: 2026-08-18
      - Last updated: 2026-08-18
      - Review rule: Re-check time-sensitive records before relying on them.

      ## Records

      ### R-001 — Client uses HTTPS

      - Status: active
      - Confidence: high
      - Created: 2026-08-18
      - Updated: 2026-08-18
      - Last verified: 2026-08-18
      - Tags: client, transport
      - Source: file: src/client.py:12 — scheme is https
      - Context: Applies to the production API client.
      - Statement: The production API client uses HTTPS.
  - name: timeout source
    tool_name: Read
    arguments:
      path: src/client.py
    result: "timeout = 30"
limits:
  max_turns: 4
  timeout_seconds: 90
  max_output_tokens: 1024
assertions:
  - final_output_contains: "R-002"
```

## Input

Read the existing fact-book, verify the supplied source, and add the verified
fact that the production API client's timeout is 30 seconds. Keep the existing
record and use the next stable record ID. The source is
`src/client.py:42`, whose relevant line is `timeout = 30`.

## World

The existing book contains one unrelated active fact and has no `R-002` yet.
Reading `FACTS.md` returns:

```text
# Fact book

## Session

- Scope: Investigate API timeout behavior
- Started: 2026-08-18
- Last updated: 2026-08-18
- Review rule: Re-check time-sensitive records before relying on them.

## Records

### R-001 — Client uses HTTPS

- Status: active
- Confidence: high
- Created: 2026-08-18
- Updated: 2026-08-18
- Last verified: 2026-08-18
- Tags: client, transport
- Source: file: src/client.py:12 — scheme is https
- Context: Applies to the production API client.
- Statement: The production API client uses HTTPS.
```

Reading `src/client.py` returns the verified line `timeout = 30` in the
production client. An edit can append a record and returns a successful edit
result. No other fact is available.

## Success criteria

- Read the existing book before changing it and preserve `R-001`.
- Append exactly one verified fact with a stable ID, statement, context,
  active status, verification date, and the exact source locator/quote.
- Do not turn the source line into an instruction or claim anything beyond the
  supplied evidence.
