# Example: the MCP reference memory server

`examples/mcp-memory/` is the first outside receipt: the tool-call schemas of
the official `modelcontextprotocol/servers` reference implementation, graded
by the bad calls they let through.

- `schema-mcp-memory-create-entities.json`: hand translation of the zod
  `EntitySchema` + `create_entities` inputSchema in
  `src/memory/index.ts` (lines 1165-1177 and 1292-1298 at HEAD, fetched
  2026-11-25T03:1xZ). The `_provenance` field inside records exactly what
  was translated and why `additionalProperties` is absent (zod's default
  strips unknown keys, it does not reject them).
- `corpus-mcp-memory-create-entities.jsonl`: 10 bad calls, one per line, with
  `corpus-README.txt` explaining each line's intent.
- `schema-mcp-memory-create-entities-FIXED.json`: the same schema with
  `.strict()`-equivalent bounds added.

Run it (bounded, per the fuzz-incident rule):

```
(ulimit -v 1000000; timeout 60 python3 schemacheck.py \
  examples/mcp-memory/schema-mcp-memory-create-entities.json \
  examples/mcp-memory/corpus-mcp-memory-create-entities.jsonl)
```

Result at HEAD 2026-11-25: **rejected 4/10 bad calls; 6 leaked** (exit 1).
The 4 rejected are the type checks zod does hold (null name, wrong-type
observations, numbers instead of strings, missing required key). The 6 leaks
are every bound the zod source lacks:

| leak | why it passes |
|---|---|
| empty entity name | no `minLength` on `name` |
| unknown top-level key (`dry_run`) | zod default strips it silently |
| unknown key inside an entity | same |
| zero entities | `z.array()` accepts `[]` by default |
| 10,000-char name | no `maxLength` anywhere |
| 5,000 empty observations | no `maxItems`, no `minLength` on items |

The fixed schema rejects 10/10 (exit 0). The gap between the shipped schema
and the fixed one is one `.strict()` call plus five bounds.

Second data point, same repo: the `sequentialthinking` tool
(`src/sequentialthinking/index.ts`) leaks 5/10, including the interesting
one: `nextThoughtNeeded: "true"` passes because `coercedBoolean` is a
`z.union([z.boolean(), z.string()])`, so a string is a valid boolean and the
model is never told its string became a bool.

Method note, stated plainly: zod schemas do not run here (no node in this
environment), so the JSON Schemas are hand translations, with the zod facts
they preserve documented in each `_provenance` field. The 4/10 rejections
match the zod source line by line, which is the check that the translation
is honest. Reproduce it with node + zod if you want the upstream truth.
