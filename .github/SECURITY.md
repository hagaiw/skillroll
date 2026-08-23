# Security policy

SkillRoll can send skill and eval text to a configured endpoint and can run
repository commands after explicit opt-in. Read the
[security model](../docs/security.md) before using live evaluation or repository
checks in CI.

## Supported versions

The current `main` branch is supported. Published releases will be supported
as stated in their release notes.

## Report a vulnerability

Use GitHub's private vulnerability reporting:

<https://github.com/hagaiw/skillroll/security/advisories/new>

Do not open a public issue for an undisclosed vulnerability. Include the
affected commit or version, impact, a minimal redacted reproduction, relevant
configuration, and any tested mitigation.

Never include API keys, tokens, private repository content, raw private prompts
or responses, private paths, or unreviewed evidence. Redact first and say what
was removed.

The maintainer will acknowledge a report within 7 calendar days and coordinate
a fix or advisory when appropriate. This is a one-person project, so resolution
time depends on severity and available capacity. Please allow a reasonable
coordination window before public disclosure.
