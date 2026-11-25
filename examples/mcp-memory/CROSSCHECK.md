# Cross-check: mcpseal vs schemacheck on the same two MCP reference servers

Two graders, two different halves of the same question. mcpseal
(@hashshabbir/mcp-pack 0.3.0, run here 2026-11-25T03:3xZ) grades what the
package's code and metadata could do to you. schemacheck grades what the
tool's input schema lets a model get away with. Both matter; neither sees
the other's half.

## What each grader saw

mcpseal's 12 rules (read from dist/src/mcpseal.js): dynamic code (eval /
new Function), credential-file references, env dumps, hard-coded IPs,
child_process shell use, decode-then-execute, webhook/paste sends, no
license, no repository, package < 14 days old, single maintainer, network
requests. All code-side and metadata-side. The word "schema" appears once
in its grader source: the CLI's own argument parser.

schemacheck's 10 bad calls per target: missing required keys, wrong types,
empty strings, unknown keys, empty arrays, unbounded lengths, unbounded
array sizes, type-coercion traps. All schema-side.

## mcpseal's read (run here, bounded)

```
$ node node_modules/@hashshabbir/mcp-pack/dist/src/mcpseal.js \
    @modelcontextprotocol/server-memory
@modelcontextprotocol/server-memory@1.0.0
Seal: A  (100/100)
  No findings.

$ node node_modules/@hashshabbir/mcp-pack/dist/src/mcpseal.js \
    @modelcontextprotocol/server-sequential-thinking
@modelcontextprotocol/server-sequential-thinking@1.0.0
Seal: A  (100/100)
  No findings.
```

## schemacheck's read (same servers, schema side)

```
$ python3 schemacheck.py \
  examples/mcp-memory/schema-mcp-memory-create-entities.json \
  examples/mcp-memory/corpus-mcp-memory-create-entities.jsonl
rejected 4/10 bad calls; 6 leaked

$ python3 schemacheck.py \
  examples/mcp-memory/schema-mcp-sequentialthinking.json \
  examples/mcp-memory/corpus-mcp-sequentialthinking.jsonl
rejected 5/10 bad calls; 5 leaked
```

Details per leak in the sibling README. Short version: empty entity names
pass, unknown keys are stripped silently, 10,000-char names pass, 5,000
empty observations pass, and `nextThoughtNeeded: "true"` passes because
`coercedBoolean` is a `z.union([z.boolean(), z.string()])`.

## What this says

Same two servers: **A (100/100) and A (100/100)** from the supply-chain
side, **6/10 and 5/10 leaks** from the schema side. The A grades are
correct for what mcpseal measures; they just do not measure the half of
the surface where an agent's own tool calls live. A grader that wants one
letter for "is this server safe to hand an agent" needs both halves.

## Answer to grimmer's HN question (story 50623202, comment 2026-11-24T13:38:29Z)

"Could it check for prompt injection on the MCP tool schema side?" — not
as shipped, and the gap is measurable: on the two MCP reference servers,
mcpseal reports zero findings while the schemas let 11 of 20 known-bad
calls through. Static schema checks catch one class of it (missing
required, wrong types, no bounds, silent coercion); what they cannot see
is a description string that tells the model to do something harmful, so
a full answer needs both.

## Reproduce

```
npm install @hashshabbir/mcp-pack
node node_modules/@hashshabbir/mcp-pack/dist/src/mcpseal.js \
  @modelcontextprotocol/server-memory
node node_modules/@hashshabbir/mcp-pack/dist/src/mcpseal.js \
  @modelcontextprotocol/server-sequential-thinking
python3 schemacheck.py \
  examples/mcp-memory/schema-mcp-memory-create-entities.json \
  examples/mcp-memory/corpus-mcp-memory-create-entities.jsonl
python3 schemacheck.py \
  examples/mcp-memory/schema-mcp-sequentialthinking.json \
  examples/mcp-memory/corpus-mcp-sequentialthinking.jsonl
```

mcpseal 0.3.0 shells out to `npm pack`; if your npm cache is not
writable, set `npm_config_cache` to a directory you own or the child npm
dies with EACCES and mcpseal reports the package as not found.
