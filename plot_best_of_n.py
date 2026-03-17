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
    parser.add_argument("--models", default=None,
                        help="Comma-separated list of model slugs to include (default: all)")
    parser.add_argument("--per-attempt", action="store_true",
                        help="Show individual attempt lines instead of averaging")
    args = parser.parse_args()

    models, total_tests = parse_summary(args.summary)
    if not models:
        print("Error: no per-attempt data found.", file=sys.stderr)
        sys.exit(1)

    # Filter models if requested
    if args.models:
        wanted = [m.strip() for m in args.models.split(",")]
        models = {k: v for k, v in models.items() if k in wanted}
        if not models:
            print(f"Error: none of the requested models found.", file=sys.stderr)
            sys.exit(1)

    ns = list(range(1, args.max_n + 1))

    def to_val(score):
        return score / total_tests * 100 if args.pct else score

    if args.per_attempt:
        _plot_per_attempt(models, ns, to_val, args, total_tests)
    else:
        _plot_averaged(models, ns, to_val, args, total_tests)


def _plot_averaged(models, ns, to_val, args, total_tests):
    # Compute mean best-of-N for each model and each N
    model_curves = {}
    for name, submissions in models.items():
        curve = []
        for n in ns:
            scores = best_of_n(submissions, n)
            curve.append(to_val(mean(scores)))
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

    _finish_plot(ax, fig, ns, args, total_tests, "Best-of-N improvement by model")


def _plot_per_attempt(models, ns, to_val, args, total_tests):
    names = list(models.keys())
    if args.sort:
        # Sort by mean best-of-max
        names.sort(key=lambda name: mean(best_of_n(models[name], ns[-1])))

    # Distinct colors per model
    base_colors = plt.cm.tab10.colors
    model_colors = {name: base_colors[i % len(base_colors)] for i, name in enumerate(names)}

    fig, ax = plt.subplots(figsize=(max(8, len(names) * 2), 7))

    for name in names:
        submissions = models[name]
        color = model_colors[name]
        for j, attempt_subs in enumerate(submissions):
            curve = [to_val(max(attempt_subs[:n])) for n in ns]
            ax.plot(ns, curve, marker="o", markersize=3, linewidth=1.0,
                    color=color, alpha=0.5,
                    label=name if j == 0 else None)

    _finish_plot(ax, fig, ns, args, total_tests, "Best-of-N per attempt")


def _finish_plot(ax, fig, ns, args, total_tests, title):
    ax.set_xticks(ns)
    ax.set_xlabel("N (best of first N submissions)", fontsize=11)
    if args.pct:
        ax.set_ylabel("Score (%)", fontsize=11)
        ax.set_ylim(bottom=0, top=105)
    else:
        ax.set_ylabel(f"Score (out of {total_tests})", fontsize=11)
        ax.set_ylim(bottom=0, top=total_tests * 1.05)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.grid(axis="both", alpha=0.3)

    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=8,
              framealpha=0.9, borderaxespad=0)

    fig.tight_layout()
    fig.savefig(args.output, dpi=150, bbox_inches="tight")
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
