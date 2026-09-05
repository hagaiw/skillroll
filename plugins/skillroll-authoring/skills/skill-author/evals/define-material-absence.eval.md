# Define a material absence without exhaustive prohibitions

```skillroll
schema_version: 1
```

## Input

Improve a book-ordering skill whose search tool may return an empty list. An
empty list can mean either that no matching book exists or that the catalog is
temporarily unavailable, depending on a status field. The current skill just
says “search, then order the selected result.”

No external interaction is needed.

## World

No external interaction is needed.

## Success criteria

- Identify the empty-result meaning as material to whether ordering may continue.
- Recommend guidance that distinguishes no match from catalog failure using the status field.
- Keep the repair close to the search or ordering capability it constrains.
- Do not propose an exhaustive list of unrelated unsupported features or a rigid rewrite of the entire skill.
