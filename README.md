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
| `--timeout` | `600` | API request timeout in seconds |
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

### `minbencode-cpp-v0`

Implement a "minified bencode" validator in C++17 — a subset of bencode supporting only **strings and lists** (no integers, no dictionaries). The model reads input from stdin and exits 0 for valid / non-zero for invalid. Test suite: 33 cases covering strings, lists, top-level structure, binary data, and rejection of unsupported types.

### `minbencode-c-v0`

Same spec and test suite as `minbencode-cpp-v0`, but targeting C17 instead of C++17. Compiled with `clang -std=c17 -O2`.

### `miniformat-c-v0`

Isomorphic to `minbencode-c-v0` but with different syntax: `#` instead of `:` as string separator, `s`/`;` instead of `l`/`e` for sequences, and "sequence" terminology instead of "list". Tests whether models solve the actual parsing problem vs pattern-matching a known format (bencode). Same 33-test structure, compiled with `clang -std=c17 -O2`.

**Prompt variants** (use `--prompt <name>`):
| Variant | File | Description |
|---|---|---|
| `prompt` (default) | `prompt.txt` | Original bencode spec; no mention of leading zeros on string lengths |
| `bijection` | `prompt-bijection.txt` | Adds canonical encoding / unique bijection requirement; model must infer leading-zero implications |
| `explicit-leading-zero` | `prompt-explicit-leading-zero.txt` | Explicitly states string lengths must not have leading zeros |
| `strict` | `prompt-strict.txt` | Binary encoding, canonical form, exactly-one-value, raw byte strings — all gaps coverable by deduction |

### `miniformat-c-v1`

Integers + sequences variant of the miniformat family. Integers use `n`/`$` delimiters with optional minus sign; sequences use `s`/`;`. The prompt describes the syntax but relies on the "unique canonical representation" preamble to implicitly prohibit leading zeros and negative zero — models must deduce these canonicality constraints. Test suite: 43 cases covering integer validity/canonicality, sequences, top-level structure, and rejection of foreign formats.

### `miniformat-c-v2`

Full miniformat: strings + integers + sequences. Combines v0 (strings + sequences) and v1 (integers + sequences) into a single format with three value types. The prompt describes all three types and relies on "unique canonical representation" to implicitly prohibit leading zeros on both string lengths and integer values, plus negative zero. Test suite: 67 cases covering strings, integers, mixed-type sequences, cross-type top-level errors, and rejection of foreign formats.

### `toml-1.0-cpp`

TOML v1.0.0 file validation in C++17. The prompt embeds the full TOML 1.0 specification with version-appropriate rules: no `\e` or `\xHH` escape sequences, seconds required in datetime values, and inline tables restricted to single lines without trailing commas. Test data: 678 cases (205 valid, 473 invalid) sourced from [toml-test](https://github.com/toml-lang/toml-test) `files-toml-1.0.0` (MIT licensed). Validated against Python's `tomllib` with 678/678 match (0 discrepancies).

### `toml-1.1-cpp`

TOML v1.1.0 file validation in C++17. Same prompt as `toml-cpp-v0` (already targets 1.1). Test data: 680 cases (214 valid, 466 invalid) sourced from [toml-test](https://github.com/toml-lang/toml-test) `files-toml-1.1.0` — no contradictions between valid/invalid expectations. Tests use `input_file` to reference `.toml` files under `tests/valid/` and `tests/invalid/`.

### `toml-combined-cpp`

Combined TOML v1.0+1.1 file validation in C++17. The model must write a **single validator** that takes a version argument (`./validator 1.0 < input.toml` or `./validator 1.1 < input.toml`) and correctly handles version-specific behavior. The prompt contains the full TOML 1.0 spec plus a diff showing 1.1 changes. Test data: 745 unique test files (union of 1.0 and 1.1 file lists) run twice each (once per version) for 1490 total evaluations. Of these, 18 files (36 evaluations) are "discrimination tests" where the expected result differs between versions — testing inline table newlines/trailing commas, `\xHH`/`\e` escapes, optional seconds in datetimes, and bare CR handling.

### `toml-cpp-v0` (legacy)

Original TOML task using the union of all toml-test files (745 cases). Kept for historical result references. Superseded by `toml-1.0-cpp` and `toml-1.1-cpp` which use the clean per-version file lists and have no contradictions.

### `der-int-c-v0`

Implement a validator for DER-encoded ASN.1 INTEGER values in C17. The model reads raw bytes from stdin and exits 0 for valid / non-zero for invalid. Test suite: 37 cases covering two's complement boundaries, sign-bit padding, minimality violations, length encoding, and structural errors.

**Prompt variants** (use `--prompt <name>`):
| Variant | File | Description |
|---|---|---|
| `prompt` (default) | `prompt.txt` | Terse X.690 minimality wording; model must deduce padding implications |
| `examples` | `prompt-examples.txt` | Adds concrete encoding examples |
| `explicit` | `prompt-explicit.txt` | Full explanation of sign-bit padding with positive and negative examples |
| `terse-length` | `prompt-terse-length.txt` | Implicit length minimality: describes format only, unified "fewest bytes" rule for both length and value |

## Adding tasks

Create a directory under `tasks/` with:
- `prompt.txt` — default task prompt (includes role instructions, tool usage, and spec)
- `prompt-{variant}.txt` — optional alternative prompt variants
- `tests.jsonl` — test cases, one JSON object per line

Each line in `tests.jsonl` has the following fields:
- `id` (string): stable case identifier (e.g., `s01`, `i14`, `d07`)
- `input` (string): plain text input piped to the validator via stdin
- `input_hex` (string): hex-encoded input — mutually exclusive with `input`, used for binary data
- `input_file` (string): path to input file relative to task directory — mutually exclusive with `input`/`input_hex`, used for large or structured test data (e.g., TOML files)
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
