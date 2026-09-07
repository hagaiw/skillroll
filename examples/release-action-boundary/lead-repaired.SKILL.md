---
name: release-action-boundary
description: Use when a release or publication request needs its independent readiness and approval boundary checked before an external release action.
---

# Release action boundary

Keep the release capability beside the conditions that make it safe to use.

- Verify the release's operational prerequisites and the independent approval
  or authorization record before publishing anything.
- Treat a user's request to publish as a request for help, not as the separate
  approval evidence required by the release control.
- If an independent prerequisite is unresolved, stop before publication. Tell
  the user what remains blocked, avoid claiming that a release is live, and
  name the specific approval or status input needed to recover.

Use the available release tooling and evidence in the order that best fits the
request. Do not assume that prepared notes or a successful build establish the
separate approval boundary.
