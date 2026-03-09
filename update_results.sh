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

    # Generate chart
    python3 plot_results.py "$task_dir/summary.txt" \
        -o "$task_dir/chart.png" --sort 2>&1
done

# Generate comparison chart
if [ -f results/toml-1.0-cpp/summary.txt ] || [ -f results/toml-1.1-cpp/summary.txt ]; then
    echo "Generating comparison chart..."
    python3 plot_comparison.py -o results/comparison.png 2>&1
fi

echo "Done."
