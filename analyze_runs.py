#!/usr/bin/env python3
"""Aggregate and compare results across multiple benchmark runs."""

import argparse
import json
import re
import sys
from pathlib import Path

SCORE_RE = re.compile(r"(\d+)/(\d+) passed")


def parse_tests_txt(path: Path) -> tuple[int, int]:
    """Parse a tests.txt file, return (passed, total). Returns (0, 0) if missing."""
    if not path.exists():
        return 0, 0
    text = path.read_text()
    m = SCORE_RE.search(text.splitlines()[-1] if text.strip() else "")
    if not m:
        return 0, 0
    return int(m.group(1)), int(m.group(2))


def analyze_run(run_dir: Path, n_attempts: int | None = None) -> dict:
    """Analyze a single run directory, return per-attempt submission scores."""
    attempts_dir = run_dir / "attempts"
    if not attempts_dir.is_dir():
        print(f"Warning: no attempts/ in {run_dir}", file=sys.stderr)
        return {"attempts": []}

    # Sort attempt dirs numerically
    attempt_dirs = sorted(
        [d for d in attempts_dir.iterdir() if d.is_dir()],
        key=lambda d: int(d.name),
    )
    if n_attempts is not None:
        attempt_dirs = attempt_dirs[:n_attempts]

    attempts = []
    for attempt_dir in attempt_dirs:
        subs_dir = attempt_dir / "submissions"
        if not subs_dir.is_dir():
            attempts.append({"submissions": []})
            continue

        sub_dirs = sorted(
            [d for d in subs_dir.iterdir() if d.is_dir()],
            key=lambda d: int(d.name),
        )

        submissions = []
        for sub_dir in sub_dirs:
            passed, total = parse_tests_txt(sub_dir / "tests.txt")
            submissions.append({"passed": passed, "total": total})

        attempts.append({"submissions": submissions})

    return {"attempts": attempts}


def compute_stats(analysis: dict) -> dict:
    """Compute first-turn, best-of-5, best-of-all stats from analysis."""
    first_turns = []
    best_of_5 = []
    best_of_all = []
    total_tests = 0

    for attempt in analysis["attempts"]:
        subs = attempt["submissions"]
        if not subs:
            first_turns.append(0)
            best_of_5.append(0)
            best_of_all.append(0)
            continue

        # Track total from first submission that has total > 0
        for s in subs:
            if s["total"] > 0:
                total_tests = s["total"]
                break

        first_turns.append(subs[0]["passed"])
        best_of_5.append(max(s["passed"] for s in subs[:5]))
        best_of_all.append(max(s["passed"] for s in subs))

    return {
        "n_attempts": len(analysis["attempts"]),
        "total_tests": total_tests,
        "first_turn": first_turns,
        "best_of_5": best_of_5,
        "best_of_all": best_of_all,
    }


def mean(xs: list[int | float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def main():
    parser = argparse.ArgumentParser(description="Analyze and compare benchmark runs")
    parser.add_argument("runs", nargs="+", help="Run directories to analyze")
    parser.add_argument("--labels", default=None, help="Comma-separated model labels (overrides meta.json)")
    parser.add_argument("--n-attempts", type=int, default=None, help="Only use first N attempts per run")
    parser.add_argument("--verbose", action="store_true", help="Show per-attempt detail")
    args = parser.parse_args()

    labels = args.labels.split(",") if args.labels else [None] * len(args.runs)
    if len(labels) != len(args.runs):
        print(f"Error: {len(labels)} labels but {len(args.runs)} runs", file=sys.stderr)
        sys.exit(1)

    rows = []
    for run_path, label in zip(args.runs, labels):
        run_dir = Path(run_path)
        if not run_dir.is_dir():
            print(f"Warning: {run_dir} not found, skipping", file=sys.stderr)
            continue

        # Determine model name
        meta_file = run_dir / "meta.json"
        if label:
            model_name = label
        elif meta_file.exists():
            meta = json.loads(meta_file.read_text())
            model_name = meta.get("model", run_dir.name)
        else:
            model_name = run_dir.name

        analysis = analyze_run(run_dir, args.n_attempts)
        stats = compute_stats(analysis)
        rows.append((model_name, stats))

    if not rows:
        print("No valid runs found.")
        return

    # Print table
    total = rows[0][1]["total_tests"]
    name_width = max(len(r[0]) for r in rows)
    name_width = max(name_width, 5)  # min "Model"

    def fmt_score(values: list, total: int) -> str:
        m = mean(values)
        return f"{m:.1f}/{total}"

    header = (
        f"{'Model':<{name_width}} | {'Attempts':>8} | {'First-turn':>17} | "
        f"{'Best-of-5':>17} | {'Best-of-all':>17}"
    )
    sep = "-" * len(header)
    print(sep)
    print(header)
    print(sep)
    for model_name, stats in rows:
        n = stats["n_attempts"]
        t = stats["total_tests"]
        print(
            f"{model_name:<{name_width}} | {n:>8} | "
            f"{fmt_score(stats['first_turn'], t):>17} | "
            f"{fmt_score(stats['best_of_5'], t):>17} | "
            f"{fmt_score(stats['best_of_all'], t):>17}"
        )
    print(sep)

    if args.verbose:
        for model_name, stats in rows:
            t = stats["total_tests"]
            print(f"\n  {model_name}:")
            for i, (ft, b5, ba) in enumerate(zip(
                stats["first_turn"], stats["best_of_5"], stats["best_of_all"]
            )):
                print(f"    attempt {i}: first={ft}/{t}  best5={b5}/{t}  bestAll={ba}/{t}")


if __name__ == "__main__":
    main()
