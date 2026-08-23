# Assess a configuration migration risk

```skillroll
schema_version: 1
```

## Input

Assess risk: a configuration format adds a required timeout field; migration tests are absent.

## World

The supplied facts are complete; no migration test result exists.

## Success criteria

- Identify compatibility risk from the required field.
- Recommend migration testing and label the result as uncertain.
