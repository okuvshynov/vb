#!/usr/bin/env python3
"""Analyze turn-by-turn score improvement across benchmark runs."""

import argparse
import json
import sys
from pathlib import Path

from analyze_runs import parse_tests_txt, resolve_attempts_dir


def collect_turn_data(run_dir: Path, n_attempts: int | None = None) -> list[list[int]]:
    """Collect per-attempt turn scores: [[t1, t2, ...], ...]."""
    attempts_dir = resolve_attempts_dir(run_dir)
    if attempts_dir is None:
        print(f"Warning: no attempts found for {run_dir}", file=sys.stderr)
        return []

    attempt_dirs = sorted(
        [d for d in attempts_dir.iterdir() if d.is_dir()],
        key=lambda d: int(d.name),
    )
    if n_attempts is not None:
        attempt_dirs = attempt_dirs[:n_attempts]

    all_turns = []
    for attempt_dir in attempt_dirs:
        subs_dir = attempt_dir / "submissions"
        if not subs_dir.is_dir():
            all_turns.append([])
            continue
        sub_dirs = sorted(
            [d for d in subs_dir.iterdir() if d.is_dir()],
            key=lambda d: int(d.name),
        )
        scores = []
        for sub_dir in sub_dirs:
            passed, _ = parse_tests_txt(sub_dir / "tests.txt")
            scores.append(passed)
        all_turns.append(scores)

    return all_turns


def mean(xs: list[int | float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def print_per_turn_table(models: list[tuple[str, list[list[int]]]]):
    """Table 1: per-turn average score."""
    # Find max turn count across all models
    max_turns = 0
    for _, turn_data in models:
        for scores in turn_data:
            max_turns = max(max_turns, len(scores))

    if max_turns == 0:
        print("No submission data found.")
        return

    name_width = max(len(name) for name, _ in models)
    name_width = max(name_width, 5)

    # Header
    turn_headers = [f"Turn {i+1}" for i in range(max_turns)]
    header = f"{'Model':<{name_width}}"
    for th in turn_headers:
        header += f" | {th:>12}"
    sep = "-" * len(header)

    print(sep)
    print(header)
    print(sep)

    for model_name, turn_data in models:
        row = f"{model_name:<{name_width}}"
        for t in range(max_turns):
            scores_at_t = [s[t] for s in turn_data if len(s) > t]
            if scores_at_t:
                avg = mean(scores_at_t)
                row += f" | {avg:>6.1f} ({len(scores_at_t):>2})"
            else:
                row += f" | {'':>12}"
        print(row)

    print(sep)


def compute_summary(turn_data: list[list[int]]) -> dict:
    """Compute summary stats from turn data."""
    first_turns = []
    final_minus_first = []
    positive_gains = []
    regressions = 0
    total_pairs = 0
    recovery_successes = 0
    recovery_opportunities = 0

    for scores in turn_data:
        if not scores:
            continue
        first_turns.append(scores[0])
        final_minus_first.append(scores[-1] - scores[0])

        for i in range(len(scores) - 1):
            delta = scores[i + 1] - scores[i]
            total_pairs += 1
            if delta > 0:
                positive_gains.append(delta)
            elif delta < 0:
                regressions += 1
            # Recovery: 0 followed by another turn
            if scores[i] == 0:
                recovery_opportunities += 1
                if scores[i + 1] > 0:
                    recovery_successes += 1

    return {
        "avg_t1": mean(first_turns),
        "avg_gain": mean(positive_gains),
        "regress_pct": (regressions / total_pairs * 100) if total_pairs else 0.0,
        "recovery": (recovery_successes, recovery_opportunities),
        "final_t1": mean(final_minus_first),
    }


def print_summary_table(models: list[tuple[str, list[list[int]]]]):
    """Table 2: summary stats."""
    name_width = max(len(name) for name, _ in models)
    name_width = max(name_width, 5)

    header = (
        f"{'Model':<{name_width}} | {'Avg T1':>7} | {'Avg Gain':>8} | "
        f"{'Regress%':>8} | {'Recovery':>8} | {'Final-T1':>8}"
    )
    sep = "-" * len(header)

    print(sep)
    print(header)
    print(sep)

    for model_name, turn_data in models:
        s = compute_summary(turn_data)
        rec_s, rec_o = s["recovery"]
        rec_str = f"{rec_s}/{rec_o}" if rec_o > 0 else "n/a"
        print(
            f"{model_name:<{name_width}} | {s['avg_t1']:>7.1f} | "
            f"{s['avg_gain']:>+8.1f} | {s['regress_pct']:>7.1f}% | "
            f"{rec_str:>8} | {s['final_t1']:>+8.1f}"
        )

    print(sep)


def print_verbose(models: list[tuple[str, list[list[int]]]]):
    """Print per-attempt submission traces."""
    for model_name, turn_data in models:
        print(f"\n  {model_name}:")
        for i, scores in enumerate(turn_data):
            if not scores:
                print(f"    attempt {i}: (no submissions)")
                continue
            trace = " -> ".join(str(s) for s in scores)
            net = scores[-1] - scores[0]
            print(f"    attempt {i}: {trace}  (net: {net:+d})")


def main():
    parser = argparse.ArgumentParser(description="Analyze turn-by-turn score improvement")
    parser.add_argument("runs", nargs="+", help="Run directories to analyze")
    parser.add_argument("--labels", default=None, help="Comma-separated model labels")
    parser.add_argument("--n-attempts", type=int, default=None, help="Only use first N attempts")
    parser.add_argument("--verbose", action="store_true", help="Show per-attempt traces")
    args = parser.parse_args()

    labels = args.labels.split(",") if args.labels else [None] * len(args.runs)
    if len(labels) != len(args.runs):
        print(f"Error: {len(labels)} labels but {len(args.runs)} runs", file=sys.stderr)
        sys.exit(1)

    models = []
    for run_path, label in zip(args.runs, labels):
        run_dir = Path(run_path)
        if not run_dir.is_dir():
            print(f"Warning: {run_dir} not found, skipping", file=sys.stderr)
            continue

        meta_file = run_dir / "meta.json"
        if label:
            model_name = label
        elif meta_file.exists():
            meta = json.loads(meta_file.read_text())
            model_name = meta.get("slug", meta.get("model", run_dir.name))
        else:
            model_name = run_dir.name

        turn_data = collect_turn_data(run_dir, args.n_attempts)
        models.append((model_name, turn_data))

    if not models:
        print("No valid runs found.")
        return

    print("\n=== Per-Turn Average Score ===\n")
    print_per_turn_table(models)

    print("\n=== Summary ===\n")
    print_summary_table(models)

    if args.verbose:
        print_verbose(models)


if __name__ == "__main__":
    main()
