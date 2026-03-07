#!/usr/bin/env python3
"""AI Coding Benchmark Harness — evaluates models on code generation tasks."""

import argparse
import json
import re
import shlex
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


@dataclass
class TestResult:
    compiled: bool
    compiler_output: str
    test_output: str
    matrix: ConfusionMatrix


@dataclass
class AttemptResult:
    attempt_index: int
    turns_used: int
    submissions: int
    final_matrix: ConfusionMatrix
    elapsed_seconds: float


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


def run_tests(binary: Path, tests: list[dict], task_dir: Path | None = None) -> tuple[str, ConfusionMatrix]:
    """Run all test cases against the binary, return (output_text, matrix)."""
    matrix = ConfusionMatrix()
    lines = []
    for t in tests:
        if "input_file" in t:
            input_data = (task_dir / t["input_file"]).read_bytes()
        elif "input_hex" in t:
            input_data = bytes.fromhex(t["input_hex"])
        else:
            input_data = t["input"].encode()

        expected = t["expected"]
        tid = t.get("id", "?")
        label = t["label"]

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

    summary = f"{matrix.passed}/{matrix.total} passed"
    lines.append(summary)
    return "\n".join(lines), matrix


def handle_submit(source_code: str, tests: list[dict], compile_cmd: str, src_ext: str, task_dir: Path | None = None) -> TestResult:
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
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
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
    """
    # Strip provider prefix
    if "/" in model:
        name = model.split("/", 1)[1]
    else:
        name = model

    # Strip GGUF filenames to base model name
    name = re.sub(r'-UD-.*\.gguf$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\.gguf$', '', name, flags=re.IGNORECASE)

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
    attempt_index: int,
    attempt_dir: Path,
    compile_cmd: str,
    src_ext: str,
    task_dir: Path | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
    timeout: float = 600,
) -> AttemptResult:
    attempt_dir.mkdir(parents=True, exist_ok=True)
    submissions_dir = attempt_dir / "submissions"
    submissions_dir.mkdir()

    messages = [{"role": "user", "content": user_prompt}]
    submissions = 0
    last_compiled_result: TestResult | None = None
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
                **sampling_params,
            )
        except Exception as e:
            print(f"  [attempt {attempt_index}] API error on turn {turn}: {e}", file=sys.stderr)
            break

        choice = response.choices[0]
        assistant_msg = choice.message
        finish_reason = choice.finish_reason

        # Convert to dict immediately to avoid Pydantic serialization warnings
        # on subsequent litellm.completion() calls and during save_attempt_log().
        messages.append(serialize_message(assistant_msg))

        if finish_reason == "length":
            print(f"  [attempt {attempt_index}] turn {turn}: response truncated (max_tokens too low)", file=sys.stderr)

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

            submissions += 1
            # Save submission source code
            sub_dir = submissions_dir / str(submissions)
            sub_dir.mkdir()
            (sub_dir / f"solution{src_ext}").write_text(source_code)

            result = handle_submit(source_code, tests, compile_cmd, src_ext, task_dir)

            # Save compiler and test output
            (sub_dir / "compiler.txt").write_text(result.compiler_output)
            if result.compiled:
                (sub_dir / "tests.txt").write_text(result.test_output)

            tool_result_str = format_tool_result(result)

            status = "COMPILE_FAIL"
            if result.compiled:
                last_compiled_result = result
                m = result.matrix
                status = f"{m.passed}/{m.total} (TP={m.tp} FN={m.fn} FP={m.fp} TN={m.tn})"

            print(f"  [attempt {attempt_index}] turn {turn}, submission {submissions}: {status}")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result_str,
            })

        # Early exit if all tests passed
        if last_compiled_result:
            m = last_compiled_result.matrix
            if m.passed == m.total and m.total > 0:
                break

    elapsed = time.time() - start
    final_matrix = last_compiled_result.matrix if last_compiled_result else ConfusionMatrix()

    # Save conversation transcript
    save_attempt_log(attempt_dir, messages)

    return AttemptResult(
        attempt_index=attempt_index,
        turns_used=min(turn + 1, max_turns) if 'turn' in dir() else 0,
        submissions=submissions,
        final_matrix=final_matrix,
        elapsed_seconds=round(elapsed, 1),
    )


def print_summary(results: list[AttemptResult], model: str, task: str, prompt: str) -> str:
    lines = []
    lines.append("")
    lines.append("=" * 60)
    lines.append(f"Task: {task} | Prompt: {prompt} | Model: {model} | Attempts: {len(results)}")
    lines.append("=" * 60)

    for r in results:
        m = r.final_matrix
        score = f"{m.passed}/{m.total}" if m.total > 0 else "0/0"
        status = "PASS" if m.passed == m.total and m.total > 0 else "FAIL"
        lines.append(
            f"  attempt {r.attempt_index}: {score} ({status}) "
            f"| TP={m.tp} FN={m.fn} FP={m.fp} TN={m.tn} "
            f"| {r.submissions} submissions | {r.turns_used} turns | {r.elapsed_seconds}s"
        )

    scored = [r for r in results if r.final_matrix.total > 0]
    if scored:
        scores = [r.final_matrix.passed / r.final_matrix.total for r in scored]
        mean = sum(scores) / len(scores)
        all_pass = sum(1 for s in scores if s == 1.0)
        lines.append(f"\nMean score: {mean:.2%}")
        lines.append(f"Min: {min(scores):.2%} | Max: {max(scores):.2%}")
        lines.append(f"All-pass rate: {all_pass}/{len(scored)} ({all_pass/len(scored):.0%})")

        # Aggregate confusion matrix
        agg = ConfusionMatrix(
            tp=sum(r.final_matrix.tp for r in scored),
            fn=sum(r.final_matrix.fn for r in scored),
            fp=sum(r.final_matrix.fp for r in scored),
            tn=sum(r.final_matrix.tn for r in scored),
        )
        n = len(scored)
        lines.append(f"\nAggregate confusion matrix (sum over {n} attempts):")
        lines.append(f"                  Predicted Valid  Predicted Invalid")
        lines.append(f"  Actually Valid   TP={agg.tp:<14d} FN={agg.fn}")
        lines.append(f"  Actually Invalid FP={agg.fp:<14d} TN={agg.tn}")
    else:
        lines.append("\nNo valid submissions across all attempts.")

    summary = "\n".join(lines)
    print(summary)
    return summary


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
    parser.add_argument("--prompt", default="prompt", help="Prompt variant (loads prompt-{name}.txt, or 'prompt' for prompt.txt)")
    parser.add_argument("--timeout", type=float, default=600, help="API request timeout in seconds (default: 600)")
    parser.add_argument("--slug", default=None, help="Model slug for results directory (default: auto-derived from model name)")
    parser.add_argument("--results-dir", default="results", help="Base results directory (default: results/)")
    args = parser.parse_args()

    # Resolve task directory
    tasks_dir = Path(__file__).parent / "tasks" / args.task
    if not tasks_dir.is_dir():
        print(f"Error: task directory not found: {tasks_dir}", file=sys.stderr)
        sys.exit(1)

    if args.prompt == "prompt":
        prompt_file = tasks_dir / "prompt.txt"
    else:
        prompt_file = tasks_dir / f"prompt-{args.prompt}.txt"
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
            # Cloud provider (e.g. "anthropic/claude-sonnet-4-20250514", "openai/gpt-4o"):
            # LiteLLM routes automatically, api_base not needed.
            api_base = None
        else:
            # Bare model name (e.g. "qwen2.5-coder-32b") means local server:
            # prefix with "openai/" so LiteLLM uses the OpenAI-compatible path.
            model = f"openai/{model}"
    else:
        # Auto-detect from local server and prefix with "openai/".
        bare_model = auto_detect_model(api_base, api_key or "no-key")
        model = f"openai/{bare_model}"

    # Build sampling params
    sampling_params = {"max_tokens": args.max_tokens}
    if args.temperature is not None:
        sampling_params["temperature"] = args.temperature
    if args.reasoning_effort is not None:
        sampling_params["reasoning_effort"] = args.reasoning_effort

    # Resolve output directory
    slug = args.slug or derive_slug(model, args.reasoning_effort)
    results_base = Path(__file__).parent / args.results_dir
    run_dir = results_base / args.task / slug
    attempts_dir = run_dir / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)

    # Check for existing attempts (append mode)
    start_index = next_attempt_index(attempts_dir)
    if start_index > 0:
        print(f"Appending to existing run ({start_index} attempts already present)")

    print(f"Running task '{args.task}' (prompt: {args.prompt}) with model '{model}'")
    sampling_str = ", ".join(f"{k}={v}" for k, v in sampling_params.items()) or "server defaults"
    print(f"Attempts: {args.n_attempts} (indices {start_index}–{start_index + args.n_attempts - 1}) | Max turns: {args.max_turns} | Sampling: {sampling_str}")
    print(f"Output: {run_dir}")
    print("-" * 60)

    results = []
    try:
        for i in range(args.n_attempts):
            attempt_index = start_index + i
            print(f"\n--- Attempt {attempt_index} ---")
            r = run_attempt(
                model=model,
                user_prompt=user_prompt,
                tests=tests,
                max_turns=args.max_turns,
                sampling_params=sampling_params,
                attempt_index=attempt_index,
                attempt_dir=attempts_dir / str(attempt_index),
                compile_cmd=compile_cmd,
                src_ext=src_ext,
                task_dir=tasks_dir,
                api_base=api_base,
                api_key=api_key,
                timeout=args.timeout,
            )
            results.append(r)
    except KeyboardInterrupt:
        print("\n\nInterrupted! Showing results collected so far.")

    if results:
        total_attempts = start_index + len(results)
        summary = print_summary(results, model, args.task, args.prompt)
        (run_dir / "summary.txt").write_text(summary.lstrip("\n") + "\n")
        (run_dir / "meta.json").write_text(json.dumps({
            "model": model,
            "task": args.task,
            "prompt": args.prompt,
            "n_attempts": total_attempts,
            "max_turns": args.max_turns,
            "sampling_params": sampling_params,
        }, indent=2) + "\n")
        print(f"\nOutput saved to: {run_dir}")


if __name__ == "__main__":
    main()
