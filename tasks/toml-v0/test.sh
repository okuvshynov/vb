#!/usr/bin/env bash
VALIDATOR="${1:?Usage: test.sh <validator-binary>}"
TESTS_DIR="$(cd "$(dirname "$0")" && pwd)/tests"
PASS=0
FAIL=0

# Valid tests — expect exit 0
for f in $(find "$TESTS_DIR/valid" -name '*.toml' | sort); do
    "$VALIDATOR" < "$f" 2>/dev/null && rc=0 || rc=$?
    if [ "$rc" -eq 0 ]; then
        PASS=$((PASS + 1))
    else
        name="${f#$TESTS_DIR/}"
        echo "FAIL: $name (exit=$rc, expected valid)"
        FAIL=$((FAIL + 1))
    fi
done

# Invalid tests — expect non-zero exit
for f in $(find "$TESTS_DIR/invalid" -name '*.toml' | sort); do
    "$VALIDATOR" < "$f" 2>/dev/null && rc=0 || rc=$?
    if [ "$rc" -ne 0 ]; then
        PASS=$((PASS + 1))
    else
        name="${f#$TESTS_DIR/}"
        echo "FAIL: $name (exit=$rc, expected invalid)"
        FAIL=$((FAIL + 1))
    fi
done

total=$((PASS + FAIL))
if [ "$FAIL" -eq 0 ]; then
    echo "ALL $total TESTS PASSED"
else
    echo "$FAIL/$total TESTS FAILED"
    exit 1
fi
