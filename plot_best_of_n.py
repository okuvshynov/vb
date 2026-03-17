#!/usr/bin/env python3
"""Line chart showing how best-of-N score improves with N for each model."""

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from plot_results import parse_summary, best_of_n


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def main():
    parser = argparse.ArgumentParser(description="Plot best-of-N improvement curves")
    parser.add_argument("summary", help="Path to summary.txt (with --verbose detail)")
    parser.add_argument("-o", "--output", default="results/best-of-n.png", help="Output PNG path")
    parser.add_argument("--max-n", type=int, default=5, help="Maximum N to plot (default: 5)")
    parser.add_argument("--sort", action="store_true", help="Sort models by best-of-max score")
    parser.add_argument("--pct", action="store_true", help="Show as percentage instead of raw count")
    args = parser.parse_args()

    models, total_tests = parse_summary(args.summary)
    if not models:
        print("Error: no per-attempt data found.", file=sys.stderr)
        sys.exit(1)

    ns = list(range(1, args.max_n + 1))

    # Compute mean best-of-N for each model and each N
    model_curves = {}
    for name, submissions in models.items():
        curve = []
        for n in ns:
            scores = best_of_n(submissions, n)
            m = mean(scores)
            curve.append(m / total_tests * 100 if args.pct else m)
        model_curves[name] = curve

    names = list(model_curves.keys())
    if args.sort:
        names.sort(key=lambda name: model_curves[name][-1])

    fig, ax = plt.subplots(figsize=(max(8, len(names) * 0.6), 7))

    cmap = plt.cm.tab20
    colors = [cmap(i / max(len(names) - 1, 1)) for i in range(len(names))]

    for i, name in enumerate(names):
        curve = model_curves[name]
        ax.plot(ns, curve, marker="o", markersize=5, linewidth=1.8,
                label=name, color=colors[i])

    ax.set_xticks(ns)
    ax.set_xlabel("N (best of first N submissions)", fontsize=11)
    if args.pct:
        ax.set_ylabel("Mean score (%)", fontsize=11)
        ax.set_ylim(bottom=0, top=105)
    else:
        ax.set_ylabel(f"Mean score (out of {total_tests})", fontsize=11)
        ax.set_ylim(bottom=0, top=total_tests * 1.05)
    ax.set_title("Best-of-N improvement by model", fontsize=13, fontweight="bold")
    ax.grid(axis="both", alpha=0.3)

    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8,
              framealpha=0.9, borderaxespad=0)

    fig.tight_layout()
    fig.savefig(args.output, dpi=150, bbox_inches="tight")
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
