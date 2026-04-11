#!/usr/bin/env python3
"""AI Coding Benchmark Harness — evaluates models on code generation tasks."""

import argparse
import datetime
import json
import os
import math
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import warnings
from dataclasses import dataclass
from pathlib import Path

import litellm

litellm.drop_params = True

# Suppress Pydantic serialization warnings from LiteLLM's response types
# not exactly matching OpenAI's schemas (harmless type mismatches).
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")


@dataclass
class ConfusionMatrix:
    tp: int = 0  # valid correctly accepted
    fn: int = 0  # valid incorrectly rejected
    fp: int = 0  # invalid incorrectly accepted
    tn: int = 0  # invalid correctly rejected

    @property
    def passed(self) -> int:
        return self.tp + self.tn

    @property
    def total(self) -> int:
        return self.tp + self.fn + self.fp + self.tn

    @property
    def mcc(self) -> float:
        """Matthews Correlation Coefficient (phi coefficient)."""
        denom_sq = ((self.tp + self.fp) * (self.tp + self.fn)
                    * (self.tn + self.fp) * (self.tn + self.fn))
        if denom_sq == 0:
            return 0.0
        return (self.tp * self.tn - self.fp * self.fn) / math.sqrt(denom_sq)


@dataclass
class TestResult:
    compiled: bool
    compiler_output: str
    test_output: str
    matrix: ConfusionMatrix


@dataclass
class Submission:
    turn: int
    matrix: ConfusionMatrix | None = None  # None for failed submissions
    error: str | None = None  # e.g. "compile_error", "compile_timeout"


@dataclass
class AttemptResult:
    attempt_index: int
    timestamp: str  # ISO 8601, recorded when attempt completes
    elapsed_seconds: float
    submissions: list[Submission]


@dataclass
class InfraFailure:
    timestamp: str       # ISO 8601
    turn: int            # which turn failed
    error_type: str      # "api_error", "timeout", etc.
    error_message: str


def _log(msg: str):
    print(msg, flush=True)


SUBMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit",
        "description": "Submit source code for compilation and testing.",
        "parameters": {
            "type": "object",
            "properties": {
                "source_code": {
                    "type": "string",
                    "description": "Complete source code to compile and test.",
                }
            },
            "required": ["source_code"],
        },
    },
}


def load_tests(tests_file: Path) -> list[dict]:
    """Load test cases from JSONL file."""
    tests = []
    with open(tests_file) as f:
        for line in f:
            line = line.strip()
            if line:
                tests.append(json.loads(line))
    return tests


def run_tests(binary: Path, tests: list[dict], task_dir: Path) -> tuple[str, ConfusionMatrix]:
    """Run all test cases against the binary, return (output_text, matrix)."""
    matrix = ConfusionMatrix()
    lines = []

    for t in tests:
        input_data = (task_dir / t["input_file"]).read_bytes()

        tid = t.get("id", "?")
        label = t["label"]
        expected = t["expected"]

        try:
            proc = subprocess.run(
                [str(binary)], input=input_data,
                capture_output=True, timeout=5,
            )
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            rc = -1

        passed = (expected == "valid" and rc == 0) or (expected == "invalid" and rc != 0)
        if passed:
            if expected == "valid":
                matrix.tp += 1
            else:
                matrix.tn += 1
        else:
            if expected == "valid":
                matrix.fn += 1
            else:
                matrix.fp += 1
            lines.append(f"FAIL {tid}: {label} (exit={rc}, expected {expected})")

    lines.append(f"{matrix.passed}/{matrix.total} passed")
    return "\n".join(lines), matrix


def handle_submit(source_code: str, tests: list[dict], compile_cmd: str, src_ext: str, task_dir: Path) -> TestResult:
    with tempfile.TemporaryDirectory() as tmpdir:
        src_name = f"solution{src_ext}"
        src = Path(tmpdir) / src_name
        src.write_text(source_code)

        # Compile
        try:
            comp = subprocess.run(
                shlex.split(compile_cmd) + ["-o", "solution", src_name],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return TestResult(
                compiled=False,
                compiler_output="Compilation timed out (30s limit).",
                test_output="",
                matrix=ConfusionMatrix(),
            )

        if comp.returncode != 0:
            return TestResult(
                compiled=False,
                compiler_output=comp.stderr,
                test_output="",
                matrix=ConfusionMatrix(),
            )

        binary = Path(tmpdir) / "solution"
        test_output, matrix = run_tests(binary, tests, task_dir)

        return TestResult(
            compiled=True,
            compiler_output=comp.stderr,
            test_output=test_output,
            matrix=matrix,
        )


def format_tool_result(result: TestResult) -> str:
    parts = []
    if not result.compiled:
        parts.append("COMPILATION FAILED")
        parts.append(result.compiler_output)
        return "\n".join(parts)

    m = result.matrix
    parts.append(f"Compiled successfully. Test results: {m.passed}/{m.total} passed.")
    if m.passed < m.total:
        # Include FAIL lines so the model can fix bugs
        for line in result.test_output.splitlines():
            if line.startswith("FAIL "):
                parts.append(line)
    return "\n".join(parts)


def auto_detect_model(api_base: str, api_key: str) -> str:
    """Auto-detect model from a local OpenAI-compatible server via /models endpoint."""
    url = api_base.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "validation-bench/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError) as e:
        print(f"Error: cannot reach {url}: {e}", file=sys.stderr)
        sys.exit(1)
    model_ids = [m["id"] for m in data.get("data", [])]
    if not model_ids:
        print("Error: no models available at the endpoint.", file=sys.stderr)
        sys.exit(1)
    model_id = model_ids[0]
    print(f"Auto-detected model: {model_id}")
    return model_id


def derive_slug(model: str, reasoning_effort: str | None = None) -> str:
    """Derive a filesystem-friendly slug from a LiteLLM model name.

    Examples:
        anthropic/claude-opus-4-6        -> claude-opus-4.6
        anthropic/claude-sonnet-4-20250514 -> claude-sonnet-4.0
        minimax/MiniMax-M2.5             -> minimax-m2.5
        openai/gpt-5.3-codex             -> gpt-5.3-codex
        openai/gpt-5.3-codex + high      -> gpt-5.3-codex-high
        zai/glm-5                        -> glm-5
        moonshot/kimi-k2.5               -> kimi-k2.5
        mistral/devstral-latest          -> devstral
        openai/Qwen3.5-122B-A10B-UD-Q6_K_XL-00001-of-00004.gguf -> qwen3.5-122b-a10b-q6_k_xl
        openai/Qwen3.5-397B-A17B-UD-IQ3_XXS-00001-of-00004.gguf -> qwen3.5-397b-a17b-iq3_xxs
    """
    # Strip provider prefix
    if "/" in model:
        name = model.split("/", 1)[1]
    else:
        name = model

    # Strip GGUF filenames: keep quant level, drop shard suffix and extension
    # e.g. Qwen3.5-122B-A10B-UD-Q6_K_XL-00001-of-00004.gguf -> Qwen3.5-122B-A10B-Q6_K_XL
    # e.g. model-UD-IQ3_XXS-00001-of-00004.gguf -> model-IQ3_XXS
    name = re.sub(r'-UD-([A-Za-z0-9_]+)(-\d+-of-\d+)?\.gguf$', r'-\1', name)
    name = re.sub(r'(-\d+-of-\d+)?\.gguf$', '', name, flags=re.IGNORECASE)

    name = name.lower()

    # Strip "-latest" suffix
    name = re.sub(r'-latest$', '', name)

    # Map Claude model IDs to friendly versions
    name = re.sub(r'^claude-(.*)-4-20250514$', r'claude-\1-4.0', name)
    name = re.sub(r'^claude-(.*)-4-0$', r'claude-\1-4.0', name)
    name = re.sub(r'^claude-(.*)-4-6$', r'claude-\1-4.6', name)

    # Append reasoning effort if present
    if reasoning_effort:
        name = f"{name}-{reasoning_effort}"

    return name


def next_attempt_index(attempts_dir: Path) -> int:
    """Find the next available attempt index in an existing attempts directory."""
    if not attempts_dir.is_dir():
        return 0
    existing = [int(d.name) for d in attempts_dir.iterdir() if d.is_dir() and d.name.isdigit()]
    return max(existing) + 1 if existing else 0


def claim_attempt_dir(attempts_dir: Path) -> tuple[int, Path]:
    """Atomically claim next attempt directory."""
    attempts_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        idx = next_attempt_index(attempts_dir)
        attempt_dir = attempts_dir / str(idx)
        try:
            attempt_dir.mkdir()
            return idx, attempt_dir
        except FileExistsError:
            continue
    raise RuntimeError("Could not claim attempt dir after 100 retries")


def serialize_message(msg) -> dict:
    """Convert a message (dict or LiteLLM/OpenAI object) to a JSON-serializable dict."""
    if isinstance(msg, dict):
        return msg
    return msg.model_dump(exclude_none=True)


def save_attempt_log(attempt_dir: Path, messages: list):
    """Save the full conversation transcript as messages.json."""
    serialized = [serialize_message(m) for m in messages]
    (attempt_dir / "messages.json").write_text(
        json.dumps(serialized, indent=2, ensure_ascii=False)
    )


def run_attempt(
    model: str,
    user_prompt: str,
    tests: list[dict],
    max_turns: int,
    sampling_params: dict,
    attempts_dir: Path,
    compile_cmd: str,
    src_ext: str,
    task_dir: Path,
    api_base: str | None = None,
    api_key: str | None = None,
    timeout: float = 600,
) -> AttemptResult | InfraFailure:
    staging = tempfile.TemporaryDirectory()
    staging_dir = Path(staging.name)
    submissions_dir = staging_dir / "submissions"
    submissions_dir.mkdir()

    messages = [{"role": "user", "content": user_prompt}]
    submission_count = 0
    submission_results: list[Submission] = []
    api_error: Exception | None = None
    error_turn = -1
    start = time.time()

    for turn in range(max_turns):
        try:
            response = litellm.completion(
                model=model,
                messages=messages,
                tools=[SUBMIT_TOOL],
                tool_choice="required",
                api_base=api_base,
                api_key=api_key,
                timeout=timeout,
                cache_control_injection_points=[
                    {"location": "message", "index": 0},
                ],
                **sampling_params,
            )
        except Exception as e:
            _log(f"  API error on turn {turn}: {e}")
            api_error = e
            error_turn = turn
            break

        choice = response.choices[0]
        assistant_msg = choice.message
        finish_reason = choice.finish_reason

        # Convert to dict immediately to avoid Pydantic serialization warnings
        # on subsequent litellm.completion() calls and during save_attempt_log().
        messages.append(serialize_message(assistant_msg))

        if finish_reason == "length":
            _log(f"  turn {turn}: response truncated (max_tokens too low)")

        if not assistant_msg.tool_calls:
            # Model stopped without calling a tool
            break

        for tool_call in assistant_msg.tool_calls:
            if tool_call.function.name != "submit":
                tool_result_str = f"Unknown tool: {tool_call.function.name}. Use the `submit` tool."
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result_str,
                })
                continue

            try:
                args = json.loads(tool_call.function.arguments)
                source_code = args["source_code"]
            except (json.JSONDecodeError, KeyError) as e:
                tool_result_str = f"Invalid tool arguments: {e}. Pass source_code as a string."
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result_str,
                })
                continue

            submission_count += 1
            # Save submission source code
            sub_dir = submissions_dir / str(submission_count)
            sub_dir.mkdir()
            (sub_dir / f"solution{src_ext}").write_text(source_code)

            result = handle_submit(source_code, tests, compile_cmd, src_ext, task_dir)

            # Save compiler and test output
            (sub_dir / "compiler.txt").write_text(result.compiler_output)
            if result.compiled:
                (sub_dir / "tests.txt").write_text(result.test_output)

            tool_result_str = format_tool_result(result)

            if result.compiled:
                submission_results.append(Submission(turn=turn, matrix=result.matrix))
                m = result.matrix
                status = f"{m.passed}/{m.total} (TP={m.tp} FN={m.fn} FP={m.fp} TN={m.tn}) MCC={m.mcc:.3f}"
            else:
                error = "compile_timeout" if "timed out" in result.compiler_output else "compile_error"
                submission_results.append(Submission(turn=turn, error=error))
                status = error.upper()

            _log(f"  turn {turn}, submission {submission_count}: {status}")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result_str,
            })

        # Early exit if all tests passed
        if submission_results and submission_results[-1].matrix:
            m = submission_results[-1].matrix
            if m.passed == m.total and m.total > 0:
                break

    elapsed = time.time() - start

    # If API error occurred, treat entire attempt as infrastructure failure
    if api_error is not None:
        staging.cleanup()
        error_type = "timeout" if "timeout" in str(api_error).lower() else "api_error"
        return InfraFailure(
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            turn=error_turn,
            error_type=error_type,
            error_message=str(api_error),
        )

    # No submissions at all (model never called submit) — also infra failure
    if submission_count == 0:
        staging.cleanup()
        return InfraFailure(
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            turn=turn if 'turn' in dir() else 0,
            error_type="no_submissions",
            error_message="Model completed without making any submissions",
        )

    # Save debug logs
    attempt_index, attempt_dir = claim_attempt_dir(attempts_dir)
    shutil.move(str(submissions_dir), str(attempt_dir / "submissions"))
    save_attempt_log(attempt_dir, messages)

    staging.cleanup()

    return AttemptResult(
        attempt_index=attempt_index,
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        elapsed_seconds=round(elapsed, 1),
        submissions=submission_results,
    )


def main():
    parser = argparse.ArgumentParser(description="AI Coding Benchmark Harness")
    parser.add_argument("--task", required=True, help="Task name (directory under tasks/)")
    parser.add_argument("--n-attempts", type=int, default=1, help="Number of independent attempts")
    parser.add_argument("--api-base", default="http://localhost:8080/v1", help="API base URL (for local/custom endpoints)")
    parser.add_argument("--api-key", default=None, help="API key (or set OPENAI_API_KEY / ANTHROPIC_API_KEY env var)")
    parser.add_argument("--model", default="", help="Model name in LiteLLM format: anthropic/claude-sonnet-4-20250514, openai/gpt-4o, or bare name for local servers (empty = auto-detect from local server)")
    parser.add_argument("--temperature", type=float, default=None, help="Sampling temperature (omit to use server default)")
    parser.add_argument("--reasoning-effort", choices=["low", "medium", "high"], default=None, help="Reasoning effort for reasoning models (low/medium/high)")
    parser.add_argument("--max-tokens", type=int, default=32768, help="Max tokens per response (default: 32768)")
    parser.add_argument("--max-turns", type=int, default=10, help="Max conversation turns per attempt")
    parser.add_argument("--timeout", type=float, default=600, help="API request timeout in seconds (default: 600)")
    parser.add_argument("--slug", default=None, help="Model slug for results directory (default: auto-derived from model name)")
    parser.add_argument("--results-dir", default="results", help="Base results directory (default: results/)")
    parser.add_argument("--data-dir", default=None, help="Base data directory for attempts (default: ~/.vb-data, env: VB_DATA_DIR)")
    args = parser.parse_args()

    # Resolve task directory
    tasks_dir = Path(__file__).parent / "tasks" / args.task
    if not tasks_dir.is_dir():
        print(f"Error: task directory not found: {tasks_dir}", file=sys.stderr)
        sys.exit(1)

    prompt_file = tasks_dir / "prompt.txt"
    tests_file = tasks_dir / "tests.jsonl"
    for f in [prompt_file, tests_file]:
        if not f.exists():
            print(f"Error: missing file: {f}", file=sys.stderr)
            sys.exit(1)

    compile_file = tasks_dir / "compile"
    if compile_file.exists():
        compile_cmd = compile_file.read_text().strip()
    else:
        compile_cmd = "clang++ -std=c++17 -O2"

    compiler_binary = shlex.split(compile_cmd)[0]
    src_ext = ".cpp" if "++" in compiler_binary else ".c"

    user_prompt = prompt_file.read_text()
    user_prompt = user_prompt.replace("{compile_cmd}", compile_cmd)
    tests = load_tests(tests_file)

    api_base = args.api_base
    api_key = args.api_key

    if args.model:
        model = args.model
        if "/" in model:
            api_base = None
        else:
            model = f"openai/{model}"
    else:
        bare_model = auto_detect_model(api_base, api_key or "no-key")
        model = f"openai/{bare_model}"

    # Build sampling params
    sampling_params = {"max_tokens": args.max_tokens}
    if args.temperature is not None:
        sampling_params["temperature"] = args.temperature
    if args.reasoning_effort is not None:
        sampling_params["reasoning_effort"] = args.reasoning_effort

    # Resolve directories
    slug = args.slug or derive_slug(model, args.reasoning_effort)
    results_base = Path(__file__).parent / args.results_dir
    results_file = results_base / args.task / f"{slug}.jsonl"

    data_dir_base = Path(args.data_dir or os.environ.get("VB_DATA_DIR", "") or Path.home() / ".vb-data")
    data_run_dir = data_dir_base / args.task / slug
    attempts_dir = data_run_dir / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)

    # Check for existing attempts
    existing = next_attempt_index(attempts_dir)
    if existing > 0:
        print(f"Appending to existing run ({existing} attempts already present)")

    print(f"Running task '{args.task}' with model '{model}'")
    sampling_str = ", ".join(f"{k}={v}" for k, v in sampling_params.items()) or "server defaults"
    print(f"Attempts: {args.n_attempts} | Max turns: {args.max_turns} | Sampling: {sampling_str}")
    print(f"Debug logs: {data_run_dir}")
    print(f"Results: {results_file}")
    print("-" * 60)

    results: list[AttemptResult] = []
    failures: list[InfraFailure] = []

    try:
        for i in range(args.n_attempts):
            _log(f"\n--- Attempt {i + 1}/{args.n_attempts} ---")
            r = run_attempt(
                model=model,
                user_prompt=user_prompt,
                tests=tests,
                max_turns=args.max_turns,
                sampling_params=sampling_params,
                attempts_dir=attempts_dir,
                compile_cmd=compile_cmd,
                src_ext=src_ext,
                task_dir=tasks_dir,
                api_base=api_base,
                api_key=api_key,
                timeout=args.timeout,
            )
            if isinstance(r, InfraFailure):
                failures.append(r)
                _log(f"  Infrastructure failure: {r.error_type}: {r.error_message}")
            else:
                results.append(r)
                _log(f"  [attempt {r.attempt_index}] debug logs saved")
    except KeyboardInterrupt:
        print("\n\nInterrupted! Showing results collected so far.")

    # Append failures to failures.jsonl (debug logs)
    if failures:
        failures_file = data_run_dir / "failures.jsonl"
        with open(failures_file, "a") as f:
            for fail in failures:
                f.write(json.dumps({
                    "timestamp": fail.timestamp,
                    "turn": fail.turn,
                    "error_type": fail.error_type,
                    "error_message": fail.error_message,
                }) + "\n")
        print(f"\n{len(failures)} infrastructure failure(s) logged to {failures_file}")

    # Append results to JSONL (version-controlled)
    if results:
        results_file.parent.mkdir(parents=True, exist_ok=True)
        with open(results_file, "a") as f:
            for r in results:
                record = {
                    "task": args.task,
                    "model": model,
                    "slug": slug,
                    "timestamp": r.timestamp,
                    "attempt": r.attempt_index,
                    "elapsed_seconds": r.elapsed_seconds,
                    "sampling_params": sampling_params,
                    "submissions": [
                        {"turn": s.turn, "matrix": {"tp": s.matrix.tp, "fn": s.matrix.fn,
                                                    "fp": s.matrix.fp, "tn": s.matrix.tn}}
                        if s.matrix else
                        {"turn": s.turn, "error": s.error}
                        for s in r.submissions
                    ],
                }
                f.write(json.dumps(record) + "\n")

        print(f"\nResults appended to {results_file}")


if __name__ == "__main__":
    main()
