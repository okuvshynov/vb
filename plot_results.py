#!/usr/bin/env python3
"""Generate a boxplot + strip chart from analyze_runs.py summary output."""

import argparse
import re
import sys
from collections import OrderedDict

import matplotlib.pyplot as plt
import numpy as np

ATTEMPT_RE = re.compile(
    r"^\s+attempt \d+: first=(\d+)/(\d+)\s+best5=(\d+)/(\d+)\s+bestAll=(\d+)/(\d+)$"
)
MODEL_RE = re.compile(r"^\s{2}(.+):$")


def parse_summary(path: str) -> tuple[OrderedDict[str, list[dict]], int]:
    """Parse verbose summary file. Returns {model: [{first, best5, bestAll, total}, ...], ...}."""
    models: OrderedDict[str, list[dict]] = OrderedDict()
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
                total_tests = int(m.group(2))
                models[current_model].append({
                    "first": int(m.group(1)),
                    "best5": int(m.group(3)),
                    "bestAll": int(m.group(5)),
                    "total": total_tests,
                })

    return models, total_tests


def main():
    parser = argparse.ArgumentParser(description="Plot benchmark results from summary file")
    parser.add_argument("summary", help="Path to summary.txt (with --verbose detail)")
    parser.add_argument("-o", "--output", default="results/chart.png", help="Output PNG path")
    parser.add_argument("--metric", default="best5", choices=["first", "best5", "bestAll"],
                        help="Which metric to plot (default: best5)")
    parser.add_argument("--sort", action="store_true", help="Sort models by median score")
    args = parser.parse_args()

    models, total_tests = parse_summary(args.summary)
    if not models:
        print("Error: no per-attempt data found. Run analyze_runs.py with --verbose.", file=sys.stderr)
        sys.exit(1)

    metric_label = {"first": "First-turn", "best5": "Best-of-5", "bestAll": "Best-of-all"}[args.metric]

    # Extract scores per model
    names = list(models.keys())
    scores = [np.array([a[args.metric] for a in models[n]]) for n in names]

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

    fig.tight_layout()
    fig.savefig(args.output, dpi=150)
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
