# Reconcile a stale fact

```skillroll
schema_version: 1
rules:
  - name: existing stale candidate
    tool_name: Read
    arguments:
      path: FACTS.md
    result: |
      # Fact book

      ## Session

      - Scope: Reconcile cache-key behavior across service releases
      - Started: 2025-12-01
      - Last updated: 2025-12-01
      - Review rule: Re-check facts when the service release changes.

      ## Records

      ### R-001 — Cache keys omit tenant ID

      - Status: active
      - Confidence: high
      - Created: 2025-12-01
      - Updated: 2025-12-01
      - Last verified: 2025-12-01
      - Tags: cache
      - Source: file: release-4.1.md — cache keys omit tenant ID
      - Context: Applies to the old service release.
      - Statement: Cache keys omit the tenant ID.
  - name: current release source
    tool_name: Read
    arguments:
      path: release-4.2.md
    result: "Cache keys now include tenant ID."
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
  - final_output_contains: "tenant"
```

## Input

Reconcile the cache-key fact in the existing book against the current source.
Keep the history understandable and report which fact is safe to use now.

This eval exposes one `world_action` tool. Read `FACTS.md` and then
`release-4.2.md`, read `references/context.md` before the first record write,
and then call `Write` with `path` and complete replacement `content`. Do not
finish with a plan. Use the canonical Markdown record shape. Preserve the
session metadata, mark `R-001` as `superseded`, add one active replacement with
`Supersedes: R-001`, and use the current date `2026-08-18` for the replacement
record's lifecycle fields.

## World

The existing book has this active record, last verified on 2025-12-01:

```text
### R-001 — Cache keys omit tenant ID
- Status: active
- Confidence: high
- Created: 2025-12-01
- Updated: 2025-12-01
- Last verified: 2025-12-01
- Tags: cache
- Source: file: release-4.1.md — cache keys omit tenant ID
- Context: Applies to the old service release.
- Statement: Cache keys omit the tenant ID.
```

The current source `release-4.2.md` says: `Cache keys now include tenant ID.`
Reading the existing book and current source returns those exact contents. An
edit can update or append records and returns a successful edit result.

## Success criteria

- Read both the existing record and current source before editing.
- Do not leave the old statement as an active current fact. Mark it stale,
  disputed, or superseded, or revise it with an explicit current source.
- Preserve a clear source trail and current verification date, and report that
  the current release includes the tenant ID in cache keys.
