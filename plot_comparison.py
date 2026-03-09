#!/usr/bin/env python3
"""Side-by-side boxplot comparing toml-1.0-cpp and toml-1.1-cpp results."""

import argparse
import sys
from collections import OrderedDict

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from plot_results import parse_summary

# Model display order and category assignment.
# Keys are slugs (as used by validation_bench.py and update_results.sh).
# Categories: "proprietary" (closed-weight), "api" (open-weight via API), "local" (GGUF/local)
MODEL_CONFIG = OrderedDict([
    ("gpt-5.3-codex-high",  "proprietary"),
    ("gpt-5.3-codex-low",   "proprietary"),
    ("claude-opus-4.6",     "proprietary"),
    ("claude-sonnet-4.0",   "proprietary"),
    ("glm-5",               "api"),
    ("kimi-k2.5",           "api"),
    ("minimax-m2.5",        "api"),
    ("devstral",            "api"),
    ("gpt-oss-120b-f16",    "local"),
    ("qwen3.5-397b-a17b",   "local"),
    ("qwen3.5-122b-q8",     "local"),
])

CATEGORY_COLORS = {
    "proprietary": ("#4878a8", "#6a9fd8"),  # (1.0, 1.1) — blue tones
    "api":         ("#d4813f", "#e8a96a"),   # orange tones
    "local":       ("#5a9e5a", "#82c482"),   # green tones
}

CATEGORY_LABELS = {
    "proprietary": "Proprietary",
    "api":         "Open-weight (API)",
    "local":       "Open-weight (local)",
}


def main():
    parser = argparse.ArgumentParser(description="Side-by-side comparison chart")
    parser.add_argument("--v10", default="results/toml-1.0-cpp/summary.txt",
                        help="Path to toml-1.0-cpp summary.txt")
    parser.add_argument("--v11", default="results/toml-1.1-cpp/summary.txt",
                        help="Path to toml-1.1-cpp summary.txt")
    parser.add_argument("-o", "--output", default="results/comparison.png",
                        help="Output PNG path")
    parser.add_argument("--metric", default="best5", choices=["first", "best5", "bestAll"],
                        help="Which metric to plot (default: best5)")
    args = parser.parse_args()

    models_10, total_10 = parse_summary(args.v10)
    models_11, total_11 = parse_summary(args.v11)

    if not models_10 and not models_11:
        print("Error: no data found in either summary file.", file=sys.stderr)
        sys.exit(1)

    # Use models from MODEL_CONFIG that appear in at least one dataset
    all_available = set(models_10.keys()) | set(models_11.keys())
    model_names = [m for m in MODEL_CONFIG if m in all_available]

    if not model_names:
        print("Error: no models in MODEL_CONFIG match the summary data.", file=sys.stderr)
        print(f"  Summary models: {all_available}", file=sys.stderr)
        sys.exit(1)

    n = len(model_names)
    metric = args.metric
    metric_label = {"first": "First-turn", "best5": "Best-of-5", "bestAll": "Best-of-all"}[metric]

    # Normalize to percentage
    def to_pct(attempts, total):
        return [a[metric] / total * 100 for a in attempts]

    fig, ax = plt.subplots(figsize=(max(10, n * 1.6), 7))

    group_width = 1.0
    box_width = 0.32
    gap = 0.06  # gap between 1.0 and 1.1 boxes
    positions_10 = []
    positions_11 = []

    for i in range(n):
        center = i * group_width
        positions_10.append(center - gap / 2 - box_width / 2)
        positions_11.append(center + gap / 2 + box_width / 2)

    rng = np.random.default_rng(42)

    # Draw category background bands
    prev_cat = None
    band_start = -0.5
    band_colors = {"proprietary": "#e8eef5", "api": "#fdf0e5", "local": "#e8f5e8"}
    for i, name in enumerate(model_names):
        cat = MODEL_CONFIG[name]
        if cat != prev_cat and prev_cat is not None:
            ax.axvspan(band_start, i * group_width - 0.5, color=band_colors[prev_cat], alpha=0.5, zorder=0)
            band_start = i * group_width - 0.5
        prev_cat = cat
    # Final band
    if prev_cat:
        ax.axvspan(band_start, n * group_width - 0.5, color=band_colors[prev_cat], alpha=0.5, zorder=0)

    # Plot each model
    for i, name in enumerate(model_names):
        cat = MODEL_CONFIG[name]
        color_10, color_11 = CATEGORY_COLORS[cat]

        for version, models_data, total, pos, color, hatch in [
            ("1.0", models_10, total_10, positions_10[i], color_10, None),
            ("1.1", models_11, total_11, positions_11[i], color_11, "//"),
        ]:
            if name not in models_data:
                continue
            scores = np.array(to_pct(models_data[name], total))

            bp = ax.boxplot(
                [scores],
                positions=[pos],
                widths=box_width,
                patch_artist=True,
                showmeans=True,
                meanprops=dict(marker="D", markerfacecolor="white", markeredgecolor="black", markersize=4),
                medianprops=dict(color="black", linewidth=1.2),
                boxprops=dict(facecolor=color, edgecolor="black", linewidth=0.8),
                whiskerprops=dict(color="black", linewidth=0.8),
                capprops=dict(color="black", linewidth=0.8),
                flierprops=dict(marker="", linewidth=0),
            )
            if hatch:
                for patch in bp["boxes"]:
                    patch.set_hatch(hatch)

            # Jittered strip
            jitter = rng.uniform(-box_width * 0.3, box_width * 0.3, size=len(scores))
            ax.scatter(
                pos + jitter, scores,
                color=color, alpha=0.7, s=20, zorder=3,
                edgecolors="white", linewidths=0.4,
            )

    # X-axis
    ax.set_xticks([i * group_width for i in range(n)])
    ax.set_xticklabels(model_names, rotation=35, ha="right", fontsize=9)

    # Y-axis
    ax.set_ylabel("Tests passed (%)", fontsize=11)
    ax.set_ylim(bottom=0, top=105)
    ax.axhline(y=100, color="gray", linestyle="--", alpha=0.4, linewidth=0.8)
    ax.grid(axis="y", alpha=0.3)

    # Title
    ax.set_title(f"TOML Validator Benchmark — {metric_label} score (1.0 vs 1.1)", fontsize=13, fontweight="bold")

    # Legend: version + category
    legend_handles = []
    # Version indicators
    legend_handles.append(mpatches.Patch(facecolor="#999999", edgecolor="black", label="TOML 1.0"))
    legend_handles.append(mpatches.Patch(facecolor="#bbbbbb", edgecolor="black", hatch="//", label="TOML 1.1"))
    legend_handles.append(mpatches.Patch(facecolor="none", edgecolor="none", label=""))  # spacer
    # Category indicators
    for cat, label in CATEGORY_LABELS.items():
        color_10, _ = CATEGORY_COLORS[cat]
        legend_handles.append(mpatches.Patch(facecolor=color_10, edgecolor="black", label=label))

    ax.legend(handles=legend_handles, loc="upper left", bbox_to_anchor=(1.01, 1),
              fontsize=8, framealpha=0.9, borderaxespad=0)

    fig.tight_layout()
    fig.savefig(args.output, dpi=150, bbox_inches="tight")
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
