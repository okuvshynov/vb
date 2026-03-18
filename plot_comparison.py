#!/usr/bin/env python3
"""Side-by-side boxplot comparing two benchmark variants."""

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from plot_results import parse_summary, best_of_n

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
    # qwen3.5-397b-a17b: grouped by quant level (high to low)
    ("qwen3.5-397b-a17b",       "local"),
    ("qwen3.5-397b-a17b-iq3_xxs", "local"),
    ("qwen3.5-397b-a17b-iq2_xxs", "local"),
    ("qwen3.5-397b-a17b-iq1_m",   "local"),
    # qwen3.5-122b-a10b: grouped by quant level (high to low)
    ("qwen3.5-122b-q8",           "local"),
    ("qwen3.5-122b-a10b-q6_k_xl", "local"),
    ("qwen3.5-122b-a10b-iq4_xs",  "local"),
    ("qwen3.5-122b-a10b-iq3_xxs", "local"),
    ("qwen3.5-122b-a10b",         "local"),
])

CATEGORY_COLORS = {
    "proprietary": ("#4878a8", "#6a9fd8"),  # (left, right) box colors
    "api":         ("#d4813f", "#e8a96a"),
    "local":       ("#5a9e5a", "#82c482"),
    "unknown":     ("#888888", "#aaaaaa"),
}

CATEGORY_LABELS = {
    "proprietary": "Proprietary",
    "api":         "Open-weight (API)",
    "local":       "Open-weight (local)",
    "unknown":     "Unknown",
}


def infer_trivial_baseline(summary_path: str) -> float | None:
    """Infer trivial baseline (%) from task's tests.jsonl if available."""
    p = Path(summary_path)
    task_name = p.parent.name
    tests_jsonl = Path("tasks") / task_name / "tests.jsonl"
    if not tests_jsonl.exists():
        return None
    tests = [json.loads(line) for line in tests_jsonl.open()]
    n_valid = sum(1 for t in tests if t["expected"] == "valid")
    n_invalid = len(tests) - n_valid
    return max(n_valid, n_invalid) / len(tests) * 100


def main():
    parser = argparse.ArgumentParser(description="Side-by-side comparison chart")
    parser.add_argument("--left", required=True, help="Path to left summary.txt")
    parser.add_argument("--right", required=True, help="Path to right summary.txt")
    parser.add_argument("--left-label", default=None, help="Label for left variant (default: infer from path)")
    parser.add_argument("--right-label", default=None, help="Label for right variant (default: infer from path)")
    parser.add_argument("-o", "--output", default="results/comparison.png",
                        help="Output PNG path")
    parser.add_argument("--best-of", type=int, default=None, metavar="N",
                        help="Plot best score out of first N submissions per attempt (default: all)")
    args = parser.parse_args()

    left_label = args.left_label or Path(args.left).parent.name
    right_label = args.right_label or Path(args.right).parent.name

    models_left, total_left = parse_summary(args.left)
    models_right, total_right = parse_summary(args.right)

    if not models_left and not models_right:
        print("Error: no data found in either summary file.", file=sys.stderr)
        sys.exit(1)

    # Use models from MODEL_CONFIG that appear in at least one dataset,
    # then append any unknown models sorted alphabetically with "unknown" category.
    all_available = set(models_left.keys()) | set(models_right.keys())
    model_names = [m for m in MODEL_CONFIG if m in all_available]
    unknown = sorted(all_available - set(MODEL_CONFIG.keys()))
    if unknown:
        print(f"Note: models not in MODEL_CONFIG (will use 'unknown' category): {', '.join(unknown)}", file=sys.stderr)
        model_names.extend(unknown)

    if not model_names:
        print("Error: no models match the summary data.", file=sys.stderr)
        sys.exit(1)

    n = len(model_names)
    bo = args.best_of
    metric_label = f"Best-of-{bo}" if bo else "Best-of-all"

    # Normalize to percentage
    def to_pct(submissions, total):
        scores = best_of_n(submissions, bo)
        return [s / total * 100 for s in scores]

    fig, ax = plt.subplots(figsize=(max(10, n * 1.6), 7))

    group_width = 1.0
    box_width = 0.32
    gap = 0.06
    positions_left = []
    positions_right = []

    for i in range(n):
        center = i * group_width
        positions_left.append(center - gap / 2 - box_width / 2)
        positions_right.append(center + gap / 2 + box_width / 2)

    rng = np.random.default_rng(42)

    # Draw category background bands
    prev_cat = None
    band_start = -0.5
    band_colors = {"proprietary": "#e8eef5", "api": "#fdf0e5", "local": "#e8f5e8", "unknown": "#eeeeee"}
    for i, name in enumerate(model_names):
        cat = MODEL_CONFIG.get(name, "unknown")
        if cat != prev_cat and prev_cat is not None:
            ax.axvspan(band_start, i * group_width - 0.5, color=band_colors[prev_cat], alpha=0.5, zorder=0)
            band_start = i * group_width - 0.5
        prev_cat = cat
    if prev_cat:
        ax.axvspan(band_start, n * group_width - 0.5, color=band_colors[prev_cat], alpha=0.5, zorder=0)

    # Plot each model
    for i, name in enumerate(model_names):
        cat = MODEL_CONFIG.get(name, "unknown")
        color_l, color_r = CATEGORY_COLORS[cat]

        for side_models, total, pos, color, hatch in [
            (models_left, total_left, positions_left[i], color_l, None),
            (models_right, total_right, positions_right[i], color_r, "//"),
        ]:
            if name not in side_models:
                continue
            scores = np.array(to_pct(side_models[name], total))

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

    # Trivial baselines
    trivial_left = infer_trivial_baseline(args.left)
    trivial_right = infer_trivial_baseline(args.right)
    if trivial_left is not None:
        ax.axhline(y=trivial_left, color="#4878a8", linestyle=":", alpha=0.6, linewidth=1.2)
        ax.text(n * group_width - 0.5, trivial_left + 0.5,
                f"trivial {left_label} ({trivial_left:.0f}%)",
                fontsize=7, color="#4878a8", ha="right", va="bottom")
    if trivial_right is not None and trivial_right != trivial_left:
        ax.axhline(y=trivial_right, color="#5a9e5a", linestyle=":", alpha=0.6, linewidth=1.2)
        ax.text(n * group_width - 0.5, trivial_right - 1.5,
                f"trivial {right_label} ({trivial_right:.0f}%)",
                fontsize=7, color="#5a9e5a", ha="right", va="top")

    # Title
    ax.set_title(f"TOML Validator — {metric_label} ({left_label} vs {right_label})",
                 fontsize=13, fontweight="bold")

    # Legend
    legend_handles = [
        mpatches.Patch(facecolor="#999999", edgecolor="black", label=left_label),
        mpatches.Patch(facecolor="#bbbbbb", edgecolor="black", hatch="//", label=right_label),
        mpatches.Patch(facecolor="none", edgecolor="none", label=""),  # spacer
    ]
    for cat, label in CATEGORY_LABELS.items():
        color_l, _ = CATEGORY_COLORS[cat]
        legend_handles.append(mpatches.Patch(facecolor=color_l, edgecolor="black", label=label))

    ax.legend(handles=legend_handles, loc="upper left", bbox_to_anchor=(1.01, 1),
              fontsize=8, framealpha=0.9, borderaxespad=0)

    fig.tight_layout()
    fig.savefig(args.output, dpi=150, bbox_inches="tight")
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
