#!/usr/bin/env python3
"""Analyze turn-by-turn improvement: scatter plot of best score vs improvement gained."""

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from analyze_runs import parse_tests_txt, resolve_attempts_dir


# Consistent colors per model across tasks
MODEL_COLORS = {
    "gpt-5.3-codex-high": "#1f77b4",
    "gpt-5.3-codex-low": "#6baed6",
    "claude-opus-4.6": "#2ca02c",
    "claude-sonnet-4.0": "#98df8a",
    "glm-5": "#d62728",
    "kimi-k2.5": "#ff7f0e",
    "minimax-m2.5": "#e377c2",
    "devstral": "#bcbd22",
    # qwen3.5-397b-a17b variants (brown tones, darker = higher quant)
    "qwen3.5-397b-a17b": "#5b3a1a",
    "qwen3.5-397b-a17b-iq3_xxs": "#8c564b",
    "qwen3.5-397b-a17b-iq2_xxs": "#a0725e",
    "qwen3.5-397b-a17b-iq1_m": "#c49c94",
    # qwen3.5-122b-a10b variants (teal tones, darker = higher quant)
    "qwen3.5-122b-q8": "#0a6e6e",
    "qwen3.5-122b-a10b-q6_k_xl": "#17becf",
    "qwen3.5-122b-a10b-iq4_xs": "#7fcdbb",
    "qwen3.5-122b-a10b-iq3_xxs": "#a8dbd9",
    "qwen3.5-122b-a10b": "#aec7e8",
}
_FALLBACK_COLORS = plt.cm.tab20.colors


def collect_attempt_points(run_dir: Path, n_attempts: int | None = None) -> list[tuple[int, int]]:
    """Return [(best_score, best - first), ...] per attempt."""
    attempts_dir = resolve_attempts_dir(run_dir)
    if attempts_dir is None:
        return []

    attempt_dirs = sorted(
        [d for d in attempts_dir.iterdir() if d.is_dir()],
        key=lambda d: int(d.name),
    )
    if n_attempts is not None:
        attempt_dirs = attempt_dirs[:n_attempts]

    points = []
    for attempt_dir in attempt_dirs:
        subs_dir = attempt_dir / "submissions"
        if not subs_dir.is_dir():
            continue
        sub_dirs = sorted(
            [d for d in subs_dir.iterdir() if d.is_dir()],
            key=lambda d: int(d.name),
        )
        if not sub_dirs:
            continue
        scores = []
        for sub_dir in sub_dirs:
            passed, _ = parse_tests_txt(sub_dir / "tests.txt")
            scores.append(passed)
        first = scores[0]
        best = max(scores)
        points.append((best, best - first))
    return points


def discover_task_runs(task_dir: Path) -> list[tuple[str, Path]]:
    """Find all (slug, run_dir) pairs in a task results directory."""
    runs = []
    for d in sorted(task_dir.iterdir()):
        if not d.is_dir():
            continue
        meta_file = d / "meta.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text())
            slug = meta.get("slug", d.name)
        else:
            slug = d.name
        runs.append((slug, d))
    return runs


def get_color(slug: str, idx: int) -> str:
    if slug in MODEL_COLORS:
        return MODEL_COLORS[slug]
    return _FALLBACK_COLORS[idx % len(_FALLBACK_COLORS)]


def main():
    parser = argparse.ArgumentParser(
        description="Scatter plot: best score vs improvement from first turn"
    )
    parser.add_argument(
        "tasks", nargs="+",
        help="Task result directories (e.g. results/toml-1.0-cpp results/toml-1.1-cpp)",
    )
    parser.add_argument("--n-attempts", type=int, default=None, help="Only use first N attempts")
    parser.add_argument("-o", "--output", default="results/turns.png", help="Output PNG path")
    args = parser.parse_args()

    task_dirs = [Path(t) for t in args.tasks]
    for td in task_dirs:
        if not td.is_dir():
            print(f"Warning: {td} not found, skipping", file=sys.stderr)

    task_dirs = [td for td in task_dirs if td.is_dir()]
    if not task_dirs:
        print("No valid task directories found.")
        sys.exit(1)

    # Collect data: {task_name: {slug: [(best, improvement), ...]}}
    all_data = {}
    all_slugs = set()
    trivial_baselines = {}  # task_name -> trivial score (max(#valid, #invalid))
    for td in task_dirs:
        task_name = td.name
        runs = discover_task_runs(td)
        task_data = {}
        for slug, run_dir in runs:
            pts = collect_attempt_points(run_dir, args.n_attempts)
            if pts:
                task_data[slug] = pts
                all_slugs.add(slug)
        all_data[task_name] = task_data

        # Compute trivial baseline from tests.jsonl
        tests_jsonl = Path("tasks") / task_name / "tests.jsonl"
        if tests_jsonl.exists():
            tests = [json.loads(line) for line in tests_jsonl.open()]
            n_valid = sum(1 for t in tests if t["expected"] == "valid")
            n_invalid = len(tests) - n_valid
            trivial_baselines[task_name] = max(n_valid, n_invalid)

    n_tasks = len(all_data)
    # Grid: each task gets [scatter (wide), boxplot (narrow)]
    fig, axes = plt.subplots(
        1, n_tasks * 2, figsize=(6 * n_tasks + 3 * n_tasks, 7),
        gridspec_kw={"width_ratios": [3, 1.2] * n_tasks},
    )
    if n_tasks == 1:
        axes = [axes]  # ensure indexable

    # Stable slug ordering for legend
    slug_order = sorted(all_slugs)

    for task_idx, (task_name, task_data) in enumerate(all_data.items()):
        ax_scatter = axes[task_idx * 2]
        ax_box = axes[task_idx * 2 + 1]

        box_data = []
        box_labels = []
        box_colors = []

        for idx, slug in enumerate(slug_order):
            if slug not in task_data:
                continue
            pts = task_data[slug]
            bests = [p[0] for p in pts]
            improvements = [p[1] for p in pts]
            color = get_color(slug, idx)

            ax_scatter.scatter(
                bests, improvements, c=color, label=slug, s=40, alpha=0.8,
                edgecolors="white", linewidths=0.4, zorder=3,
            )
            box_data.append(improvements)
            box_labels.append(slug)
            box_colors.append(color)

        # Scatter formatting
        ax_scatter.axhline(y=0, color="gray", linestyle="--", alpha=0.5, linewidth=0.8)
        if task_name in trivial_baselines:
            tv = trivial_baselines[task_name]
            ax_scatter.axvline(x=tv, color="red", linestyle=":", alpha=0.5, linewidth=1.2)
            ax_scatter.text(tv - 2, ax_scatter.get_ylim()[1] * 0.95,
                            f"trivial ({tv})", fontsize=7, color="red",
                            ha="right", va="top", rotation=90)
        ax_scatter.set_xlabel("Best score (across turns)", fontsize=10)
        ax_scatter.set_ylabel("Improvement (best − first turn)", fontsize=10)
        ax_scatter.set_title(task_name, fontsize=12, fontweight="bold")
        ax_scatter.grid(alpha=0.3)
        ax_scatter.legend(fontsize=7, loc="upper left", framealpha=0.9)

        # Boxplot
        if box_data:
            bp = ax_box.boxplot(
                box_data, vert=True, patch_artist=True, widths=0.6,
                showmeans=True,
                meanprops=dict(marker="D", markerfacecolor="white",
                               markeredgecolor="black", markersize=3),
                medianprops=dict(color="black", linewidth=1),
                flierprops=dict(marker="", linewidth=0),
            )
            for patch, color in zip(bp["boxes"], box_colors):
                patch.set_facecolor(color)
                patch.set_alpha(0.7)
            ax_box.set_xticklabels(box_labels, rotation=60, ha="right", fontsize=6)
            ax_box.set_title("Improvement", fontsize=10)
            ax_box.grid(axis="y", alpha=0.3)
            ax_box.axhline(y=0, color="gray", linestyle="--", alpha=0.5, linewidth=0.8)

    fig.suptitle("Multi-turn Improvement", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(args.output, dpi=150, bbox_inches="tight")
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
