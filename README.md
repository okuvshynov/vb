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
./setup.sh
```

`setup.sh` clones [toml-test](https://github.com/toml-lang/toml-test) at a pinned commit into `.cache/toml-test`, generates `tests.jsonl` for each task from the upstream file lists, and symlinks task test data into the cache. Run it once after cloning the repo, or again after bumping the pinned commit.

## Usage

### Examples

Run against OpenAI API (uses `OPENAI_API_KEY` env var):

```bash
python validation_bench.py --task toml-1.0-cpp --model openai/gpt-5.3-codex --n-attempts 5
```

With reasoning effort:

```bash
python validation_bench.py --task toml-1.0-cpp --model openai/gpt-5.3-codex --reasoning-effort low --n-attempts 5
```

Run against Anthropic API (uses `ANTHROPIC_API_KEY` env var):

```bash
python validation_bench.py --task toml-1.0-cpp --model anthropic/claude-sonnet-4-20250514 --n-attempts 5
```

Run against a local OpenAI-compatible server (e.g. llama.cpp):

```bash
python validation_bench.py --task toml-1.0-cpp --api-base http://localhost:8080/v1 --n-attempts 5
```

### CLI arguments

| Argument | Default | Description |
|---|---|---|
| `--task` | required | Task name (directory under `tasks/`) |
| `--n-attempts` | `1` | Number of independent attempts |
| `--api-base` | `http://localhost:8080/v1` | OpenAI-compatible endpoint |
| `--api-key` | env var | API key (or set `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`) |
| `--model` | auto-detect | Model name in LiteLLM format (e.g. `openai/gpt-5.3-codex`, `anthropic/claude-sonnet-4-20250514`); empty = auto-detect from local server |
| `--temperature` | server default | Sampling temperature |
| `--reasoning-effort` | none | Reasoning effort: `low`, `medium`, or `high` |
| `--max-tokens` | `32768` | Max tokens per response |
| `--max-turns` | `10` | Max conversation turns per attempt |
| `--timeout` | `600` | API request timeout in seconds |
| `--slug` | auto-derived | Model slug for results directory name |
| `--results-dir` | `results/` | Base results directory |
| `--data-dir` | `~/.vb-data` | Base data directory for attempts (env: `VB_DATA_DIR`) |

## Tasks

### `toml-1.0-cpp`

TOML v1.0.0 file validation in C++17. The prompt embeds the full TOML 1.0 specification with version-appropriate rules: no `\e` or `\xHH` escape sequences, seconds required in datetime values, and inline tables restricted to single lines without trailing commas. Test data: 678 cases (205 valid, 473 invalid) sourced from [toml-test](https://github.com/toml-lang/toml-test) `files-toml-1.0.0` (MIT licensed). Validated against Python's `tomllib` with 678/678 match (0 discrepancies).

### `toml-1.1-cpp`

TOML v1.1.0 file validation in C++17. Same prompt as `toml-cpp-v0` (already targets 1.1). Test data: 680 cases (214 valid, 466 invalid) sourced from [toml-test](https://github.com/toml-lang/toml-test) `files-toml-1.1.0` — no contradictions between valid/invalid expectations. Tests use `input_file` to reference `.toml` files under `tests/valid/` and `tests/invalid/`.

### `toml-1.0-cpp-nospec`

Same as `toml-1.0-cpp` (same test data, same compiler) but the prompt does **not** include the TOML specification. Tests the model's built-in knowledge of TOML v1.0.0 rather than instruction-following ability.

### `toml-1.1-cpp-nospec`

Same as `toml-1.1-cpp` (same test data, same compiler) but without the specification in the prompt. Tests model knowledge of TOML v1.1.0 — particularly interesting since 1.1 adds `\e`, `\xHH` escapes, optional seconds in datetimes, and multi-line inline tables, which models may not know about.

## Adding tasks

Create a directory under `tasks/` with:
- `prompt.txt` — task prompt (includes role instructions, tool usage, and spec)
- `tests.jsonl` — test cases, one JSON object per line

Each line in `tests.jsonl` has the following fields:
- `id` (string): stable case identifier (e.g., `s01`, `i14`, `d07`)
- `input_file` (string): path to input file relative to task directory, piped to the validator via stdin
- `expected`: `"valid"` or `"invalid"`
- `label`: human-readable test description

## Updating results

After running benchmarks, regenerate all summaries and charts:

```bash
./update_results.sh
```

This script:
1. Scans `results/<task>/<slug>/meta.json` to discover runs
2. Counts attempts via each run's `data_dir` (from `meta.json`)
3. Skips models with 0 attempts
4. Runs `analyze_runs.py --verbose` per task → `results/<task>/summary.txt`
5. Runs `plot_results.py` per task → `results/<task>/chart.png`
6. Runs `plot_comparison.py` → `results/comparison.png`

Model slugs are used as labels everywhere (summaries, charts, comparison).

To add a new model to the comparison chart's ordering/categories, edit `MODEL_CONFIG` in `plot_comparison.py`. Models not listed in `MODEL_CONFIG` still appear in per-task charts but are excluded from the comparison.
