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

```bash
python validation_bench.py --task bencode-cpp-v0 --n-repeats 10
```

| Argument | Default | Description |
|---|---|---|
| `--task` | required | Task name (directory under `tasks/`) |
| `--n-repeats` | `1` | Number of independent runs |
| `--api-base` | `http://localhost:8080/v1` | OpenAI-compatible endpoint |
| `--api-key` | `"no-key"` | API key |
| `--model` | auto-detect | Model name; empty = query `/v1/models` |
| `--temperature` | `1.0` | Sampling temperature |
| `--max-turns` | `10` | Max conversation turns per repeat |

## Tasks

### `bencode-cpp-v0`

Implement a bencode message validator in C++17. The model reads input from stdin and exits 0 for valid / non-zero for invalid. Test suite: 55 cases covering strings, integers, lists, dictionaries, edge cases, and binary data.

## Adding tasks

Create a directory under `tasks/` with:
- `prompt.txt` — task specification (pure spec, no tool instructions)
- `test.sh` — test script that takes the compiled binary path as `$1`

Test script should print `ALL N TESTS PASSED` on success or `F/N TESTS FAILED` on failure.
