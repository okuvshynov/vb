#!/usr/bin/env python3
"""AI Coding Benchmark Harness — evaluates models on code generation tasks."""

import argparse
import datetime
import json
import os
import math
import re
import secrets
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
    attempt_id: str
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


DOCKER_IMAGE = "vb-sandbox"
COMPILE_CMD = "clang++ -std=c++17 -O2"


class Sandbox:
    """Docker container sandbox for compiling and running untrusted code."""

    def __init__(self):
        self.container_id: str | None = None

    def start(self):
        result = subprocess.run(
            ["docker", "run", "-d", "--rm",
             "--network=none",
             "--memory=512m",
             "--cpus=1",
             "--pids-limit=256",
             "--read-only",
             "--tmpfs=/work:rw,exec,size=64m",
             "--tmpfs=/tmp:rw,size=64m",
             DOCKER_IMAGE, "sleep", "infinity"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start sandbox: {result.stderr}")
        self.container_id = result.stdout.strip()

    def stop(self):
        if self.container_id:
            subprocess.run(["docker", "kill", self.container_id],
                           capture_output=True)
            self.container_id = None

    def _exec(self, cmd: list[str], input_data: bytes | None = None,
              timeout: float = 30) -> subprocess.CompletedProcess:
        full_cmd = ["docker", "exec"]
        if input_data is not None:
            full_cmd.append("-i")
        full_cmd.extend([self.container_id] + cmd)
        return subprocess.run(full_cmd, input=input_data,
                              capture_output=True, timeout=timeout)

    def compile(self, source_code: str) -> tuple[bool, str]:
        """Copy source into container and compile. Returns (success, compiler_output)."""
        # Write source via stdin to avoid mount
        write = self._exec(["sh", "-c", "cat > /work/solution.cpp"],
                           input_data=source_code.encode())
        if write.returncode != 0:
            return False, f"Failed to write source: {write.stderr.decode()}"

        try:
            comp = self._exec(
                ["sh", "-c", f"cd /work && {COMPILE_CMD} -o solution solution.cpp"],
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return False, "Compilation timed out (30s limit)."

        return comp.returncode == 0, comp.stderr.decode()

    def run_binary(self, input_data: bytes) -> int:
        """Run /work/solution with input via stdin. Returns exit code (-1 on timeout)."""
        try:
            proc = self._exec(["/work/solution"], input_data=input_data, timeout=5)
            return proc.returncode
        except subprocess.TimeoutExpired:
            return -1


def run_tests(sandbox: Sandbox, tests: list[dict], task_dir: Path) -> tuple[str, ConfusionMatrix]:
    """Run all test cases against the binary in sandbox, return (output_text, matrix)."""
    matrix = ConfusionMatrix()
    lines = []

    for t in tests:
        input_data = (task_dir / t["input_file"]).read_bytes()

        tid = t.get("id", "?")
        label = t["label"]
        expected = t["expected"]

        rc = sandbox.run_binary(input_data)

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


def handle_submit(source_code: str, tests: list[dict], sandbox: Sandbox, task_dir: Path) -> TestResult:
    compiled, compiler_output = sandbox.compile(source_code)

    if not compiled:
        return TestResult(
            compiled=False,
            compiler_output=compiler_output,
            test_output="",
            matrix=ConfusionMatrix(),
        )

    test_output, matrix = run_tests(sandbox, tests, task_dir)

    return TestResult(
        compiled=True,
        compiler_output=compiler_output,
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


def make_attempt_id(task: str, slug: str) -> str:
    """Generate a unique, sortable attempt ID: <task>_<slug>_YYYYMMDD-HHMMSS-<4hex>."""
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{task}_{slug}_{ts}-{secrets.token_hex(2)}"


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
    attempt_dir: Path,
    task_dir: Path,
    attempt_id: str,
    api_base: str | None = None,
    api_key: str | None = None,
    timeout: float = 600,
) -> AttemptResult | InfraFailure:
    sandbox = Sandbox()
    sandbox.start()

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
    turn = 0

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
            (sub_dir / "solution.cpp").write_text(source_code)

            result = handle_submit(source_code, tests, sandbox, task_dir)

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

    sandbox.stop()

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
            turn=turn,
            error_type="no_submissions",
            error_message="Model completed without making any submissions",
        )

    # Save debug logs
    attempt_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(submissions_dir), str(attempt_dir / "submissions"))
    save_attempt_log(attempt_dir, messages)

    staging.cleanup()

    return AttemptResult(
        attempt_id=attempt_id,
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

    user_prompt = prompt_file.read_text()
    user_prompt = user_prompt.replace("{compile_cmd}", COMPILE_CMD)
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
    results_file = results_base / "results.jsonl"

    data_dir_base = Path(args.data_dir or os.environ.get("VB_DATA_DIR", "") or Path.home() / ".vb-data")
    data_dir_base.mkdir(parents=True, exist_ok=True)

    print(f"Running task '{args.task}' with model '{model}'")
    sampling_str = ", ".join(f"{k}={v}" for k, v in sampling_params.items()) or "server defaults"
    print(f"Attempts: {args.n_attempts} | Max turns: {args.max_turns} | Sampling: {sampling_str}")
    print(f"Debug logs: {data_dir_base}")
    print(f"Results: {results_file}")
    print("-" * 60)

    results_file.parent.mkdir(parents=True, exist_ok=True)
    failures_file = data_dir_base / "failures.jsonl"

    def save_result(r: AttemptResult):
        record = {
            "task": args.task,
            "model": model,
            "slug": slug,
            "timestamp": r.timestamp,
            "attempt_id": r.attempt_id,
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
        with open(results_file, "a") as f:
            f.write(json.dumps(record) + "\n")

    def save_failure(fail: InfraFailure):
        with open(failures_file, "a") as f:
            f.write(json.dumps({
                "timestamp": fail.timestamp,
                "turn": fail.turn,
                "error_type": fail.error_type,
                "error_message": fail.error_message,
            }) + "\n")

    try:
        for i in range(args.n_attempts):
            _log(f"\n--- Attempt {i + 1}/{args.n_attempts} ---")
            attempt_id = make_attempt_id(args.task, slug)
            attempt_dir = data_dir_base / attempt_id
            r = run_attempt(
                model=model,
                user_prompt=user_prompt,
                tests=tests,
                max_turns=args.max_turns,
                sampling_params=sampling_params,
                attempt_dir=attempt_dir,
                task_dir=tasks_dir,
                attempt_id=attempt_id,
                api_base=api_base,
                api_key=api_key,
                timeout=args.timeout,
            )
            if isinstance(r, InfraFailure):
                save_failure(r)
                _log(f"  Infrastructure failure: {r.error_type}: {r.error_message}")
            else:
                save_result(r)
                _log(f"  [{r.attempt_id}] saved to {results_file}")
    except KeyboardInterrupt:
        print("\n\nInterrupted!")


if __name__ == "__main__":
    main()
