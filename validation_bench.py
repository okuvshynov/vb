#!/usr/bin/env python3
"""AI Coding Benchmark Harness — evaluates models on code generation tasks."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI


@dataclass
class TestResult:
    compiled: bool
    compiler_output: str
    test_output: str
    passed: int
    total: int


@dataclass
class RepeatResult:
    repeat_index: int
    turns_used: int
    submissions: int
    final_passed: int
    final_total: int
    elapsed_seconds: float


SYSTEM_TEMPLATE = """\
You are an expert C++ programmer. Implement the solution described below.
Submit your complete C++ source code using the `submit` tool.
You will receive compilation and test results. Fix and resubmit if needed.

## Specification
{spec}"""

SUBMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit",
        "description": "Submit C++ source code for compilation and testing.",
        "parameters": {
            "type": "object",
            "properties": {
                "source_code": {
                    "type": "string",
                    "description": "Complete C++ source code to compile and test.",
                }
            },
            "required": ["source_code"],
        },
    },
}


def handle_submit(source_code: str, test_sh: Path) -> TestResult:
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "solution.cpp"
        src.write_text(source_code)

        # Compile
        try:
            comp = subprocess.run(
                ["clang++", "-std=c++17", "-O2", "-o", "solution", "solution.cpp"],
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
                passed=0,
                total=0,
            )

        if comp.returncode != 0:
            return TestResult(
                compiled=False,
                compiler_output=comp.stderr,
                test_output="",
                passed=0,
                total=0,
            )

        # Copy test.sh into tmpdir and run
        shutil.copy(test_sh, Path(tmpdir) / "test.sh")
        try:
            run = subprocess.run(
                ["bash", "test.sh", "./solution"],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            return TestResult(
                compiled=True,
                compiler_output=comp.stderr,
                test_output="Test execution timed out (60s limit).",
                passed=0,
                total=0,
            )

        output = run.stdout + run.stderr
        passed, total = parse_test_output(output)

        return TestResult(
            compiled=True,
            compiler_output=comp.stderr,
            test_output=output,
            passed=passed,
            total=total,
        )


def parse_test_output(output: str) -> tuple[int, int]:
    m = re.search(r"ALL (\d+) TESTS PASSED", output)
    if m:
        total = int(m.group(1))
        return total, total

    m = re.search(r"(\d+)/(\d+) TESTS FAILED", output)
    if m:
        failed = int(m.group(1))
        total = int(m.group(2))
        return total - failed, total

    return 0, 0


def format_tool_result(result: TestResult) -> str:
    parts = []
    if not result.compiled:
        parts.append("COMPILATION FAILED")
        parts.append(result.compiler_output)
        return "\n".join(parts)

    parts.append(f"Compiled successfully. Test results: {result.passed}/{result.total} passed.")
    if result.passed < result.total:
        # Include FAIL lines so the model can fix bugs
        for line in result.test_output.splitlines():
            if line.startswith("FAIL:"):
                parts.append(line)
    return "\n".join(parts)


def auto_detect_model(client: OpenAI) -> str:
    models = client.models.list()
    model_ids = [m.id for m in models.data]
    if not model_ids:
        print("Error: no models available at the endpoint.", file=sys.stderr)
        sys.exit(1)
    model_id = model_ids[0]
    print(f"Auto-detected model: {model_id}")
    return model_id


def serialize_message(msg) -> dict:
    """Convert a message (dict or OpenAI object) to a JSON-serializable dict."""
    if isinstance(msg, dict):
        return msg
    return msg.model_dump(exclude_none=True)


def save_repeat_log(repeat_dir: Path, messages: list):
    """Save the full conversation transcript as messages.json."""
    serialized = [serialize_message(m) for m in messages]
    (repeat_dir / "messages.json").write_text(
        json.dumps(serialized, indent=2, ensure_ascii=False)
    )


def run_repeat(
    client: OpenAI,
    model: str,
    system_message: str,
    test_sh: Path,
    max_turns: int,
    temperature: float,
    repeat_index: int,
    repeat_dir: Path,
) -> RepeatResult:
    repeat_dir.mkdir(parents=True, exist_ok=True)
    submissions_dir = repeat_dir / "submissions"
    submissions_dir.mkdir()

    messages = [{"role": "system", "content": system_message}]
    submissions = 0
    last_compiled_result: TestResult | None = None
    start = time.time()

    for turn in range(max_turns):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=[SUBMIT_TOOL],
                tool_choice="auto",
                temperature=temperature,
            )
        except Exception as e:
            print(f"  [repeat {repeat_index}] API error on turn {turn}: {e}", file=sys.stderr)
            break

        choice = response.choices[0]
        assistant_msg = choice.message

        # Append assistant message
        messages.append(assistant_msg)

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
            (sub_dir / "solution.cpp").write_text(source_code)

            result = handle_submit(source_code, test_sh)

            # Save compiler and test output
            (sub_dir / "compiler.txt").write_text(result.compiler_output)
            if result.compiled:
                (sub_dir / "tests.txt").write_text(result.test_output)

            tool_result_str = format_tool_result(result)

            status = "COMPILE_FAIL"
            if result.compiled:
                last_compiled_result = result
                status = f"{result.passed}/{result.total}"

            print(f"  [repeat {repeat_index}] turn {turn}, submission {submissions}: {status}")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_result_str,
            })

        # Early exit if all tests passed
        if last_compiled_result and last_compiled_result.passed == last_compiled_result.total and last_compiled_result.total > 0:
            break

    elapsed = time.time() - start
    final_passed = last_compiled_result.passed if last_compiled_result else 0
    final_total = last_compiled_result.total if last_compiled_result else 0

    # Save conversation transcript
    save_repeat_log(repeat_dir, messages)

    return RepeatResult(
        repeat_index=repeat_index,
        turns_used=min(turn + 1, max_turns) if 'turn' in dir() else 0,
        submissions=submissions,
        final_passed=final_passed,
        final_total=final_total,
        elapsed_seconds=round(elapsed, 1),
    )


def print_summary(results: list[RepeatResult], model: str, task: str, prompt: str):
    print("\n" + "=" * 60)
    print(f"Task: {task} | Prompt: {prompt} | Model: {model} | Repeats: {len(results)}")
    print("=" * 60)

    for r in results:
        score = f"{r.final_passed}/{r.final_total}" if r.final_total > 0 else "0/0"
        status = "PASS" if r.final_passed == r.final_total and r.final_total > 0 else "FAIL"
        print(
            f"  repeat {r.repeat_index}: {score} ({status}) "
            f"| {r.submissions} submissions | {r.turns_used} turns | {r.elapsed_seconds}s"
        )

    scored = [r for r in results if r.final_total > 0]
    if scored:
        scores = [r.final_passed / r.final_total for r in scored]
        mean = sum(scores) / len(scores)
        all_pass = sum(1 for s in scores if s == 1.0)
        print(f"\nMean score: {mean:.2%}")
        print(f"Min: {min(scores):.2%} | Max: {max(scores):.2%}")
        print(f"All-pass rate: {all_pass}/{len(scored)} ({all_pass/len(scored):.0%})")
    else:
        print("\nNo valid submissions across all repeats.")


def main():
    parser = argparse.ArgumentParser(description="AI Coding Benchmark Harness")
    parser.add_argument("--task", required=True, help="Task name (directory under tasks/)")
    parser.add_argument("--n-repeats", type=int, default=1, help="Number of independent runs")
    parser.add_argument("--api-base", default="http://localhost:8080/v1", help="OpenAI-compatible endpoint")
    parser.add_argument("--api-key", default="no-key", help="API key")
    parser.add_argument("--model", default="", help="Model name (empty = auto-detect)")
    parser.add_argument("--temperature", type=float, default=1.0, help="Sampling temperature")
    parser.add_argument("--max-turns", type=int, default=10, help="Max conversation turns per repeat")
    parser.add_argument("--prompt", default="prompt", help="Prompt variant (loads prompt-{name}.txt, or 'prompt' for prompt.txt)")
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
    test_sh = tasks_dir / "test.sh"
    for f in [prompt_file, test_sh]:
        if not f.exists():
            print(f"Error: missing file: {f}", file=sys.stderr)
            sys.exit(1)

    spec = prompt_file.read_text()
    system_message = SYSTEM_TEMPLATE.format(spec=spec)

    client = OpenAI(base_url=args.api_base, api_key=args.api_key)

    model = args.model if args.model else auto_detect_model(client)

    # Create run output directory
    run_dir = Path(tempfile.mkdtemp(prefix="vb_"))
    repeats_dir = run_dir / "repeats"
    repeats_dir.mkdir()

    print(f"Running task '{args.task}' (prompt: {args.prompt}) with model '{model}'")
    print(f"Repeats: {args.n_repeats} | Max turns: {args.max_turns} | Temperature: {args.temperature}")
    print(f"Output: {run_dir}")
    print("-" * 60)

    results = []
    try:
        for i in range(args.n_repeats):
            print(f"\n--- Repeat {i} ---")
            r = run_repeat(
                client=client,
                model=model,
                system_message=system_message,
                test_sh=test_sh,
                max_turns=args.max_turns,
                temperature=args.temperature,
                repeat_index=i,
                repeat_dir=repeats_dir / str(i),
            )
            results.append(r)
    except KeyboardInterrupt:
        print("\n\nInterrupted! Showing results collected so far.")

    if results:
        print_summary(results, model, args.task, args.prompt)
        print(f"\nOutput saved to: {run_dir}")


if __name__ == "__main__":
    main()
