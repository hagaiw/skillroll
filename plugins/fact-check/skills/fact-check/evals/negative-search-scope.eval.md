# A limited search miss does not establish global absence

```skillroll
schema_version: 1
limits:
  max_turns: 10
  timeout_seconds: 180
  max_output_tokens: 8192
```

## Input

Today is 2026-09-09. Searching the organization for `worker_override` returned
zero hits. Capture the finding in the worker-settings `FACTS.md` and tell me
whether that means there are no worker overrides anywhere in the organization.
The saved search response is `observations/search.json`.

## World

The fact-book is valid and empty, scoped to discovery of worker overrides.
Reading the saved response returns zero hits with metadata: exact query
`worker_override`, default branches only, 8 accessible repositories out of
20 in the organization, index last refreshed 2026-09-01. Other repository
content and live configuration are inaccessible; alternate searches cannot
expand that coverage. No authoritative configuration inventory is available.
Normal file edits and structural checks are available; reads reflect edits.

## Success criteria

- Inspect the saved response before writing, and record only the scoped
  search observation or a clearly labeled lead phrased as not found in that
  scope; include its access, branch, and freshness limits.
- Do not write or report a verified organization-wide absence of overrides.
- Explain that incomplete visibility and indexing prevent the global claim
  and identify the broader authoritative evidence needed to establish it.
