#!/usr/bin/env bash
VALIDATOR="${1:?Usage: test.sh <validator-binary>}"
TESTS_DIR="$(cd "$(dirname "$0")" && pwd)/tests"
VALID_PASS=0
VALID_FAIL=0
INVALID_PASS=0
INVALID_FAIL=0

# Valid tests — expect exit 0
for f in $(find "$TESTS_DIR/valid" -name '*.toml' | sort); do
    "$VALIDATOR" < "$f" 2>/dev/null && rc=0 || rc=$?
    if [ "$rc" -eq 0 ]; then
        VALID_PASS=$((VALID_PASS + 1))
    else
        name="${f#$TESTS_DIR/}"
        echo "FAIL: $name (exit=$rc, expected valid)"
        VALID_FAIL=$((VALID_FAIL + 1))
    fi
done

# Invalid tests — expect non-zero exit
for f in $(find "$TESTS_DIR/invalid" -name '*.toml' | sort); do
    "$VALIDATOR" < "$f" 2>/dev/null && rc=0 || rc=$?
    if [ "$rc" -ne 0 ]; then
        INVALID_PASS=$((INVALID_PASS + 1))
    else
        name="${f#$TESTS_DIR/}"
        echo "FAIL: $name (exit=$rc, expected invalid)"
        INVALID_FAIL=$((INVALID_FAIL + 1))
    fi
done

PASS=$((VALID_PASS + INVALID_PASS))
FAIL=$((VALID_FAIL + INVALID_FAIL))
total=$((PASS + FAIL))
echo "MATRIX: TP=$VALID_PASS FN=$VALID_FAIL FP=$INVALID_FAIL TN=$INVALID_PASS"
if [ "$FAIL" -eq 0 ]; then
    echo "ALL $total TESTS PASSED"
else
    echo "$FAIL/$total TESTS FAILED"
    exit 1
fi
