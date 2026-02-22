# validation_bench

AI coding benchmark harness that evaluates models on code generation tasks via OpenAI-compatible API with tool calling.

## How it works

1. Sends a task specification to a model via OpenAI-compatible API
2. Model submits solutions via a `submit(source_code)` tool
3. Harness compiles and tests each submission, returning results (including failure details)
4. Model can iterate — fix bugs and resubmit within a configurable turn limit
5. Reports per-repeat and aggregate scoring

## Setup

```bash
pip install -r requirements.txt
```

## Usage

CLI arguments:

| Argument | Default | Description |
|---|---|---|
| `--task` | required | Task name (directory under `tasks/`) |
| `--n-repeats` | `1` | Number of independent runs |
| `--api-base` | `http://localhost:8080/v1` | OpenAI-compatible endpoint |
| `--api-key` | `"no-key"` | API key |
| `--model` | auto-detect | Model name; empty = query `/v1/models` |
| `--temperature` | server default | Sampling temperature (omit to let the server decide) |
| `--max-turns` | `10` | Max conversation turns per repeat |
| `--prompt` | `prompt` | Prompt variant name (see below) |

### Bencode

```bash
python validation_bench.py --task bencode-cpp-v0 --n-repeats 10
python validation_bench.py --task bencode-cpp-v0 --prompt bijection --n-repeats 10
python validation_bench.py --task bencode-cpp-v0 --prompt explicit-leading-zero --n-repeats 10
```

## Tasks

### `bencode-cpp-v0`

Implement a bencode message validator in C++17. The model reads input from stdin and exits 0 for valid / non-zero for invalid. Test suite: 71 cases covering strings, integers, lists, dictionaries, edge cases, and binary data.

**Prompt variants** (use `--prompt <name>`):
| Variant | File | Description |
|---|---|---|
| `prompt` (default) | `prompt.txt` | Original bencode spec; no mention of leading zeros on string lengths |
| `bijection` | `prompt-bijection.txt` | Adds canonical encoding / unique bijection requirement; model must infer leading-zero implications |
| `explicit-leading-zero` | `prompt-explicit-leading-zero.txt` | Explicitly states string lengths must not have leading zeros |
| `strict` | `prompt-strict.txt` | Binary encoding, canonical form, exactly-one-value, raw byte strings — all gaps coverable by deduction |

## Adding tasks

Create a directory under `tasks/` with:
- `prompt.txt` — default task prompt (includes role instructions, tool usage, and spec)
- `prompt-{variant}.txt` — optional alternative prompt variants
- `tests.jsonl` — test cases, one JSON object per line

Each line in `tests.jsonl` has the following fields:
- `id` (string): stable case identifier (e.g., `s01`, `i14`, `d07`)
- `input` (string): plain text input piped to the validator via stdin
- `input_hex` (string): hex-encoded input — mutually exclusive with `input`, used for binary data
- `expected`: `"valid"` or `"invalid"`
- `label`: human-readable test description

## Reference validator

`reference/` contains a reference bencode validator built on [libtorrent](https://github.com/arvidn/libtorrent)'s `bdecode()` — the canonical C++ bencode implementation. It verifies our test expectations against a battle-tested implementation.

```bash
cd reference
python3 check_tests.py    # builds libtorrent + validator, runs all tests
```

**Prerequisites:** Boost (`brew install boost`), CMake, clang++. libtorrent source expected at `../3rd/libtorrent` (with `deps/try_signal` submodule initialized).

**Current results:** 68/71 match, 3 known discrepancies:
- `i08` (FN): libtorrent rejects integers exceeding int64 range — implementation limit, not spec violation
- `i09` (FP): libtorrent misses negative zero (`i-0e`) — `has_soft_error()` bug
- `i12` (FP): libtorrent misses negative leading zero (`i-03e`) — same bug

## Developing test cases

When adding new test cases to `tests.jsonl`:

### 1. Identify gaps

Find untested corner cases by:
- **Reviewing LLM-generated solutions** that pass all existing tests. Look for bugs the tests don't catch (e.g., `getline` stripping newlines, comparing raw bencode keys instead of key bytes).
- **Studying reference implementations** — libtorrent's `test_bdecode.cpp` has ~78 test scenarios. Cross-reference against our suite.
- **Analyzing the spec** for ambiguities (trailing data, key ordering edge cases, integer boundaries).

### 2. Add cases to tests.jsonl

Assign an ID following the convention: `s` (string), `i` (integer), `l` (list), `d` (dict), `t` (top-level), followed by a two-digit number. Use `input_hex` for binary content (null bytes, newlines).

```json
{"id": "s14", "input_hex": "333a610a62", "expected": "valid", "label": "string: binary content (newline)"}
```

### 3. Verify against reference

Run `reference/check_tests.py` and confirm new cases either match or fall into a known discrepancy. Any NEW discrepancy means either the test expectation is wrong or a new libtorrent gap was found — investigate before merging.

### 4. Confirm bug-catching value

If the test was inspired by a buggy solution, compile that solution and verify it actually fails on the new test:

```bash
clang++ -std=c++17 -O2 -o /tmp/buggy solution.cpp
echo -n 'input' | /tmp/buggy && echo VALID || echo INVALID
```
