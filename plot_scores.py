#!/usr/bin/env python
"""Generate horizontal boxplots of best-submission MCC per attempt, grouped by model slug."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


def load_attempt_scores(results_file: Path, task: str, exclude: list[str] | None = None
                        ) -> dict[str, list[float]]:
    """Read results.jsonl → {slug: [max_mcc_per_attempt]}."""
    # First pass: collect best MCC per (attempt_id, slug)
    best: dict[tuple[str, str], float] = {}
    for line in results_file.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("task") != task:
            continue
        slug = r.get("slug", "")
        if exclude and slug in exclude:
            continue
        mcc = r.get("mcc")
        if mcc is None:
            continue
        key = (r["attempt_id"], slug)
        best[key] = max(best.get(key, -1.0), mcc)

    # Group by slug
    by_slug: dict[str, list[float]] = defaultdict(list)
    for (_, slug), mcc in best.items():
        by_slug[slug].append(mcc)
    return dict(by_slug)


FIRST_PARTY_PREFIXES = ("gpt-", "claude-", "o1-", "o3-", "o4-")
COLOR_FIRST_PARTY = "#4C72B0"
COLOR_OSS = "#55A868"


def _is_first_party(slug: str) -> bool:
    return any(slug.startswith(p) for p in FIRST_PARTY_PREFIXES)


def plot_boxplots(scores: dict[str, list[float]], task: str, output: Path):
    slugs = sorted(scores.keys(), key=lambda s: sorted(scores[s])[len(scores[s]) // 2])
    data = [scores[s] for s in slugs]
    labels = [f"{s} (n={len(scores[s])})" for s in slugs]
    colors = [COLOR_FIRST_PARTY if _is_first_party(s) else COLOR_OSS for s in slugs]

    fig, ax = plt.subplots(figsize=(10, max(3, len(slugs) * 0.45)))
    bp = ax.boxplot(data, vert=False, patch_artist=True, widths=0.5,
                    showmeans=True,
                    meanprops=dict(marker="D", markerfacecolor="white",
                                   markeredgecolor="#333", markersize=4),
                    medianprops=dict(color="white", linewidth=1.5),
                    flierprops=dict(marker="o", markersize=3, alpha=0.5))
    for patch, c in zip(bp["boxes"], colors):
        patch.set_facecolor(c)
        patch.set_alpha(0.7)

    # Background shading per row
    for i, c in enumerate(colors):
        ax.axhspan(i + 0.5, i + 1.5, color=c, alpha=0.06)

    ax.set_yticklabels(labels)
    ax.set_xlabel("Best MCC per attempt")
    ax.set_title(f"Model scores — {task}")
    ax.set_xlim(-0.05, 1.05)
    ax.grid(axis="x", alpha=0.3)

    # Scatter individual points
    for i, (d, c) in enumerate(zip(data, colors)):
        y = [i + 1] * len(d)
        ax.scatter(d, y, color=c, alpha=0.4, s=15, zorder=3)

    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)
    print(f"Saved {output}")


def main():
    parser = argparse.ArgumentParser(description="Plot MCC boxplots per model slug")
    parser.add_argument("--task", default="toml-1.0-cpp", help="Task to plot (default: toml-1.0-cpp)")
    parser.add_argument("--results", default=None, help="Path to results.jsonl")
    parser.add_argument("--output", default=None, help="Output image path (default: plots/<task>.png)")
    parser.add_argument("--exclude", nargs="*", default=[], help="Slugs to exclude")
    args = parser.parse_args()

    results_file = Path(args.results) if args.results else Path(__file__).parent / "results" / "results.jsonl"
    output = Path(args.output) if args.output else Path(__file__).parent / "plots" / f"{args.task}.png"
    output.parent.mkdir(parents=True, exist_ok=True)

    scores = load_attempt_scores(results_file, args.task, args.exclude or None)
    if not scores:
        print(f"No data for task '{args.task}'")
        return
    plot_boxplots(scores, args.task, output)


if __name__ == "__main__":
    main()
