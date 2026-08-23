# Update a verified fact

```skillroll
schema_version: 1
rules:
  - name: old timeout record
    tool_name: Read
    arguments:
      path: FACTS.md
    result: |
      # Fact book

      ## Session

      - Scope: Verify the production API timeout
      - Started: 2026-07-01
      - Last updated: 2026-07-01
      - Review rule: Re-check service documentation before relying on it.

      ## Records

      ### R-005 — Production API timeout

      - Status: active
      - Confidence: high
      - Created: 2026-07-01
      - Updated: 2026-07-01
      - Last verified: 2026-07-01
      - Tags: api, timeout
      - Source: url: https://example.test/old-docs — timeout is 60 seconds
      - Context: Production API requests.
      - Statement: The production API client timeout is 60 seconds.
  - name: current timeout documentation
    tool_name: Read
    arguments:
      path: https://example.test/current-docs#timeouts
    result: "The production API client timeout is 30 seconds."
  - name: reject incomplete write
    tool_name: Write
    arguments:
      path: FACTS.md
    result: "ERROR: Write requires complete replacement content for FACTS.md."
limits:
  max_turns: 4
  timeout_seconds: 90
  max_output_tokens: 1024
assertions:
  - final_output_contains: "30 seconds"
```

## Input

The current documentation corrects the existing timeout fact. Read the book
and current source, then update the existing record so only the current
verified value is active. Preserve the record ID and source trail.

This eval exposes one `world_action` tool. Read `FACTS.md` and then exactly
`https://example.test/current-docs#timeouts`—not the old source URL. Read
`references/context.md` before writing, then use `Write` with complete
replacement `content`. Preserve the session metadata and exactly one canonical
`R-005` record. Keep `Status: active`, set `Updated` and `Last verified` to
`2026-08-18`, replace the source and statement with the verified 30-second
value, and do not leave the old 60-second wording in the book.

## World

`FACTS.md` contains `R-005`:

```text
### R-005 — Production API timeout
- Status: active
- Confidence: high
- Created: 2026-07-01
- Updated: 2026-07-01
- Last verified: 2026-07-01
- Tags: api, timeout
- Source: url: https://example.test/old-docs — timeout is 60 seconds
- Context: Production API requests.
- Statement: The production API client timeout is 60 seconds.
```

Reading `https://example.test/current-docs#timeouts` returns: `The production
API client timeout is 30 seconds.` An edit can update the existing record and
returns a successful edit result.

## Success criteria

- Read the old record and current source before editing.
- Preserve `R-005`, change its statement/source/`Updated`/`Last verified` as
  needed, and ensure the old 60-second claim is not left active.
- Report the current verified value as 30 seconds and identify its source.
