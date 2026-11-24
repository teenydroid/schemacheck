#!/usr/bin/env python3
"""Tests for schemacheck. Bounded per the fuzz-incident rule:
resource limits on this process, no unbounded input, integer caps everywhere.

Run:  (ulimit -v 1000000; timeout 60 python3 -m unittest -v test_schemacheck)
"""

import json
import os
import resource
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE / "schemacheck.py"
FIXTURES = HERE / "fixtures"

# Bound ourselves first: 1 GB address space (json + interpreter headroom).
resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))

MAX_CHILD_OUTPUT = 200_000  # bytes we will ever read back from a child


def run_tool(*argv, timeout=20):
    """Run schemacheck in a bounded child: RLIMIT_AS + timeout + capped output."""
    out_path = Path(tempfile.mkdtemp(dir=HERE)) / "out.txt"
    limit = "import resource,sys; resource.setrlimit(resource.RLIMIT_AS,(500_000_000,)*2); sys.argv=%r" % (
        [str(TOOL)] + [str(a) for a in argv],)
    code = limit + "; exec(open(sys.argv[0]).read())"
    with out_path.open("wb") as out:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            stdout=out, stderr=subprocess.DEVNULL, timeout=timeout,
        )
    data = out_path.read_bytes()[:MAX_CHILD_OUTPUT]
    return proc.returncode, data.decode("utf-8", "replace")


def write(tmp, name, text):
    p = Path(tmp) / name
    p.write_text(text, encoding="utf-8")
    return p


class TestValidator(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(HERE))
        import schemacheck  # noqa
        self.sc = sys.modules["schemacheck"]

    def test_type_rejects_bool_for_integer(self):
        errs = self.sc.validate({"type": "integer"}, True)
        self.assertTrue(errs)

    def test_required_missing(self):
        errs = self.sc.validate({"required": ["a"]}, {})
        self.assertTrue(any("missing required" in e for e in errs))

    def test_additional_properties_false(self):
        errs = self.sc.validate({"properties": {"a": {}},
                                 "additionalProperties": False}, {"b": 1})
        self.assertTrue(any("additional property" in e for e in errs))

    def test_enum(self):
        errs = self.sc.validate({"enum": ["x", "y"]}, "z")
        self.assertTrue(errs)
        self.assertFalse(self.sc.validate({"enum": ["x", "y"]}, "x"))

    def test_oneOf_ambiguity_rejected(self):
        errs = self.sc.validate({"oneOf": [{"type": "integer"},
                                           {"type": "integer"}]}, 3)
        self.assertTrue(any("oneOf" in e for e in errs))

    def test_unique_items(self):
        errs = self.sc.validate({"uniqueItems": True}, [1, 1])
        self.assertTrue(any("unique" in e for e in errs))

    def test_min_max_integer(self):
        errs = self.sc.validate({"type": "integer", "minimum": 1, "maximum": 7}, 9)
        self.assertTrue(any("maximum" in e for e in errs))

    def test_string_bounds(self):
        errs = self.sc.validate({"type": "string", "minLength": 2}, "x")
        self.assertTrue(any("minLength" in e for e in errs))

    def test_nested_path_reported(self):
        errs = self.sc.validate({"properties": {"c": {"properties": {"e": {"type": "string"}}}}},
                                {"c": {"e": 1}})
        self.assertIn("$.c.e", errs[0])

    def test_empty_schema_allows_anything(self):
        self.assertEqual(self.sc.validate({}, {"any": "thing"}), [])


class TestCorpusRunner(unittest.TestCase):
    def test_strict_schema_rejects_all_ten(self):
        rc, out = run_tool(FIXTURES / "schema-strict.json",
                           FIXTURES / "bad-calls.jsonl")
        self.assertEqual(rc, 0, out)
        self.assertIn("rejected 10/10", out)

    def test_loose_schema_leaks(self):
        loose = write(HERE, "schema-loose.json", json.dumps({"type": "object"}))
        try:
            rc, out = run_tool(loose, FIXTURES / "bad-calls.jsonl")
            self.assertEqual(rc, 1, out)
            self.assertIn("leaked", out)
            self.assertIn("10 leaked", out)
        finally:
            os.unlink(loose)

    def test_relaxed_schema_leaks_exactly_two(self):
        # drop required AND additionalProperties at the top level: corpus
        # lines 1 ({"op": ...}) and 8 ({"extra": true}) can slip; every other
        # line still violates a clause (nested contact keeps its own guard).
        schema = json.loads((FIXTURES / "schema-strict.json").read_text())
        schema.pop("required")
        schema.pop("additionalProperties")
        loose = write(HERE, "schema-no-req.json", json.dumps(schema))
        try:
            rc, out = run_tool(loose, FIXTURES / "bad-calls.jsonl")
            self.assertEqual(rc, 1, out)
            self.assertIn("2 leaked", out)
            self.assertIn("LEAK line 1", out)
            self.assertIn("LEAK line 8", out)
        finally:
            os.unlink(loose)

    def test_empty_corpus_is_error(self):
        empty = write(HERE, "empty.jsonl", "")
        try:
            rc, out = run_tool(FIXTURES / "schema-strict.json", empty)
            self.assertEqual(rc, 2, out)
        finally:
            os.unlink(empty)

    def test_cap_on_corpus_size(self):
        big = write(HERE, "big.jsonl",
                    "\n".join('{"city":"x"}' for _ in range(1001)))
        try:
            rc, out = run_tool(FIXTURES / "schema-strict.json", big)
            self.assertEqual(rc, 2, out)
        finally:
            os.unlink(big)

    def test_quiet_mode_score_only(self):
        rc, out = run_tool(FIXTURES / "schema-strict.json",
                           FIXTURES / "bad-calls.jsonl", "--quiet")
        self.assertEqual(rc, 0, out)
        self.assertEqual(out.strip(), "10/10")

    def test_bad_json_line_is_error(self):
        bad = write(HERE, "bad.jsonl", "{not json}\n")
        try:
            rc, out = run_tool(FIXTURES / "schema-strict.json", bad)
            self.assertEqual(rc, 2, out)
        finally:
            os.unlink(bad)


if __name__ == "__main__":
    unittest.main()
