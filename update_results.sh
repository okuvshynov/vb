#!/usr/bin/env bash
# Regenerate summaries and charts from current data.
# Scans results/<task>/<slug>/meta.json to discover runs,
# then calls analyze_runs.py and plot_results.py per task,
# and plot_comparison.py for the cross-task comparison chart.
set -euo pipefail

cd "$(dirname "$0")"

# For each task dir under results/, collect model run dirs that have
# at least one attempt in their data_dir.
for task_dir in results/*/; do
    [ -d "$task_dir" ] || continue
    task=$(basename "$task_dir")

    run_dirs=()
    labels=()

    for model_dir in "$task_dir"*/; do
        [ -d "$model_dir" ] || continue
        meta="$model_dir/meta.json"
        [ -f "$meta" ] || continue

        slug=$(python3 -c "import json; print(json.load(open('$meta'))['slug'])")
        data_dir=$(python3 -c "import json; print(json.load(open('$meta')).get('data_dir',''))")

        # Count attempts
        n=0
        if [ -n "$data_dir" ] && [ -d "$data_dir/attempts" ]; then
            n=$(ls "$data_dir/attempts" 2>/dev/null | wc -l | tr -d ' ')
        elif [ -d "$model_dir/attempts" ]; then
            n=$(ls "$model_dir/attempts" 2>/dev/null | wc -l | tr -d ' ')
        fi

        if [ "$n" -gt 0 ]; then
            run_dirs+=("$model_dir")
            labels+=("$slug")
        fi
    done

    if [ ${#run_dirs[@]} -eq 0 ]; then
        echo "$task: no runs with data, skipping"
        continue
    fi

    label_str=$(IFS=,; echo "${labels[*]}")

    echo "$task: ${#run_dirs[@]} models (${label_str})"

    # Generate summary
    python3 analyze_runs.py --verbose "${run_dirs[@]}" \
        --labels "$label_str" \
        > "$task_dir/summary.txt" 2>&1

    # Generate per-task charts: default (best-of-all) + best-of-N for N=1..5
    python3 plot_results.py "$task_dir/summary.txt" \
        -o "$task_dir/chart.png" --sort 2>&1
    for bo in 1 2 3 4 5; do
        python3 plot_results.py "$task_dir/summary.txt" \
            -o "$task_dir/chart-best-of-$bo.png" --best-of $bo --sort 2>&1
    done

    # Generate best-of-N improvement curves: all models (averaged) + top-tier (per-attempt)
    python3 plot_best_of_n.py "$task_dir/summary.txt" \
        -o "$task_dir/chart-best-of-n.png" --sort --pct 2>&1
    python3 plot_best_of_n.py "$task_dir/summary.txt" \
        -o "$task_dir/chart-best-of-n-top.png" --pct --per-attempt \
        --models "gpt-5.3-codex-high,gpt-5.3-codex-low,claude-opus-4.6" 2>&1
done

# Generate comparison charts: spec vs nospec for each TOML version
for ver in "1.0" "1.1"; do
    spec="results/toml-${ver}-cpp/summary.txt"
    nospec="results/toml-${ver}-cpp-nospec/summary.txt"
    [ -f "$spec" ] || continue
    [ -f "$nospec" ] || { echo "Skipping ${ver} comparison (no nospec summary yet)"; continue; }
    echo "Generating ${ver} spec-vs-nospec comparison..."
    python3 plot_comparison.py \
        --left "$spec" --left-label "with spec" \
        --right "$nospec" --right-label "no spec" \
        -o "results/comparison-${ver}.png" 2>&1
    for bo in 1 2 3 4 5; do
        python3 plot_comparison.py \
            --left "$spec" --left-label "with spec" \
            --right "$nospec" --right-label "no spec" \
            -o "results/comparison-${ver}-best-of-$bo.png" --best-of $bo 2>&1
    done
done

echo ""
./summary.sh
echo ""
echo "Done."
