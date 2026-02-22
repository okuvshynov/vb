#!/usr/bin/env python3
"""Build the libtorrent-based validator and run the bencode test suite against it."""

import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(SCRIPT_DIR, "build")
VALIDATOR = os.path.join(BUILD_DIR, "validator")
TESTS_FILE = os.path.join(SCRIPT_DIR, "..", "tasks", "bencode-cpp-v0", "tests.jsonl")


def build():
    os.makedirs(BUILD_DIR, exist_ok=True)
    print("=== Configuring ===")
    subprocess.run(
        ["cmake", "..",
         "-DCMAKE_BUILD_TYPE=Release",
         "-DBOOST_ROOT=/opt/homebrew/opt/boost"],
        cwd=BUILD_DIR, check=True,
    )
    print("\n=== Building ===")
    subprocess.run(
        ["cmake", "--build", ".", "--parallel"],
        cwd=BUILD_DIR, check=True,
    )
    print()


def load_tests():
    tests = []
    with open(TESTS_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            t = json.loads(line)
            if "input_hex" in t:
                t["input_bytes"] = bytes.fromhex(t["input_hex"])
            else:
                t["input_bytes"] = t["input"].encode("utf-8")
            tests.append(t)
    return tests


def run_tests(tests):
    tp = tn = fp = fn = 0
    discrepancies = []

    for t in tests:
        tid = t.get("id", "?")
        label = t["label"]
        expected = t["expected"]
        data = t["input_bytes"]

        try:
            result = subprocess.run(
                [VALIDATOR],
                input=data, capture_output=True, timeout=5,
            )
            actual = "valid" if result.returncode == 0 else "invalid"
        except subprocess.TimeoutExpired:
            actual = "invalid"

        if actual == expected:
            if expected == "valid":
                tp += 1
            else:
                tn += 1
        else:
            if actual == "valid":
                fp += 1
            else:
                fn += 1
            discrepancies.append((tid, label, data, expected, actual))

    total = tp + tn + fp + fn
    passed = tp + tn
    print(f"Results: {passed}/{total} passed")
    print(f"  TP={tp}  TN={tn}  FP={fp}  FN={fn}")

    if discrepancies:
        print(f"\n{len(discrepancies)} discrepancy(ies):")
        for tid, label, data, expected, actual in discrepancies:
            display = data.hex() if not data.isascii() else data.decode("ascii", errors="replace")
            print(f"  {tid}: [{label}] input={display!r} expected={expected} actual={actual}")
    else:
        print("\nAll tests match.")


def main():
    build()
    tests = load_tests()
    run_tests(tests)


if __name__ == "__main__":
    main()
