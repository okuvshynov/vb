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

Implement a bencode message validator in C++17. The model reads input from stdin and exits 0 for valid / non-zero for invalid. Test suite: 55 cases covering strings, integers, lists, dictionaries, edge cases, and binary data.

**Prompt variants** (use `--prompt <name>`):
| Variant | File | Description |
|---|---|---|
| `prompt` (default) | `prompt.txt` | Original bencode spec; no mention of leading zeros on string lengths |
| `bijection` | `prompt-bijection.txt` | Adds canonical encoding / unique bijection requirement; model must infer leading-zero implications |
| `explicit-leading-zero` | `prompt-explicit-leading-zero.txt` | Explicitly states string lengths must not have leading zeros |

## Adding tasks

Create a directory under `tasks/` with:
- `prompt.txt` — default task specification (pure spec, no tool instructions)
- `prompt-{variant}.txt` — optional alternative prompt variants
- `tests.jsonl` — test cases, one JSON object per line

Each line in `tests.jsonl` has the following fields:
- `input` (string): plain text input piped to the validator via stdin
- `input_hex` (string): hex-encoded input — mutually exclusive with `input`
- `expected`: `"valid"` or `"invalid"`
- `label`: human-readable test description
