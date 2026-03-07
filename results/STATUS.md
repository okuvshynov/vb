# Evaluation Status

Coverage matrix for toml-1.0-cpp (678 tests) and toml-1.1-cpp (680 tests).

Target: 10 attempts per model per task.

| Model                | toml-1.0-cpp | toml-1.1-cpp |
|----------------------|--------------|--------------|
| Claude Opus 4.6      | 5/10         | 5/10         |
| Claude Sonnet 4.0    | 5/10         | --           |
| Claude Sonnet 4.6    | --           | --           |
| Devstral             | 10/10        | 10/10        |
| GLM-5                | 10/10        | 6/10         |
| GPT Codex 5.3 (high) | 5/10        | --           |
| GPT Codex 5.3 (low)  | 7/10        | --           |
| Kimi K2.5            | 10/10        | 10/10        |
| Qwen3.5-122B Q8      | 10/10        | --           |

**Legend:** `N/10` = N attempts completed, `--` = not started

## Quick reference

```
python validation_bench.py --task toml-1.0-cpp --model <model> --max-turns 5 --n-attempts 10
python validation_bench.py --task toml-1.1-cpp --model <model> --max-turns 5 --n-attempts 10
```

## Priority

1. Fill toml-1.0-cpp gaps (Claude Sonnet 4.6, top up partial runs to 10)
2. Run all models on toml-1.1-cpp for cross-version comparison
