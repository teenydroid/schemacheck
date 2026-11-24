#!/usr/bin/env python3
"""schemacheck - grade a tool-call schema by the bad calls it lets through.

Usage: schemacheck.py SCHEMA.json CORPUS.jsonl [--quiet]
  SCHEMA.json  a JSON Schema (draft-07 subset, no external refs)
  CORPUS.jsonl one bad tool-call per line (JSON objects meant to be rejected)

Exit codes: 0 = schema rejected every bad call; 1 = schema let bad calls
through (count printed); 2 = usage/IO error.

A schema is only as good as the invalid calls it refuses. schemacheck runs a
corpus of known-bad calls against a schema's validator and reports how many
slipped through. Strict schemas reject 10/10; the loose ones agents actually
ship often reject 0/10.
"""

import argparse
import json
import sys
from pathlib import Path

MAX_CORPUS = 1000          # hard cap: at most 1000 bad calls per run
MAX_LINE_BYTES = 1 << 20   # 1 MiB per corpus line


# ---------------------------------------------------------------------------
# Minimal draft-07 subset validator. Deliberately hand-rolled: no third-party
# dependency, and every clause here is one agents actually use on tool calls.
# ---------------------------------------------------------------------------

class SchemaError(Exception):
    pass


def validate(schema, value, path="$"):
    """Return a list of human-readable violations (empty = valid)."""
    if not isinstance(schema, dict):
        raise SchemaError(f"schema at {path} is not an object")
    errs = []

    if "type" in schema:
        t = schema["type"]
        if not _type_ok(t, value):
            errs.append(f"{path}: expected type {t}, got {_type_name(value)}")
            return errs  # further checks make no sense on a type mismatch

    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: value not in enum")

    if "const" in schema and value != schema["const"]:
        errs.append(f"{path}: value != const")

    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errs.append(f"{path}: missing required property {req!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errs.append(f"{path}: additional property {key!r} not allowed")
        for key, sub in props.items():
            if key in value:
                errs.extend(validate(sub, value[key], f"{path}.{key}"))
        if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
            for key, subval in value.items():
                if key not in props:
                    errs.extend(validate(schema["additionalProperties"], subval,
                                         f"{path}.{key}"))
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            errs.append(f"{path}: fewer than {schema['minProperties']} properties")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            errs.append(f"{path}: more than {schema['maxProperties']} properties")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: more than {schema['maxItems']} items")
        if "uniqueItems" in schema and schema["uniqueItems"]:
            seen = [json.dumps(v, sort_keys=True) for v in value]
            if len(set(seen)) != len(seen):
                errs.append(f"{path}: items not unique")
        if "items" in schema:
            if isinstance(schema["items"], dict):
                for i, item in enumerate(value):
                    errs.extend(validate(schema["items"], item, f"{path}[{i}]"))
            elif isinstance(schema["items"], list):
                for i, (sub, item) in enumerate(zip(schema["items"], value)):
                    errs.extend(validate(sub, item, f"{path}[{i}]"))

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: longer than maxLength {schema['maxLength']}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: above maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errs.append(f"{path}: <= exclusiveMinimum {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errs.append(f"{path}: >= exclusiveMaximum {schema['exclusiveMaximum']}")

    for sub in schema.get("allOf", []):
        errs.extend(validate(sub, value, path))
    if "anyOf" in schema:
        for sub in schema["anyOf"]:
            if not validate(sub, value, path):
                return errs
        errs.append(f"{path}: matched none of anyOf")
    if "oneOf" in schema:
        matches = sum(1 for sub in schema["oneOf"] if not validate(sub, value, path))
        if matches != 1:
            errs.append(f"{path}: matched {matches} of oneOf (need exactly 1)")
    if "not" in schema and not validate(schema["not"], value, path):
        errs.append(f"{path}: matched a forbidden (not) schema")

    return errs


def _type_name(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _type_ok(t, value):
    if isinstance(t, list):
        return any(_type_ok(one, value) for one in t)
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    raise SchemaError(f"unknown type {t!r}")


# ---------------------------------------------------------------------------
# Corpus runner
# ---------------------------------------------------------------------------

def load_corpus(path):
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"corpus not found: {path}")
    calls, lineno = [], 0
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            lineno += 1
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if len(line.encode("utf-8", errors="replace")) > MAX_LINE_BYTES:
                raise ValueError(f"corpus line {lineno} over {MAX_LINE_BYTES} bytes")
            calls.append((lineno, json.loads(line)))
            if len(calls) >= MAX_CORPUS:
                raise ValueError(f"corpus exceeds {MAX_CORPUS} calls; split it")
    return calls


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("schema", help="JSON Schema file")
    ap.add_argument("corpus", help="JSONL file of bad calls (one JSON per line)")
    ap.add_argument("--quiet", action="store_true", help="only print the score")
    args = ap.parse_args(argv)

    try:
        schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"schemacheck: cannot read schema: {exc}", file=sys.stderr)
        return 2
    try:
        calls = load_corpus(args.corpus)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"schemacheck: cannot read corpus: {exc}", file=sys.stderr)
        return 2
    if not calls:
        print("schemacheck: corpus is empty", file=sys.stderr)
        return 2

    leaked = 0
    for lineno, call in calls:
        try:
            errs = validate(schema, call)
        except SchemaError as exc:
            print(f"schemacheck: bad schema: {exc}", file=sys.stderr)
            return 2
        if not errs:
            leaked += 1
            if not args.quiet:
                print(f"LEAK line {lineno}: {json.dumps(call)[:200]}")

    total = len(calls)
    if args.quiet:
        print(f"{total - leaked}/{total}")
    else:
        print(f"rejected {total - leaked}/{total} bad calls; {leaked} leaked")
    return 0 if leaked == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
