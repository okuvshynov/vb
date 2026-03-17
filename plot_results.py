#!/usr/bin/env python3
"""Generate a boxplot + strip chart from analyze_runs.py summary output."""

import argparse
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ATTEMPT_RE = re.compile(
    r"^\s+attempt \d+: scores=([\d,]+)$"
)
MODEL_RE = re.compile(r"^\s{2}(.+):$")


def parse_summary(path: str) -> tuple[OrderedDict[str, list[list[int]]], int]:
    """Parse verbose summary file.

    Returns {model: [[sub0, sub1, ...], ...], ...} and total_tests.
    Each inner list is per-submission scores for one attempt.
    """
    models: OrderedDict[str, list[list[int]]] = OrderedDict()
    current_model = None
    total_tests = 0

    with open(path) as f:
        for line in f:
            m = MODEL_RE.match(line)
            if m:
                current_model = m.group(1).strip()
                models[current_model] = []
                continue

            m = ATTEMPT_RE.match(line)
            if m and current_model is not None:
                scores = [int(x) for x in m.group(1).split(",")]
                models[current_model].append(scores)

    # Infer total_tests from the table header line (e.g. "123.4/678")
    if not total_tests:
        with open(path) as f:
            for line in f:
                m2 = re.search(r"/(\d+)", line)
                if m2:
                    total_tests = int(m2.group(1))
                    break

    return models, total_tests


def best_of_n(submissions: list[list[int]], n: int | None) -> list[int]:
    """Compute best-of-N score per attempt. None means best-of-all."""
    result = []
    for subs in submissions:
        if n is None:
            result.append(max(subs))
        else:
            result.append(max(subs[:n]))
    return result


def main():
    parser = argparse.ArgumentParser(description="Plot benchmark results from summary file")
    parser.add_argument("summary", help="Path to summary.txt (with --verbose detail)")
    parser.add_argument("-o", "--output", default="results/chart.png", help="Output PNG path")
    parser.add_argument("--best-of", type=int, default=None, metavar="N",
                        help="Plot best score out of first N submissions per attempt (default: all)")
    parser.add_argument("--sort", action="store_true", help="Sort models by median score")
    args = parser.parse_args()

    models, total_tests = parse_summary(args.summary)
    if not models:
        print("Error: no per-attempt data found. Run analyze_runs.py with --verbose.", file=sys.stderr)
        sys.exit(1)

    n = args.best_of
    metric_label = f"Best-of-{n}" if n else "Best-of-all"

    # Extract scores per model
    names = list(models.keys())
    scores = [np.array(best_of_n(models[name], n)) for name in names]

    if args.sort:
        order = sorted(range(len(names)), key=lambda i: np.median(scores[i]))
        names = [names[i] for i in order]
        scores = [scores[i] for i in order]

    fig, ax = plt.subplots(figsize=(max(8, len(names) * 1.2), 6))

    positions = np.arange(len(names))

    # Boxplot
    bp = ax.boxplot(
        scores,
        positions=positions,
        widths=0.5,
        patch_artist=True,
        showmeans=True,
        meanprops=dict(marker="D", markerfacecolor="white", markeredgecolor="black", markersize=6),
        medianprops=dict(color="black", linewidth=1.5),
        boxprops=dict(facecolor="#b0d4f1", edgecolor="black", linewidth=1),
        whiskerprops=dict(color="black", linewidth=1),
        capprops=dict(color="black", linewidth=1),
        flierprops=dict(marker="", linewidth=0),  # hide outlier markers, we show all points
    )

    # Strip plot (jittered individual points)
    rng = np.random.default_rng(42)
    for i, s in enumerate(scores):
        jitter = rng.uniform(-0.15, 0.15, size=len(s))
        ax.scatter(
            positions[i] + jitter, s,
            color="#2266aa", alpha=0.6, s=30, zorder=3, edgecolors="white", linewidths=0.5,
        )

    ax.set_xticks(positions)
    ax.set_xticklabels(names, rotation=30, ha="right", fontsize=10)
    ax.set_ylabel(f"Tests passed (out of {total_tests})", fontsize=11)
    ax.set_title(f"{metric_label} score per attempt", fontsize=13, fontweight="bold")
    ax.set_ylim(bottom=0, top=total_tests * 1.05)
    ax.axhline(y=total_tests, color="gray", linestyle="--", alpha=0.4, linewidth=0.8)
    ax.grid(axis="y", alpha=0.3)

    # Trivial baseline: infer task from summary path (results/<task>/summary.txt)
    summary_path = Path(args.summary)
    task_name = summary_path.parent.name
    tests_jsonl = Path("tasks") / task_name / "tests.jsonl"
    if tests_jsonl.exists():
        tests = [json.loads(line) for line in tests_jsonl.open()]
        n_valid = sum(1 for t in tests if t["expected"] == "valid")
        n_invalid = len(tests) - n_valid
        trivial = max(n_valid, n_invalid)
        ax.axhline(y=trivial, color="red", linestyle=":", alpha=0.5, linewidth=1.2)
        ax.text(len(names) - 0.5, trivial + total_tests * 0.01,
                f"trivial ({trivial}/{total_tests})", fontsize=8, color="red", ha="right")

    fig.tight_layout()
    fig.savefig(args.output, dpi=150)
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
