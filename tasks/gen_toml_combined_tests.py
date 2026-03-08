#!/usr/bin/env python3
"""Generate tests.jsonl for the combined TOML 1.0+1.1 task.

Usage:
    python gen_toml_combined_tests.py <test-source-dir> [-o tests.jsonl]

The test source directory should contain files-toml-1.0.0 and files-toml-1.1.0
file lists, plus the actual test files under valid/ and invalid/.

Each test gets two expected labels (expected_1.0 and expected_1.1). The harness
runs each test twice (once per version), for a total of ~1490 evaluations.
"""

import argparse
import json
import os
import sys
from pathlib import Path


# --- Discrimination sets: tests where expected differs between versions ---

# Files present only in 1.0 file list that are invalid in 1.0 but valid in 1.1
V10_ONLY_INVALID_V11_VALID = {
    "invalid/inline-table/linebreak-01",
    "invalid/inline-table/linebreak-02",
    "invalid/inline-table/linebreak-03",
    "invalid/inline-table/linebreak-04",
    "invalid/inline-table/trailing-comma",
    "invalid/datetime/no-secs",
    "invalid/local-datetime/no-secs",
    "invalid/local-time/no-secs",
    "invalid/string/basic-byte-escapes",
}

# Files present only in 1.1 file list that are valid in 1.1 but invalid in 1.0
V11_ONLY_VALID_V10_INVALID = {
    "valid/inline-table/newline",
    "valid/inline-table/newline-comment",
    "valid/string/escape-esc",
    "valid/string/hex-escape",
    "valid/datetime/no-seconds",
    "valid/spec-1.1.0/common-12",
    "valid/spec-1.1.0/common-47",
}

# Files present only in 1.1 file list that are invalid in 1.1 but valid in 1.0
# (1.1 is stricter on bare CR in multiline strings)
V11_ONLY_INVALID_V10_VALID = {
    "invalid/control/multi-cr",
    "invalid/control/rawmulti-cr",
}


def parse_file_list(path: str) -> dict[str, str]:
    """Parse a toml-test file list, return {test_id: expected} for .toml files."""
    tests = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or not line.endswith(".toml"):
                continue
            assert line.startswith("valid/") or line.startswith("invalid/"), f"unexpected: {line}"
            test_id = line.removesuffix(".toml")
            expected = "valid" if line.startswith("valid/") else "invalid"
            tests[test_id] = expected
    return tests


def generate_combined_tests(test_source_dir: str) -> list[dict]:
    base = Path(test_source_dir)
    v10 = parse_file_list(str(base / "files-toml-1.0.0"))
    v11 = parse_file_list(str(base / "files-toml-1.1.0"))

    all_ids = sorted(set(v10) | set(v11))
    tests = []

    for test_id in all_ids:
        in_v10 = test_id in v10
        in_v11 = test_id in v11

        if in_v10 and in_v11:
            # Shared: both expectations come directly from file lists
            expected_10 = v10[test_id]
            expected_11 = v11[test_id]
        elif in_v10 and not in_v11:
            # Only in 1.0 file list
            expected_10 = v10[test_id]
            if test_id in V10_ONLY_INVALID_V11_VALID:
                expected_11 = "valid"
            else:
                # General tests: same expectation for both versions
                expected_11 = expected_10
        else:
            # Only in 1.1 file list
            expected_11 = v11[test_id]
            if test_id in V11_ONLY_VALID_V10_INVALID:
                expected_10 = "invalid"
            elif test_id in V11_ONLY_INVALID_V10_VALID:
                expected_10 = "valid"
            else:
                # General tests: same expectation for both versions
                expected_10 = expected_11

        # Label: strip valid/ or invalid/ prefix from id
        label_path = test_id.split("/", 1)[1]

        tests.append({
            "id": test_id,
            "input_file": f"tests/{test_id}.toml",
            "expected_1.0": expected_10,
            "expected_1.1": expected_11,
            "label": label_path,
        })

    return tests


def main():
    parser = argparse.ArgumentParser(description="Generate combined TOML 1.0+1.1 tests.jsonl")
    parser.add_argument("test_source_dir", help="Path to toml-test/tests/ directory")
    parser.add_argument("-o", "--output", default="-", help="Output file (default: stdout)")
    args = parser.parse_args()

    tests = generate_combined_tests(args.test_source_dir)

    # Verify all input files exist
    missing = []
    for t in tests:
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
    if len(ids) != len(set(ids)):
        dupes = {tid for tid in ids if ids.count(tid) > 1}
        print(f"ERROR: duplicate test IDs: {dupes}", file=sys.stderr)
        sys.exit(1)

    if args.output == "-":
        for t in tests:
            print(json.dumps(t))
    else:
        with open(args.output, "w") as f:
            for t in tests:
                f.write(json.dumps(t) + "\n")

    # Summary stats
    total = len(tests)
    disc = sum(1 for t in tests if t["expected_1.0"] != t["expected_1.1"])
    print(f"Generated {total} tests ({total * 2} evaluations), {disc} discrimination tests", file=sys.stderr)


if __name__ == "__main__":
    main()
