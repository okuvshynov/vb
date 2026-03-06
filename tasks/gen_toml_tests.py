#!/usr/bin/env python3
"""Generate tests.jsonl from a toml-test file list.

Usage:
    python gen_toml_tests.py <file-list> <test-source-dir> [-o tests.jsonl]

The file list (e.g. files-toml-1.0.0) contains paths like:
    valid/array/array.toml
    valid/array/array.json
    invalid/string/bad-escape-01.toml

Only .toml files are kept. The expected result is derived from the path prefix
(valid/ or invalid/). Output format:
    {"id": "valid/array/array", "input_file": "tests/valid/array/array.toml", "expected": "valid", "label": "valid: array/array"}
"""

import argparse
import json
import os
import sys
from pathlib import Path


def generate_tests(file_list_path: str, test_source_dir: str) -> list[dict]:
    with open(file_list_path) as f:
        lines = [l.strip() for l in f if l.strip()]

    toml_files = sorted(l for l in lines if l.endswith(".toml"))

    tests = []
    for path in toml_files:
        # path looks like "valid/array/array.toml" or "invalid/string/bad-escape-01.toml"
        assert path.startswith("valid/") or path.startswith("invalid/"), f"unexpected path: {path}"
        expected = "valid" if path.startswith("valid/") else "invalid"
        test_id = path.removesuffix(".toml")
        # label: "valid: array/array" or "invalid: string/bad-escape-01"
        label_path = test_id.split("/", 1)[1]  # strip "valid/" or "invalid/" prefix
        label = f"{expected}: {label_path}"

        tests.append({
            "id": test_id,
            "input_file": f"tests/{path}",
            "expected": expected,
            "label": label,
        })

    return tests


def main():
    parser = argparse.ArgumentParser(description="Generate tests.jsonl from a toml-test file list")
    parser.add_argument("file_list", help="Path to file list (e.g. files-toml-1.0.0)")
    parser.add_argument("test_source_dir", help="Path to test source directory (for verification)")
    parser.add_argument("-o", "--output", default="-", help="Output file (default: stdout)")
    args = parser.parse_args()

    tests = generate_tests(args.file_list, args.test_source_dir)

    # Verify all input files exist relative to test_source_dir
    missing = []
    for t in tests:
        # input_file is like "tests/valid/foo.toml", source dir has "valid/foo.toml"
        rel_path = t["input_file"].removeprefix("tests/")
        full_path = os.path.join(args.test_source_dir, rel_path)
        if not os.path.exists(full_path):
            missing.append(full_path)

    if missing:
        print(f"ERROR: {len(missing)} test files not found:", file=sys.stderr)
        for p in missing[:10]:
            print(f"  {p}", file=sys.stderr)
        sys.exit(1)

    # Check no duplicate IDs
    ids = [t["id"] for t in tests]
    dupes = [tid for tid in ids if ids.count(tid) > 1]
    if dupes:
        print(f"ERROR: duplicate test IDs: {set(dupes)}", file=sys.stderr)
        sys.exit(1)

    if args.output == "-":
        for t in tests:
            print(json.dumps(t))
    else:
        with open(args.output, "w") as f:
            for t in tests:
                f.write(json.dumps(t) + "\n")

    valid_count = sum(1 for t in tests if t["expected"] == "valid")
    invalid_count = sum(1 for t in tests if t["expected"] == "invalid")
    print(f"Generated {len(tests)} tests ({valid_count} valid, {invalid_count} invalid)", file=sys.stderr)


if __name__ == "__main__":
    main()
