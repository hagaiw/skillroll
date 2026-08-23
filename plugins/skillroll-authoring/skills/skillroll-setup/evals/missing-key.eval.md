# Explain a missing setup key

```skillroll
schema_version: 1
```

## Input

Doctor says the configured API-key environment variable is missing.

## World

The user has a valid configuration but has not set the named environment variable.

## Success criteria

- Explain how to set the named variable in the shell or CI secret.
- Do not ask the user to put a key in skillroll.toml.
