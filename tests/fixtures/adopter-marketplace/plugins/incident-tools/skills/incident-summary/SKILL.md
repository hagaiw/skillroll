---
name: incident-summary
description: Use when a user needs a concise evidence-based incident summary.
---

# Incident summary

When the user gives an incident identifier, call the `fetch-incident` action
exactly once with an object whose `incident_id` field contains that identifier.
Use the returned artifact as the only source of incident facts. Repeat the
returned incident identifier, service, status, and evidence in a concise
summary. Never invent a missing fact or claim that an unavailable action
succeeded.

Read [incident context](references/context.md) for the artifact shape.
