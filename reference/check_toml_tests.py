#!/usr/bin/env python3
"""Validate toml-cpp-v1 test expectations against Python's tomllib.

tomllib implements TOML v1.0.0, while our tests target v1.1.0.
Known v1.1.0 features that cause expected disagreements:
  - Newlines in inline tables
  - \\x hex escapes in strings
  - \\e (ESC) escape in strings
"""

import json
import os
import sys
import tomllib
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
TASK_DIR = SCRIPT_DIR.parent / "tasks" / "toml-cpp-v1"
TESTS_FILE = TASK_DIR / "tests.jsonl"

# Known v1.1.0 features that tomllib (v1.0.0) rejects
KNOWN_V11_IDS = {
    "valid/inline-table/newline",
    "valid/inline-table/newline-comment",
    "valid/string/escape-esc",
    "valid/string/hex-escape",
    "valid/spec-1.1.0/common-12",
    "valid/spec-1.1.0/common-47",
}


def load_tests():
    tests = []
    with open(TESTS_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            tests.append(json.loads(line))
    return tests


def run_tests(tests):
    tp = tn = fp = fn = 0
    discrepancies = []
    known_v11 = []

    for t in tests:
        tid = t["id"]
        label = t["label"]
        expected = t["expected"]
        filepath = TASK_DIR / t["input_file"]
        data = filepath.read_bytes()

        try:
            tomllib.loads(data.decode("utf-8"))
            actual = "valid"
        except Exception:
            actual = "invalid"

        if actual == expected:
            if expected == "valid":
                tp += 1
            else:
                tn += 1
        else:
            if tid in KNOWN_V11_IDS:
                known_v11.append((tid, label, expected, actual))
                # Count as agreement for reporting purposes
                if expected == "valid":
                    tp += 1
                else:
                    tn += 1
            else:
                if actual == "valid":
                    fp += 1
                else:
                    fn += 1
                discrepancies.append((tid, label, expected, actual))

    total = tp + tn + fp + fn
    passed = tp + tn
    print(f"Results: {passed}/{total} match ({fp} FP, {fn} FN)")

    if known_v11:
        print(f"\n{len(known_v11)} known TOML v1.1.0 disagreement(s) (tomllib is v1.0.0):")
        for tid, label, expected, actual in known_v11:
            print(f"  {tid}: [{label}] expected={expected} tomllib={actual}")

    if discrepancies:
        print(f"\n{len(discrepancies)} UNEXPECTED discrepancy(ies):")
        for tid, label, expected, actual in discrepancies:
            print(f"  {tid}: [{label}] expected={expected} tomllib={actual}")
        return False
    else:
        print("\nNo unexpected discrepancies.")
        return True


def main():
    tests = load_tests()
    print(f"Loaded {len(tests)} test cases from {TESTS_FILE.relative_to(SCRIPT_DIR.parent)}")
    ok = run_tests(tests)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
